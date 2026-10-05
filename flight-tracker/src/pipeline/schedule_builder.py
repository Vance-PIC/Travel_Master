"""去回程配對邏輯：把單段快照組成「航班時刻表」列（地區/日期/去回程航空公司.../票價/備註）。

配對前先保留每個航班、來源、艙等及旅客人數的最後觀測價格。只有去回程都出現
同一家航空公司，且艙等與旅客人數相同時才配對；再標出航空公司最佳及整體最佳。
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from src.config import ordered_window_keys, window_dates
from src.pipeline.filter_engine import passes_strict_rule, resolve_airline


def _snapshot_identity(flight: dict) -> tuple:
    instance_id = flight.get("flight_instance_id")
    if instance_id is not None:
        return ("instance", instance_id)
    return (
        "legacy", flight.get("flight_date"), flight.get("trip_type"),
        flight.get("origin_airport"), flight.get("dest_airport"),
        flight.get("flight_number"),
    )


def _observed_order(flight: dict) -> tuple:
    """SQLite timestamps are ISO-sortable; id provides a deterministic final fallback."""
    observed = flight.get("last_checked_at") or flight.get("captured_at") or ""
    return (str(observed), int(flight.get("id") or 0))


def _latest_snapshots(flights: list[dict]) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for flight in flights:
        key = (
            _snapshot_identity(flight),
            flight.get("source") or "legacy",
            flight.get("cabin_class") or "ECONOMY",
            int(flight.get("passenger_count") or 1),
        )
        if key not in latest or _observed_order(flight) > _observed_order(latest[key]):
            latest[key] = flight
    return list(latest.values())


def _rank(row: dict) -> tuple:
    return (
        row["price_twd_roundtrip"],
        -row["duration_days"],
        -int(row["inbound_departure_time"].replace(":", "")),
        row["outbound_airline"],
        row["outbound_flight_number"],
        row["inbound_flight_number"],
    )


def _short_date(iso_date: str) -> str:
    y, m, d = iso_date.split("-")
    return f"{int(m)}/{int(d)}"


def _duration_days(outbound_date: str, inbound_date: str) -> int:
    y1, m1, d1 = map(int, outbound_date.split("-"))
    y2, m2, d2 = map(int, inbound_date.split("-"))
    return (_date(y2, m2, d2) - _date(y1, m1, d1)).days + 1


def _build_note(outbound: dict, inbound: dict) -> str:
    reasons = []
    if not outbound.get("passes_strict_rule", True):
        reasons.append("去程不符合嚴格時間規則")
    if not inbound.get("passes_strict_rule", True):
        reasons.append("回程不符合嚴格時間規則")
    return "；".join(reasons)


def _mark_best(rows: list[dict], flexible: bool = True) -> None:
    """共用航空最佳與整體最佳標記，輸入票價必須已是可比較的來回總價。"""
    airline_groups: dict[tuple, list[dict]] = {}
    for row in rows:
        airline_groups.setdefault((
            row["dest_iata"], row["window_group"], row["outbound_airline"],
            row["cabin_class"], row["passenger_count"],
        ), []).append(row)
    for candidates in airline_groups.values():
        eligible = [row for row in candidates if not row["note"]]
        if not flexible:
            eligible = [row for row in eligible if row["inbound_weekday"] == "週六"] or eligible
        if eligible:
            min(eligible, key=_rank)["is_airline_best"] = True

    overall_groups: dict[tuple, list[dict]] = {}
    for row in rows:
        if row["is_airline_best"]:
            overall_groups.setdefault((
                row["dest_iata"], row["window_group"],
                row["cabin_class"], row["passenger_count"],
            ), []).append(row)
    for candidates in overall_groups.values():
        min(candidates, key=_rank)["is_recommended"] = True


def build_schedule_rows(
    flights: list[dict],
    settings: dict,
    window: Optional[str] = None,
    dest: Optional[str] = None,
    passenger_count: Optional[int] = None,
    cabin_class: Optional[str] = None,
) -> list[dict]:
    """flights 須為 annotate_flights() 處理過（含 passes_strict_rule）的清單。

    flights 須包含該地區去程與回程兩段資料（回程的 dest_airport 為出發地機場，
    故不可用 dest_airport 欄位篩選查詢，過濾地區改由本函式的 dest 參數處理）。
    """
    name_zh_map = {d["iata"]: d["name_zh"] for d in settings["destinations"]}
    destinations = [dest] if dest else list(name_zh_map.keys())
    windows = [window] if window and window != "ALL" else ordered_window_keys(settings)

    flights = _latest_snapshots([f for f in flights if not f.get("is_lcc")])
    if passenger_count is not None:
        flights = [f for f in flights if int(f.get("passenger_count") or 1) == passenger_count]
    if cabin_class:
        flights = [f for f in flights if (f.get("cabin_class") or "ECONOMY") == cabin_class]

    rows: list[dict] = []
    for w in windows:
        wcfg = settings["windows"].get(w)
        if not wcfg:
            continue
        outbound_date, inbound_dates = window_dates(wcfg)
        for dest in destinations:
            outbound_flights = [
                f for f in flights
                if f["dest_airport"] == dest
                and f["trip_type"] == "OUTBOUND"
                and f["flight_date"] == outbound_date
            ]
            outbound_airlines = {f["airline_name"] for f in outbound_flights if f.get("airline_name")}
            if not outbound_airlines:
                continue

            for inbound_date in inbound_dates:
                inbound_flights = [
                    f for f in flights
                    if f["origin_airport"] == dest
                    and f["trip_type"] == "INBOUND"
                    and f["flight_date"] == inbound_date
                ]
                inbound_airlines = {f["airline_name"] for f in inbound_flights if f.get("airline_name")}
                common_airlines = outbound_airlines & inbound_airlines

                for airline in common_airlines:
                    airline_outbounds = [f for f in outbound_flights if f["airline_name"] == airline]
                    airline_inbounds = [f for f in inbound_flights if f["airline_name"] == airline]
                    outbound_contexts = {
                        ((f.get("cabin_class") or "ECONOMY"), int(f.get("passenger_count") or 1))
                        for f in airline_outbounds
                    }
                    inbound_contexts = {
                        ((f.get("cabin_class") or "ECONOMY"), int(f.get("passenger_count") or 1))
                        for f in airline_inbounds
                    }
                    for fare_cabin, fare_passengers in outbound_contexts & inbound_contexts:
                        ob = min(
                            (f for f in airline_outbounds
                             if (f.get("cabin_class") or "ECONOMY") == fare_cabin
                             and int(f.get("passenger_count") or 1) == fare_passengers),
                            key=lambda f: f["price_twd"],
                        )
                        ib = min(
                            (f for f in airline_inbounds
                             if (f.get("cabin_class") or "ECONOMY") == fare_cabin
                             and int(f.get("passenger_count") or 1) == fare_passengers),
                            key=lambda f: f["price_twd"],
                        )
                        rows.append({
                            "region": name_zh_map[dest],
                            "dest_iata": dest,
                            "window": w,
                            "window_group": wcfg.get("group", w),
                            "duration_days": _duration_days(outbound_date, inbound_date),
                            "outbound_airline": airline,
                            "outbound_flight_number": ob["flight_number"],
                            "outbound_datetime": f"{_short_date(outbound_date)} {ob['departure_time']}",
                            "outbound_source": ob.get("source") or "legacy",
                            "inbound_airline": airline,
                            "inbound_flight_number": ib["flight_number"],
                            "inbound_datetime": f"{_short_date(inbound_date)} {ib['departure_time']}",
                            "inbound_source": ib.get("source") or "legacy",
                            "passenger_count": fare_passengers,
                            "cabin_class": fare_cabin,
                            "price_twd_roundtrip": ob["price_twd"] + ib["price_twd"],
                            "inbound_weekday": (
                                "週六" if _date.fromisoformat(inbound_date).weekday() == 5 else "週日"
                            ),
                            "inbound_departure_time": ib["departure_time"],
                            "is_airline_best": False,
                            "is_recommended": False,
                            "note": _build_note(ob, ib),
                        })

    selection = settings.get("strict_time_rules", {}).get("return_selection", {})
    flexible = selection.get("flexible", True)
    _mark_best(rows, flexible=flexible)

    region_order = {d["iata"]: i for i, d in enumerate(settings["destinations"])}
    window_order = {w: i for i, w in enumerate(ordered_window_keys(settings))}
    rows.sort(key=lambda r: (region_order[r["dest_iata"]], window_order[r["window"]],
                             not r["is_recommended"], not r["is_airline_best"],
                             r["price_twd_roundtrip"]))
    return rows


def build_roundtrip_schedule_rows(
    snapshots: list[dict],
    settings: dict,
    window: Optional[str] = None,
    dest: Optional[str] = None,
    passenger_count: Optional[int] = None,
    cabin_class: Optional[str] = None,
) -> list[dict]:
    """將來源明確提供的完整來回總價轉成 GUI 行程列，不做單程價格相加。"""
    destination_names = {row["iata"]: row["name_zh"] for row in settings["destinations"]}
    latest: dict[tuple, dict] = {}
    for snapshot in snapshots:
        key = (
            snapshot["window_key"], snapshot["outbound_flight_instance_id"],
            snapshot["inbound_flight_instance_id"], snapshot.get("source") or "google_flights",
            snapshot.get("cabin_class") or "ECONOMY",
            int(snapshot.get("passenger_count") or 1),
        )
        if key not in latest or _observed_order(snapshot) > _observed_order(latest[key]):
            latest[key] = snapshot

    rows: list[dict] = []
    for fare in latest.values():
        window_key = fare["window_key"]
        if window and window != "ALL" and window_key != window:
            continue
        if window_key not in settings["windows"]:
            continue
        if dest and fare["dest_airport"] != dest:
            continue
        fare_passengers = int(fare.get("passenger_count") or 1)
        fare_cabin = fare.get("cabin_class") or "ECONOMY"
        if passenger_count is not None and fare_passengers != passenger_count:
            continue
        if cabin_class and fare_cabin != cabin_class:
            continue

        configured_outbound, configured_inbounds = window_dates(settings["windows"][window_key])
        if fare["outbound_date"] != configured_outbound or fare["inbound_date"] not in configured_inbounds:
            continue
        outbound_info = resolve_airline(fare.get("outbound_airline_code"), settings)
        inbound_info = resolve_airline(fare.get("inbound_airline_code"), settings)
        if outbound_info["is_lcc"] or inbound_info["is_lcc"]:
            continue
        if outbound_info["name_zh"] != inbound_info["name_zh"]:
            continue
        outbound_ok = passes_strict_rule(
            fare["outbound_date"], "OUTBOUND", fare["outbound_departure_time"], settings,
        )
        inbound_ok = passes_strict_rule(
            fare["inbound_date"], "INBOUND", fare["inbound_departure_time"], settings,
        )
        note_parts = []
        if not outbound_ok:
            note_parts.append("去程不符合嚴格時間規則")
        if not inbound_ok:
            note_parts.append("回程不符合嚴格時間規則")
        rows.append({
            "region": destination_names.get(fare["dest_airport"], fare["dest_airport"]),
            "dest_iata": fare["dest_airport"],
            "window": window_key,
            "window_group": settings["windows"][window_key].get("group", window_key),
            "duration_days": _duration_days(fare["outbound_date"], fare["inbound_date"]),
            "outbound_airline": outbound_info["name_zh"],
            "outbound_flight_number": fare["outbound_flight_number"],
            "outbound_datetime": (
                f"{_short_date(fare['outbound_date'])} {fare['outbound_departure_time']}"
            ),
            "outbound_source": fare.get("source") or "google_flights",
            "inbound_airline": inbound_info["name_zh"],
            "inbound_flight_number": fare["inbound_flight_number"],
            "inbound_datetime": (
                f"{_short_date(fare['inbound_date'])} {fare['inbound_departure_time']}"
            ),
            "inbound_source": fare.get("source") or "google_flights",
            "passenger_count": fare_passengers,
            "cabin_class": fare_cabin,
            "price_twd_roundtrip": int(fare["price_twd"]),
            "inbound_weekday": (
                "週六" if _date.fromisoformat(fare["inbound_date"]).weekday() == 5 else "週日"
            ),
            "inbound_departure_time": fare["inbound_departure_time"],
            "is_airline_best": False,
            "is_recommended": False,
            "note": "；".join(note_parts),
        })

    flexible = settings.get("strict_time_rules", {}).get(
        "return_selection", {},
    ).get("flexible", True)
    _mark_best(rows, flexible=flexible)

    region_order = {row["iata"]: index for index, row in enumerate(settings["destinations"])}
    window_order = {key: index for index, key in enumerate(ordered_window_keys(settings))}
    rows.sort(key=lambda row: (
        region_order.get(row["dest_iata"], 999), window_order.get(row["window"], 999),
        not row["is_recommended"], not row["is_airline_best"], row["price_twd_roundtrip"],
    ))
    return rows
