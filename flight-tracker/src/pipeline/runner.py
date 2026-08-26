"""Pipeline 執行器：Scraper/Mock -> Normalizer -> FilterEngine -> DB -> (optional) Excel。

以 generator 方式逐步 yield 進度事件字典，供 API 層轉成 SSE 串流，
也可被 CLI 直接消費（列印到 stdout）。
"""

from __future__ import annotations

from typing import Iterator, Optional

from src.config import db_path, load_settings, ordered_window_keys, window_dates
from src.db.database import get_connection, init_db, insert_snapshots
from src.db.models import FlightSnapshot
from src.exporter.excel_exporter import export_snapshots_to_excel
from src.mock.mock_data import generate_mock_flights
from src.pipeline.filter_engine import annotate_flights
from src.pipeline.normalizer import RawFlight, normalize_flight
from src.pipeline.discovery_service import build_discovery_tasks, persist_discovered_flights
from src.pipeline.roundtrip_service import enrich_roundtrip_prices
from src.scraper.base import FlightScraper
from src.scraper.playwright_crawler import GoogleFlightsCrawler
from src.scraper.skyscanner_crawler import SkyscannerCrawler

SCRAPER_FACTORIES = {
    "google_flights": GoogleFlightsCrawler,
    "skyscanner": SkyscannerCrawler,
}


def _event(step: str, message: str, percent: int, level: str = "info") -> dict:
    return {"step": step, "message": message, "percent": percent, "level": level}


def _windows_to_run(window: str, settings: dict) -> list[str]:
    if window in ("ALL", None, ""):
        return ordered_window_keys(settings)
    if window not in settings["windows"]:
        raise ValueError(f"未知時段：{window}")
    return [window]


def _build_scrapers(sources: Optional[list[str]], passenger_count: int = 1,
                    direct_only: bool = True) -> list[FlightScraper]:
    selected = sources or ["google_flights"]
    invalid = [source for source in selected if source not in SCRAPER_FACTORIES]
    if invalid:
        raise ValueError(f"不支援的爬蟲來源：{', '.join(invalid)}")
    # 保留呼叫端順序，同時避免同一來源被重複執行。
    return [SCRAPER_FACTORIES[source](passenger_count=passenger_count, direct_only=direct_only)
            for source in dict.fromkeys(selected)]


def _collect_raw_flights_mock(destinations: list[str], windows: list[str]) -> list[RawFlight]:
    all_flights = generate_mock_flights()
    settings = load_settings()
    dates_to_run = set()
    for w in windows:
        wcfg = settings["windows"][w]
        outbound_date, inbound_dates = window_dates(wcfg)
        dates_to_run.add(outbound_date)
        dates_to_run.update(inbound_dates)

    def _relevant_airport(f: RawFlight) -> str:
        # OUTBOUND：目的地為海外航點 (dest_airport)。
        # INBOUND：海外出發地才是業務上關注的航點 (origin_airport)，dest_airport 是 TPE/TSA。
        return f.dest_airport if f.trip_type == "OUTBOUND" else f.origin_airport

    return [
        f
        for f in all_flights
        if _relevant_airport(f) in destinations and f.flight_date in dates_to_run
    ]


def _crawl_tasks(destinations: list[str], windows: list[str]) -> list[tuple[str, str, str, str, str]]:
    """相容既有測試／呼叫端；實作已移至 discovery_service。"""
    return build_discovery_tasks(destinations, windows, load_settings())


