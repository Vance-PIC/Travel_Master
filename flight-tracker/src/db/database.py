"""SQLite 連線管理與 Schema 初始化（stdlib sqlite3，無額外 ORM 依賴）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from src.db.models import FlightInstance, FlightSnapshot, RoundTripSnapshot

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS flight_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_date TEXT NOT NULL, trip_type TEXT NOT NULL,
    origin_airport TEXT NOT NULL, dest_airport TEXT NOT NULL,
    airline_code TEXT, operating_airline TEXT,
    flight_number TEXT NOT NULL CHECK(flight_number <> 'UNKNOWN'),
    departure_time TEXT NOT NULL, arrival_time TEXT NOT NULL,
    duration_minutes INTEGER, stops INTEGER, aircraft_type TEXT,
    discovery_source TEXT NOT NULL DEFAULT 'google_flights', source_url TEXT,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(flight_date, flight_number, origin_airport, dest_airport)
);
CREATE TABLE IF NOT EXISTS flight_price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_instance_id INTEGER REFERENCES flight_instances(id),
    flight_date TEXT NOT NULL,
    trip_type TEXT NOT NULL,
    origin_airport TEXT NOT NULL,
    dest_airport TEXT NOT NULL,
    airline_code TEXT,
    flight_number TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    arrival_time TEXT NOT NULL,
    price_twd INTEGER,
    original_currency TEXT,
    original_price REAL,
    snapshot_hash TEXT UNIQUE,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ,source TEXT DEFAULT 'legacy', cabin_class TEXT DEFAULT 'ECONOMY', passenger_count INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS roundtrip_price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbound_flight_instance_id INTEGER NOT NULL REFERENCES flight_instances(id),
    inbound_flight_instance_id INTEGER NOT NULL REFERENCES flight_instances(id),
    window_key TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'google_flights',
    cabin_class TEXT NOT NULL DEFAULT 'ECONOMY',
    passenger_count INTEGER NOT NULL DEFAULT 1,
    price_twd INTEGER NOT NULL,
    original_currency TEXT NOT NULL DEFAULT 'TWD',
    original_price REAL,
    source_url TEXT,
    snapshot_hash TEXT UNIQUE NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_last_checked_at_column(conn: sqlite3.Connection) -> None:
    """對舊版（無 last_checked_at 欄位）資料庫做欄位遷移，避免既有 DB 檔案炸開。"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(flight_price_snapshots)")}
    if "last_checked_at" not in columns:
        # SQLite only permits constant defaults when adding a column to an
        # existing table.  Keep the dynamic default in SCHEMA_SQL for fresh
        # databases, then populate migrated rows explicitly.
        conn.execute(
            "ALTER TABLE flight_price_snapshots "
            "ADD COLUMN last_checked_at TIMESTAMP"
        )
        conn.execute(
            "UPDATE flight_price_snapshots "
            "SET last_checked_at = COALESCE(captured_at, CURRENT_TIMESTAMP) "
            "WHERE last_checked_at IS NULL"
        )
        conn.commit()

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(flight_price_snapshots)")}
    additions = {
        "flight_instance_id": "INTEGER REFERENCES flight_instances(id)",
        "source": "TEXT DEFAULT 'legacy'",
        "cabin_class": "TEXT DEFAULT 'ECONOMY'",
        "passenger_count": "INTEGER DEFAULT 1",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE flight_price_snapshots ADD COLUMN {name} {definition}")
    conn.commit()


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _ensure_last_checked_at_column(conn)
    finally:
        conn.close()


def upsert_flight_instance(conn: sqlite3.Connection, flight: FlightInstance) -> tuple[int, bool]:
    if not flight.flight_number or flight.flight_number == "UNKNOWN":
        raise ValueError("flight_number 必須是已確認的真實航班號")
    existing = conn.execute(
        "SELECT id FROM flight_instances WHERE flight_date=? AND flight_number=? "
        "AND origin_airport=? AND dest_airport=?",
        (flight.flight_date, flight.flight_number, flight.origin_airport, flight.dest_airport),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE flight_instances SET departure_time=?, arrival_time=?, airline_code=?, "
            "duration_minutes=?, stops=?, aircraft_type=?, source_url=?, last_verified_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (flight.departure_time, flight.arrival_time, flight.airline_code,
             flight.duration_minutes, flight.stops, flight.aircraft_type, flight.source_url, existing["id"]),
        )
        conn.commit()
        return int(existing["id"]), False
    cursor = conn.execute(
        "INSERT INTO flight_instances (flight_date,trip_type,origin_airport,dest_airport,airline_code,"
        "operating_airline,flight_number,departure_time,arrival_time,duration_minutes,stops,aircraft_type,"
        "discovery_source,source_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (flight.flight_date, flight.trip_type, flight.origin_airport, flight.dest_airport,
         flight.airline_code, flight.operating_airline, flight.flight_number, flight.departure_time,
         flight.arrival_time, flight.duration_minutes, flight.stops, flight.aircraft_type,
         flight.discovery_source, flight.source_url),
    )
    conn.commit()
    return int(cursor.lastrowid), True


