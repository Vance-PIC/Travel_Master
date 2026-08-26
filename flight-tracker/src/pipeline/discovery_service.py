"""Stage 1 航班發現結果的正規化與持久化。"""

from __future__ import annotations

from src.config import window_dates
from src.db.database import get_connection, upsert_flight_instance
from src.db.models import FlightInstance


def build_discovery_tasks(
    destinations: list[str], windows: list[str], settings: dict,
) -> list[tuple[str, str, str, str, str]]:
    tasks: list[tuple[str, str, str, str, str]] = []
    for window_key in windows:
        outbound_date, inbound_dates = window_dates(settings["windows"][window_key])
        for dest in destinations:
            for origin in settings["origins"]:
                tasks.append((window_key, origin, dest, outbound_date, "OUTBOUND"))
                tasks.extend(
                    (window_key, dest, origin, inbound_date, "INBOUND")
                    for inbound_date in inbound_dates
                )
    unique: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for task in tasks:
        identity = task[1:]
        if identity not in seen:
            seen.add(identity)
            unique.append(task)
    return unique


def persist_discovered_flights(
    normalized: list[dict], database_path: str,
) -> tuple[dict[tuple[str, str, str, str], int], int, int]:
    instance_ids: dict[tuple[str, str, str, str], int] = {}
    discovered = refreshed = 0
    conn = get_connection(database_path)
    try:
        for flight in normalized:
            if not flight["flight_number"] or flight["flight_number"] == "UNKNOWN":
                continue
            instance_id, created = upsert_flight_instance(conn, FlightInstance(
                flight_date=flight["flight_date"], trip_type=flight["trip_type"],
                origin_airport=flight["origin_airport"], dest_airport=flight["dest_airport"],
                airline_code=flight.get("airline_code"), flight_number=flight["flight_number"],
                departure_time=flight["departure_time"], arrival_time=flight["arrival_time"],
                duration_minutes=flight.get("duration_minutes"), stops=flight.get("stops"),
                aircraft_type=flight.get("aircraft_type"), source_url=flight.get("source_url"),
            ))
            identity = (
                flight["flight_date"], flight["flight_number"],
                flight["origin_airport"], flight["dest_airport"],
            )
            instance_ids[identity] = instance_id
            discovered += int(created)
            refreshed += int(not created)
    finally:
        conn.close()
    return instance_ids, discovered, refreshed
