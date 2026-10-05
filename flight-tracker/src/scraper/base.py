"""Scraper 抽象介面。

任何新資料來源（Google Flights、Skyscanner...）皆須繼承 FlightScraper，
使 --crawl 模式可透過設定切換來源而不需更動 pipeline/API 層。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from src.pipeline.normalizer import RawFlight


@dataclass
class RoundTripQuote:
    outbound_flight_number: str
    inbound_flight_number: str
    price_twd: int
    original_currency: str = "TWD"
    original_price: float = 0.0
    source: str = "google_flights"
    source_url: Optional[str] = None


class FlightScraper(ABC):
    """單一資料來源的爬蟲介面。"""

    source_name: str = "base"

    def query_skip_reason(self, flight_date: str) -> Optional[str]:
        """回傳本地預檢的跳過原因；None 代表可呼叫 fetch。"""
        return None

    @abstractmethod
    def fetch(
        self,
        origin: str,
        dest: str,
        date: str,
        trip_type: str,
        log: Optional[Callable[[str], None]] = None,
    ) -> list[RawFlight]:
        """查詢單一航段（origin->dest，指定日期與去回程類型），回傳原始航班清單。

        實作必須自行處理逾時與例外，失敗時回傳空清單並透過 log 回報警告，
        不得讓例外往外傳導致整條 pipeline 中斷。
        """
        raise NotImplementedError