def run_pipeline(
    mode: str,
    destinations: Optional[list[str]] = None,
    window: str = "ALL",
    export: bool = False,
    sources: Optional[list[str]] = None,
    stage: str = "all",
    passenger_count: int = 1,
    direct_only: bool = True,
) -> Iterator[dict]:
    if passenger_count < 1:
        raise ValueError("passenger_count 必須至少為 1")
    if stage not in {"discover", "enrich", "all"}:
        raise ValueError(f"不支援的 Pipeline 階段：{stage}")
    settings = load_settings()
    all_destinations = [d["iata"] for d in settings["destinations"]]
    destinations = destinations or all_destinations
    windows = _windows_to_run(window, settings)
    database_path = db_path()

    yield _event("INIT", f"開始執行 Pipeline (mode={mode}, window={window})", 5)

    init_db(database_path)
    yield _event("INIT", "資料庫連線就緒", 10)
    unsupported_sources = [
        source for source in (sources or ["google_flights"])
        if source != "google_flights"
    ]
    if unsupported_sources:
        yield _event(
            "INIT",
            f"正式兩階段流程目前僅使用 Google Flights；已忽略：{', '.join(unsupported_sources)}",
            10, "warning",
        )

    if stage == "enrich":
        yield _event("ENRICH", "從已確認航班建立候選組合並查詢實際來回票價...", 20)
        for update in enrich_roundtrip_prices(
            database_path, destinations, windows, passenger_count,
            direct_only, settings, mode=mode,
        ):
            yield _event(
                "ENRICH", update.message, 20 + int(update.progress * 75), update.level,
            )
        yield _event("DONE", "正式來回票價補充階段完成", 100)
        return

    yield _event("SCRAPE", f"擷取資料中... 目標航點：{', '.join(destinations)}", 20)
    if mode == "mock":
        raw_flights = _collect_raw_flights_mock(destinations, windows)
        yield _event("SCRAPE", f"擷取完成，共取得 {len(raw_flights)} 筆原始航班資料", 40)
    else:
        # Stage 1 固定用 Google Flights 單程頁確認航班身分；票價只作初步觀測。
        scrapers = _build_scrapers(["google_flights"], passenger_count, direct_only)
        disabled_sources: set[str] = set()
        tasks = _crawl_tasks(destinations, windows)
        raw_flights = []
        for i, (w, origin, dest, date, trip_type) in enumerate(tasks, start=1):
            direction = f"{origin}→{dest}"
            percent = 20 + int(i / len(tasks) * 20)
            trip_label = "去程" if trip_type == "OUTBOUND" else "回程"
            for scraper in scrapers:
                if scraper.source_name in disabled_sources:
                    continue
                skip_reason = scraper.query_skip_reason(date)
                if skip_reason:
                    yield _event(
                        "SCRAPE",
                        f"[{scraper.source_name}] ({i}/{len(tasks)}) [{w}] "
                        f"{direction} {date} {trip_label}：{skip_reason}",
                        percent,
                        level="warning",
                    )
                    continue
                task_logs: list[str] = []
                try:
                    fetched = scraper.fetch(origin, dest, date, trip_type, log=task_logs.append)
                except Exception as exc:  # 單一來源失敗不得中斷其他來源或航段
                    fetched = []
                    task_logs.append(f"{type(exc).__name__}: {exc}")
                raw_flights += fetched
                source = scraper.source_name
                if getattr(scraper, "disabled_reason", None):
                    disabled_sources.add(source)
                yield _event(
                    "SCRAPE",
                    f"[{source}] ({i}/{len(tasks)}) [{w}] {direction} {date} {trip_label}：取得 {len(fetched)} 筆",
                    percent,
                )
                for line in task_logs:
                    yield _event("SCRAPE", f"[{source}] {line}", percent, level="warning")
        yield _event("SCRAPE", f"擷取完成，共取得 {len(raw_flights)} 筆原始航班資料", 40)

    yield _event("NORMALIZE", "正規化時間格式與幣別換算中...", 55)
    normalized = [normalize_flight(f) for f in raw_flights]
    yield _event("NORMALIZE", f"正規化完成，共 {len(normalized)} 筆", 60)

    yield _event("DISCOVER", "確認航班號並建立航班實例...", 65)
    instance_ids, discovered, refreshed = persist_discovered_flights(
        normalized, database_path,
    )
    yield _event("DISCOVER", f"航班確認完成：新增 {discovered}，重新確認 {refreshed}", 69)

    yield _event("FILTER", "套用嚴格時間過濾規則 (SPEC 2.3)...", 70)
    annotated = annotate_flights(normalized)
    passed = sum(1 for f in annotated if f["passes_strict_rule"])
    yield _event(
        "FILTER",
        f"過濾規則檢核完成：{passed}/{len(annotated)} 筆符合硬性時間限制",
        75,
    )

    if stage == "discover":
        yield _event("DONE", "航班發現階段完成（未寫入價格快照）", 100)
        return

    yield _event("ENRICH", "寫入已確認航班的單程初步估價...", 76)
    confirmed = [f for f in normalized if f["flight_number"] and f["flight_number"] != "UNKNOWN"]
    snapshots = [
        FlightSnapshot(
            flight_date=f["flight_date"],
            trip_type=f["trip_type"],
            origin_airport=f["origin_airport"],
            dest_airport=f["dest_airport"],
            flight_number=f["flight_number"],
            departure_time=f["departure_time"],
            arrival_time=f["arrival_time"],
            price_twd=f["price_twd"],
            airline_code=f.get("airline_code"),
            original_currency=f["original_currency"],
            original_price=f["original_price"],
            flight_instance_id=instance_ids.get((f["flight_date"], f["flight_number"], f["origin_airport"], f["dest_airport"])),
            source=f.get("source", "unknown"),
            passenger_count=passenger_count,
        )
        for f in confirmed
    ]
    conn = get_connection(database_path)
    try:
        inserted, skipped = insert_snapshots(conn, snapshots)
    finally:
        conn.close()
    yield _event("DB", f"單程初步估價寫入：新增 {inserted} 筆，重複略過 {skipped} 筆", 77)

    yield _event("ENRICH", "以同航空候選航班查詢實際來回總價...", 78)
    for update in enrich_roundtrip_prices(
        database_path, destinations, windows, passenger_count,
        direct_only, settings, mode=mode,
        flight_instance_ids=set(instance_ids.values()),
    ):
        yield _event(
            "ENRICH", update.message, 78 + int(update.progress * 17), update.level,
        )

    if export:
        yield _event("EXPORT", "產生 Excel 報表中...", 96)
        conn = get_connection(database_path)
        try:
            from src.db.database import fetch_all_snapshots, fetch_roundtrip_snapshots

            all_snaps = fetch_all_snapshots(conn)
            roundtrip_snaps = fetch_roundtrip_snapshots(conn)
        finally:
            conn.close()
        output_path = export_snapshots_to_excel(
            all_snaps, feature="flight_report", roundtrip_snapshots=roundtrip_snaps,
        )
        yield _event("EXPORT", f"Excel 已產生：{output_path}", 99)

    yield _event("DONE", "Pipeline 執行完成", 100)