def fetch_flight_instances(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT fi.*, EXISTS(SELECT 1 FROM flight_price_snapshots ps "
        "WHERE ps.flight_instance_id=fi.id) AS has_price, "
        "EXISTS(SELECT 1 FROM roundtrip_price_snapshots rt "
        "WHERE rt.outbound_flight_instance_id=fi.id OR rt.inbound_flight_instance_id=fi.id) "
        "AS has_roundtrip_price FROM flight_instances fi "
        "ORDER BY flight_date, origin_airport, departure_time"
    ).fetchall()]


def insert_snapshot(conn: sqlite3.Connection, snapshot: FlightSnapshot) -> bool:
    """依 snapshot_hash 去重。已存在則只更新 last_checked_at（代表這次有查到同樣的價格），
    回傳 True 代表實際新增一筆全新快照。
    """
    existing = conn.execute(
        "SELECT id FROM flight_price_snapshots WHERE snapshot_hash = ?",
        (snapshot.snapshot_hash,),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE flight_price_snapshots SET last_checked_at = CURRENT_TIMESTAMP "
            "WHERE snapshot_hash = ?",
            (snapshot.snapshot_hash,),
        )
        conn.commit()
        return False

    conn.execute(
        """
        INSERT INTO flight_price_snapshots
            (flight_instance_id, source, cabin_class, passenger_count,
             flight_date, trip_type, origin_airport, dest_airport, airline_code,
             flight_number, departure_time, arrival_time, price_twd,
             original_currency, original_price, snapshot_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.flight_instance_id, snapshot.source, snapshot.cabin_class, snapshot.passenger_count,
            snapshot.flight_date,
            snapshot.trip_type,
            snapshot.origin_airport,
            snapshot.dest_airport,
            snapshot.airline_code,
            snapshot.flight_number,
            snapshot.departure_time,
            snapshot.arrival_time,
            snapshot.price_twd,
            snapshot.original_currency,
            snapshot.original_price,
            snapshot.snapshot_hash,
        ),
    )
    conn.commit()
    return True


def insert_snapshots(conn: sqlite3.Connection, snapshots: Iterable[FlightSnapshot]) -> tuple[int, int]:
    """批次寫入，回傳 (新增筆數, 重複略過筆數)。"""
    inserted = 0
    skipped = 0
    for snap in snapshots:
        if insert_snapshot(conn, snap):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def insert_roundtrip_snapshot(conn: sqlite3.Connection, snapshot: RoundTripSnapshot) -> bool:
    existing = conn.execute(
        "SELECT id FROM roundtrip_price_snapshots WHERE snapshot_hash=?",
        (snapshot.snapshot_hash,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE roundtrip_price_snapshots SET last_checked_at=CURRENT_TIMESTAMP "
            "WHERE snapshot_hash=?",
            (snapshot.snapshot_hash,),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO roundtrip_price_snapshots "
        "(outbound_flight_instance_id,inbound_flight_instance_id,window_key,source,"
        "cabin_class,passenger_count,price_twd,original_currency,original_price,source_url,snapshot_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            snapshot.outbound_flight_instance_id, snapshot.inbound_flight_instance_id,
            snapshot.window_key, snapshot.source, snapshot.cabin_class,
            snapshot.passenger_count, snapshot.price_twd, snapshot.original_currency,
            snapshot.original_price, snapshot.source_url, snapshot.snapshot_hash,
        ),
    )
    conn.commit()
    return True


def insert_roundtrip_snapshots(
    conn: sqlite3.Connection, snapshots: Iterable[RoundTripSnapshot],
) -> tuple[int, int]:
    inserted = skipped = 0
    for snapshot in snapshots:
        if insert_roundtrip_snapshot(conn, snapshot):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def fetch_roundtrip_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT rt.*, 
               ob.flight_date AS outbound_date, ob.origin_airport AS origin_airport,
               ob.dest_airport AS dest_airport, ob.airline_code AS outbound_airline_code,
               ob.flight_number AS outbound_flight_number,
               ob.departure_time AS outbound_departure_time,
               ob.arrival_time AS outbound_arrival_time,
               ib.flight_date AS inbound_date, ib.airline_code AS inbound_airline_code,
               ib.flight_number AS inbound_flight_number,
               ib.departure_time AS inbound_departure_time,
               ib.arrival_time AS inbound_arrival_time
        FROM roundtrip_price_snapshots rt
        JOIN flight_instances ob ON ob.id=rt.outbound_flight_instance_id
        JOIN flight_instances ib ON ib.id=rt.inbound_flight_instance_id
        ORDER BY rt.last_checked_at DESC, rt.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def clear_snapshots(conn: sqlite3.Connection) -> int:
    """清空 flight_price_snapshots 全部資料，回傳刪除筆數。"""
    cursor = conn.execute("DELETE FROM flight_price_snapshots")
    conn.commit()
    return cursor.rowcount


def clear_all_price_snapshots(conn: sqlite3.Connection) -> dict[str, int]:
    """清除單程初估與正式來回票價，不刪除已確認航班實例。"""
    roundtrip = conn.execute("DELETE FROM roundtrip_price_snapshots").rowcount
    single_leg = conn.execute("DELETE FROM flight_price_snapshots").rowcount
    conn.commit()
    return {"single_leg": single_leg, "roundtrip": roundtrip,
            "total": single_leg + roundtrip}


def clear_all_tracking_data(conn: sqlite3.Connection) -> dict[str, int]:
    """清除所有追蹤資料，包含價格快照與已確認航班實例。"""
    roundtrip = conn.execute("DELETE FROM roundtrip_price_snapshots").rowcount
    single_leg = conn.execute("DELETE FROM flight_price_snapshots").rowcount
    flight_instances = conn.execute("DELETE FROM flight_instances").rowcount
    conn.commit()
    return {
        "single_leg": single_leg,
        "roundtrip": roundtrip,
        "flight_instances": flight_instances,
        "total": single_leg + roundtrip + flight_instances,
    }


def count_snapshots(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM flight_price_snapshots").fetchone()
    return int(row["cnt"])


def count_price_snapshots(conn: sqlite3.Connection) -> dict[str, int]:
    single_leg = count_snapshots(conn)
    row = conn.execute("SELECT COUNT(*) AS cnt FROM roundtrip_price_snapshots").fetchone()
    roundtrip = int(row["cnt"])
    return {"single_leg": single_leg, "roundtrip": roundtrip,
            "total": single_leg + roundtrip}


def fetch_all_snapshots(conn: sqlite3.Connection) -> list[FlightSnapshot]:
    rows = conn.execute(
        "SELECT * FROM flight_price_snapshots ORDER BY captured_at DESC, id DESC"
    ).fetchall()
    return [FlightSnapshot.from_row(row) for row in rows]


def fetch_snapshots(
    conn: sqlite3.Connection,
    dest: Optional[str] = None,
    trip_type: Optional[str] = None,
) -> list[FlightSnapshot]:
    query = "SELECT * FROM flight_price_snapshots WHERE 1=1"
    params: list = []
    if dest:
        query += " AND dest_airport = ?"
        params.append(dest)
    if trip_type:
        query += " AND trip_type = ?"
        params.append(trip_type)
    query += " ORDER BY price_twd ASC"
    rows = conn.execute(query, params).fetchall()
    return [FlightSnapshot.from_row(row) for row in rows]
