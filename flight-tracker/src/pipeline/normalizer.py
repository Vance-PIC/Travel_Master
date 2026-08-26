"""資料清洗：時間/日期格式正規化與幣別換算為 TWD。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.config import load_settings


@dataclass
class RawFlight:
    """Scraper 回傳的原始航班資料（尚未換算幣別/正規化格式）。"""

    flight_date: str
    trip_type: str
    origin_airport: str
    dest_airport: str
    flight_number: str
    departure_time: str
    arrival_time: str
    original_currency: str
    original_price: float
    airline_code: Optional[str] = None
    duration_minutes: Optional[int] = None
    stops: Optional[int] = None
    aircraft_type: Optional[str] = None
    source_url: Optional[str] = None
    source: str = "unknown"


def normalize_time(value: str) -> str:
    """統一為 HH:mm，容忍 'H:mm'、'HH:mm:ss' 等輸入。"""
    value = value.strip()
    parts = value.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return f"{hour:02d}:{minute:02d}"


def convert_to_twd(currency: str, amount: float) -> int:
    rates = load_settings()["exchange_rates"]
    rate = rates.get(currency.upper(), 1.0)
    return round(amount * rate)


def normalize_flight(raw: RawFlight) -> dict:
    """回傳正規化後、可直接建立 FlightSnapshot 的欄位 dict。"""
    return {
        "flight_date": raw.flight_date,
        "trip_type": raw.trip_type,
        "origin_airport": raw.origin_airport,
        "dest_airport": raw.dest_airport,
        "airline_code": raw.airline_code,
        "flight_number": raw.flight_number,
        "departure_time": normalize_time(raw.departure_time),
        "arrival_time": normalize_time(raw.arrival_time),
        "original_currency": raw.original_currency.upper(),
        "original_price": raw.original_price,
        "price_twd": convert_to_twd(raw.original_currency, raw.original_price),
        "duration_minutes": raw.duration_minutes,
        "stops": raw.stops,
        "aircraft_type": raw.aircraft_type,
        "source_url": raw.source_url,
        "source": raw.source,
    }
