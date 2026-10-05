"""Mock 航班資料產生器（--mock 模式資料源）。

涵蓋 SPEC 兩個時段 x 6 大航點的去程/回程航班，資料結構與真實 Scraper 輸出一致，
可離線驗證 pipeline / filter_engine / DB / Excel 匯出，無需網路連線。
"""

from __future__ import annotations

from src.pipeline.normalizer import RawFlight

# (origin, dest, airline_code, flight_number, dep, arr, currency, price)
_WINDOW_1_OUTBOUND = [
    ("TPE", "NGO", "CI", "CI150", "08:30", "12:10", "TWD", 8200),
    ("TPE", "NGO", "JX", "JX838", "15:30", "19:10", "JPY", 32000),  # 超過 15:00 -> 不通過
    ("TPE", "KIX", "BR", "BR108", "07:55", "11:35", "TWD", 7600),
    ("TPE", "KIX", "IT", "IT202", "13:40", "17:20", "TWD", 6900),
    ("TPE", "SDJ", "JL", "JL806", "09:15", "14:05", "JPY", 41000),
    ("TSA", "SDJ", "CI", "CI9822", "14:50", "19:35", "TWD", 12800),
    ("TPE", "CTS", "CI", "CI126", "08:05", "13:00", "TWD", 11500),
    ("TPE", "CTS", "JX", "JX822", "16:20", "21:15", "JPY", 38000),  # 超過 15:00 -> 不通過
    ("TPE", "HIJ", "BR", "BR186", "10:10", "14:00", "TWD", 9800),
    ("TSA", "PUS", "TW", "TW296", "09:40", "12:55", "TWD", 6300),
    ("TPE", "PUS", "BX", "BX797", "14:20", "17:35", "KRW", 210000),
]

_WINDOW_1_INBOUND_SAT = [
    ("NGO", "TPE", "CI", "CI151", "13:20", "15:50", "TWD", 8200),
    ("KIX", "TPE", "BR", "BR109", "12:45", "15:05", "TWD", 7600),
    ("SDJ", "TSA", "CI", "CI9823", "20:50", "23:35", "TWD", 12800),  # 週六 20:50 -> 不通過
    ("CTS", "TPE", "CI", "CI127", "14:15", "17:50", "TWD", 11500),
    ("HIJ", "TPE", "BR", "BR187", "15:20", "18:10", "TWD", 9800),
    ("PUS", "TSA", "TW", "TW297", "13:50", "15:15", "TWD", 6300),
]

_WINDOW_1_INBOUND_SUN = [
    ("NGO", "TPE", "JX", "JX839", "20:15", "22:45", "JPY", 32000),  # 週日 20:15 -> 不通過
    ("KIX", "TPE", "IT", "IT203", "18:30", "21:00", "TWD", 6900),  # 週日 18:30 -> 不通過
    ("SDJ", "TPE", "JL", "JL807", "10:40", "14:50", "JPY", 41000),
    ("CTS", "TPE", "JX", "JX823", "22:05", "01:45", "JPY", 38000),  # 週日 22:05 -> 不通過
    ("HIJ", "TSA", "CI", "CI9899", "11:05", "14:40", "TWD", 9800),
    ("PUS", "TPE", "BX", "BX798", "12:10", "15:30", "KRW", 210000),
]

_WINDOW_2_OUTBOUND = [
    ("TPE", "NGO", "CI", "CI150", "08:30", "12:10", "TWD", 8600),
    ("TSA", "PUS", "TW", "TW296", "09:40", "12:55", "TWD", 6500),
]

_WINDOW_2_INBOUND_SAT = [
    ("NGO", "TPE", "CI", "CI151", "13:20", "15:50", "TWD", 8600),
    ("PUS", "TSA", "TW", "TW297", "13:50", "15:15", "TWD", 6500),
]

_WINDOW_2_INBOUND_SUN = [
    ("NGO", "TPE", "JX", "JX839", "12:15", "14:45", "JPY", 33000),
    ("PUS", "TPE", "BX", "BX798", "11:40", "15:05", "KRW", 215000),
]


def _build(rows, flight_date: str, trip_type: str) -> list[RawFlight]:
    flights = []
    for origin, dest, airline, flight_no, dep, arr, currency, price in rows:
        flights.append(
            RawFlight(
                flight_date=flight_date,
                trip_type=trip_type,
                origin_airport=origin,
                dest_airport=dest,
                flight_number=flight_no,
                departure_time=dep,
                arrival_time=arr,
                original_currency=currency,
                original_price=price,
                airline_code=airline,
                stops=0,
                source="mock",
            )
        )
    return flights


def generate_mock_flights() -> list[RawFlight]:
    """回傳涵蓋兩個時段 x 6 航點的完整 mock 航班清單。"""
    flights: list[RawFlight] = []
    flights += _build(_WINDOW_1_OUTBOUND, "2027-07-11", "OUTBOUND")
    flights += _build(_WINDOW_1_INBOUND_SAT, "2027-07-17", "INBOUND")
    flights += _build(_WINDOW_1_INBOUND_SUN, "2027-07-18", "INBOUND")
    flights += _build(_WINDOW_2_OUTBOUND, "2027-08-15", "OUTBOUND")
    flights += _build(_WINDOW_2_INBOUND_SAT, "2027-08-21", "INBOUND")
    flights += _build(_WINDOW_2_INBOUND_SUN, "2027-08-22", "INBOUND")
    return flights


_ROUNDTRIP_PRICES = {
    ("2027-07-11", "CI150", "2027-07-17", "CI151"): 24600,
    ("2027-07-11", "BR108", "2027-07-17", "BR109"): 23100,
    ("2027-07-11", "CI126", "2027-07-17", "CI127"): 31800,
    ("2027-07-11", "BR186", "2027-07-17", "BR187"): 26900,
    ("2027-07-11", "JL806", "2027-07-18", "JL807"): 28700,
    ("2027-08-15", "CI150", "2027-08-21", "CI151"): 27800,
}


def mock_roundtrip_price(
    outbound_date: str, outbound_number: str,
    inbound_date: str, inbound_number: str,
) -> int | None:
    """Debug 專用的明確來回總價 fixture；不得由兩張單程價格推算。"""
    return _ROUNDTRIP_PRICES.get((
        outbound_date, outbound_number, inbound_date, inbound_number,
    ))
