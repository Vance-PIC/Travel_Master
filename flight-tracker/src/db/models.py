"""flight_price_snapshots 資料模型與雜湊/去重輔助函式。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlightInstance:
    flight_date: str
    trip_type: str
    origin_airport: str
    dest_airport: str
    flight_number: str
    departure_time: str
    arrival_time: str
    airline_code: Optional[str] = None
    operating_airline: Optional[str] = None
    duration_minutes: Optional[int] = None
    stops: Optional[int] = None
    aircraft_type: Optional[str] = None
    discovery_source: str = "google_flights"
    source_url: Optional[str] = None
    id: Optional[int] = None
    discovered_at: Optional[str] = None
    last_verified_at: Optional[str] = None


@dataclass
class FlightSnapshot:
    """對應 SPEC 第 5 節 flight_price_snapshots 資料表。"""

    flight_date: str
    trip_type: str  # OUTBOUND | INBOUND
    origin_airport: str
    dest_airport: str
    flight_number: str
    departure_time: str  # HH:mm
    arrival_time: str  # HH:mm
    price_twd: int
    airline_code: Optional[str] = None
    original_currency: str = "TWD"
    original_price: float = 0.0
    id: Optional[int] = None
    captured_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    flight_instance_id: Optional[int] = None
    source: str = "legacy"
    cabin_class: str = "ECONOMY"
    passenger_count: int = 1
    snapshot_hash: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.snapshot_hash = self.compute_hash(
            self.flight_date, self.flight_number, self.price_twd
        )
        if self.flight_instance_id:
            raw = f"{self.flight_instance_id}{self.source}{self.cabin_class}{self.passenger_count}{self.price_twd}"
            self.snapshot_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_hash(flight_date: str, flight_number: str, price_twd: int) -> str:
        raw = f"{flight_date}{flight_number}{price_twd}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "flight_instance_id": self.flight_instance_id,
            "source": self.source,
            "cabin_class": self.cabin_class,
            "passenger_count": self.passenger_count,
            "flight_date": self.flight_date,
            "trip_type": self.trip_type,
            "origin_airport": self.origin_airport,
            "dest_airport": self.dest_airport,
            "airline_code": self.airline_code,
            "flight_number": self.flight_number,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "price_twd": self.price_twd,
            "original_currency": self.original_currency,
            "original_price": self.original_price,
            "snapshot_hash": self.snapshot_hash,
            "captured_at": self.captured_at,
            "last_checked_at": self.last_checked_at,
        }

    @classmethod
    def from_row(cls, row) -> "FlightSnapshot":
        columns = set(row.keys())
        snap = cls(
            flight_date=row["flight_date"],
            trip_type=row["trip_type"],
            origin_airport=row["origin_airport"],
            dest_airport=row["dest_airport"],
            flight_number=row["flight_number"],
            departure_time=row["departure_time"],
            arrival_time=row["arrival_time"],
            price_twd=row["price_twd"],
            airline_code=row["airline_code"],
            original_currency=row["original_currency"],
            original_price=row["original_price"],
            flight_instance_id=row["flight_instance_id"] if "flight_instance_id" in columns else None,
            source=(row["source"] or "legacy") if "source" in columns else "legacy",
            cabin_class=(row["cabin_class"] or "ECONOMY") if "cabin_class" in columns else "ECONOMY",
            passenger_count=(row["passenger_count"] or 1) if "passenger_count" in columns else 1,
        )
        snap.id = row["id"]
        snap.captured_at = row["captured_at"]
        snap.last_checked_at = row["last_checked_at"]
        snap.snapshot_hash = row["snapshot_hash"]
        return snap


@dataclass
class RoundTripSnapshot:
    """Google Flights 或其他來源觀測到的完整來回行程總價。"""

    outbound_flight_instance_id: int
    inbound_flight_instance_id: int
    window_key: str
    price_twd: int
    source: str = "google_flights"
    cabin_class: str = "ECONOMY"
    passenger_count: int = 1
    original_currency: str = "TWD"
    original_price: float = 0.0
    source_url: Optional[str] = None
    id: Optional[int] = None
    captured_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    snapshot_hash: str = field(init=False, default="")

    def __post_init__(self) -> None:
        raw = (
            f"{self.window_key}{self.outbound_flight_instance_id}"
            f"{self.inbound_flight_instance_id}{self.source}{self.cabin_class}"
            f"{self.passenger_count}{self.price_twd}"
        )
        self.snapshot_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "outbound_flight_instance_id": self.outbound_flight_instance_id,
            "inbound_flight_instance_id": self.inbound_flight_instance_id,
            "window_key": self.window_key,
            "source": self.source,
            "cabin_class": self.cabin_class,
            "passenger_count": self.passenger_count,
            "price_twd": self.price_twd,
            "original_currency": self.original_currency,
            "original_price": self.original_price,
            "source_url": self.source_url,
            "snapshot_hash": self.snapshot_hash,
            "captured_at": self.captured_at,
            "last_checked_at": self.last_checked_at,
        }
