"""Stage 2 正式來回價格查詢與持久化服務。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from src.db.database import (
    fetch_flight_instances,
    get_connection,
    insert_roundtrip_snapshots,
)
from src.db.models import RoundTripSnapshot
from src.mock.mock_data import mock_roundtrip_price
from src.pipeline.candidate_selector import RoundTripJob, build_roundtrip_jobs
from src.scraper.base import RoundTripQuote
from src.scraper.playwright_crawler import GoogleFlightsCrawler


@dataclass(frozen=True)
class EnrichmentUpdate:
    progress: float
    message: str
    level: str = "info"


def _mock_quotes(job: RoundTripJob) -> list[RoundTripQuote]:
    quotes: list[RoundTripQuote] = []
    for outbound in job.outbound:
        for inbound in job.inbound:
            price = mock_roundtrip_price(
                job.outbound_date, outbound["flight_number"],
                job.inbound_date, inbound["flight_number"],
            )
            if price is not None:
                quotes.append(RoundTripQuote(
                    outbound_flight_number=outbound["flight_number"],
                    inbound_flight_number=inbound["flight_number"],
                    price_twd=price, original_price=float(price), source="mock",
                    source_url="mock://roundtrip-fixture",
                ))
    return quotes


def enrich_roundtrip_prices(
    database_path: str,
    destinations: list[str],
    windows: list[str],
    passenger_count: int,
    direct_only: bool,
    settings: dict,
    mode: str = "crawl",
    crawler_factory: Callable[..., GoogleFlightsCrawler] = GoogleFlightsCrawler,
    flight_instance_ids: set[int] | None = None,
) -> Iterator[EnrichmentUpdate]:
    conn = get_connection(database_path)
    try:
        instances = fetch_flight_instances(conn)
    finally:
        conn.close()
    if flight_instance_ids is not None:
        instances = [row for row in instances if row.get("id") in flight_instance_ids]
    jobs = build_roundtrip_jobs(instances, destinations, windows, settings, direct_only)
    if not jobs:
        yield EnrichmentUpdate(
            1.0, "沒有符合時段的同航空公司去回程候選，正式來回查價略過", "warning",
        )
        return

    crawler = None if mode == "mock" else crawler_factory(
        passenger_count=passenger_count, direct_only=direct_only,
    )
    snapshots: list[RoundTripSnapshot] = []
    for index, job in enumerate(jobs, start=1):
        logs: list[str] = []
        if mode == "mock":
            quotes = _mock_quotes(job)
        else:
            assert crawler is not None
            skip_reason = (
                crawler.query_skip_reason(job.outbound_date)
                or crawler.query_skip_reason(job.inbound_date)
            )
            if skip_reason:
                yield EnrichmentUpdate(
                    index / len(jobs),
                    f"[google_flights] ({index}/{len(jobs)}) [{job.window_key}] "
                    f"{job.origin}↔{job.dest} {job.airline_key}：{skip_reason}",
                    "warning",
                )
                continue
            quotes = crawler.fetch_roundtrip(
                job.origin, job.dest, job.outbound_date, job.inbound_date,
                list(job.outbound),
                {row["flight_number"] for row in job.inbound},
                log=logs.append,
            )
        outbound_ids = {row["flight_number"]: row["id"] for row in job.outbound}
        inbound_ids = {row["flight_number"]: row["id"] for row in job.inbound}
        for quote in quotes:
            outbound_id = outbound_ids.get(quote.outbound_flight_number)
            inbound_id = inbound_ids.get(quote.inbound_flight_number)
            if outbound_id is None or inbound_id is None:
                continue
            snapshots.append(RoundTripSnapshot(
                outbound_flight_instance_id=outbound_id,
                inbound_flight_instance_id=inbound_id,
                window_key=job.window_key, price_twd=quote.price_twd,
                source=quote.source, passenger_count=passenger_count,
                original_currency=quote.original_currency,
                original_price=quote.original_price, source_url=quote.source_url,
            ))
        source = "mock" if mode == "mock" else "google_flights"
        yield EnrichmentUpdate(
            index / len(jobs),
            f"[{source}] ({index}/{len(jobs)}) [{job.window_key}] "
            f"{job.origin}↔{job.dest} {job.airline_key}：取得 {len(quotes)} 組實際來回票價",
        )
        for line in logs:
            yield EnrichmentUpdate(index / len(jobs), f"[google_flights] {line}", "warning")

    conn = get_connection(database_path)
    try:
        inserted, skipped = insert_roundtrip_snapshots(conn, snapshots)
    finally:
        conn.close()
    yield EnrichmentUpdate(
        1.0, f"正式來回票價寫入完成：新增 {inserted} 筆，重複略過 {skipped} 筆",
    )
