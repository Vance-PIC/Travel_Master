"""Stage 2 正式來回查價的候選選擇規則。"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import window_dates
from src.pipeline.filter_engine import annotate_flights


@dataclass(frozen=True)
class RoundTripJob:
    window_key: str
    airline_key: str
    origin: str
    dest: str
    outbound_date: str
    inbound_date: str
    outbound: tuple[dict, ...]
    inbound: tuple[dict, ...]


def _airline_key(flight: dict) -> str:
    return str(flight.get("airline_code") or flight.get("airline_name") or "UNKNOWN")


def _limited(flights: list[dict], limit: int, latest_first: bool = False) -> tuple[dict, ...]:
    return tuple(sorted(
        flights, key=lambda row: row["departure_time"], reverse=latest_first,
    )[:limit])


def build_roundtrip_jobs(
    instances: list[dict],
    destinations: list[str],
    windows: list[str],
    settings: dict,
    direct_only: bool = True,
) -> list[RoundTripJob]:
    """依時段、廉航、直達及同航空公司規則縮減候選。"""
    limit = max(1, int(settings.get("scraper", {}).get(
        "roundtrip_candidate_limit_per_airline", 2,
    )))
    candidates = [
        row for row in annotate_flights(instances, settings)
        if row.get("passes_strict_rule")
        and not row.get("is_lcc")
        and (not direct_only or row.get("stops") == 0)
    ]
    jobs: list[RoundTripJob] = []
    for window_key in windows:
        outbound_date, inbound_dates = window_dates(settings["windows"][window_key])
        for origin in settings["origins"]:
            for dest in destinations:
                outbound = [
                    row for row in candidates
                    if row["trip_type"] == "OUTBOUND"
                    and row["flight_date"] == outbound_date
                    and row["origin_airport"] == origin
                    and row["dest_airport"] == dest
                ]
                for inbound_date in inbound_dates:
                    inbound = [
                        row for row in candidates
                        if row["trip_type"] == "INBOUND"
                        and row["flight_date"] == inbound_date
                        and row["origin_airport"] == dest
                        and row["dest_airport"] == origin
                    ]
                    airlines = {_airline_key(row) for row in outbound} & {
                        _airline_key(row) for row in inbound
                    }
                    for airline in sorted(airlines):
                        selected_outbound = _limited(
                            [row for row in outbound if _airline_key(row) == airline], limit,
                        )
                        selected_inbound = _limited(
                            [row for row in inbound if _airline_key(row) == airline],
                            limit, latest_first=True,
                        )
                        if selected_outbound and selected_inbound:
                            jobs.append(RoundTripJob(
                                window_key=window_key, airline_key=airline,
                                origin=origin, dest=dest,
                                outbound_date=outbound_date, inbound_date=inbound_date,
                                outbound=selected_outbound, inbound=selected_inbound,
                            ))
    return jobs
