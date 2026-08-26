"""Skyscanner Playwright 爬蟲。

Skyscanner 的 DOM 會隨地區與版本變動；解析不到單一結果時略過該卡片，
頁面或瀏覽器錯誤則透過 log 回報並回傳空清單。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Optional

from src.config import load_settings
from src.pipeline.normalizer import RawFlight
from src.scraper.base import FlightScraper

SKYSCANNER_URL = "https://www.skyscanner.com.tw/transport/flights"
CARD_SELECTORS = (
    '[data-testid="itinerary-card"]',
    '[data-testid="result-card"]',
    'div[class*="FlightsTicket_container"]',
)


class SkyscannerCrawler(FlightScraper):
    source_name = "skyscanner"

    def __init__(self, headless: Optional[bool] = None, timeout_ms: Optional[int] = None,
                 passenger_count: int = 1, direct_only: bool = True):
        settings = load_settings().get("scraper", {})
        self.headless = settings.get("headless", True) if headless is None else headless
        self.timeout_ms = settings.get("timeout_ms", 30000) if timeout_ms is None else timeout_ms
        self.disabled_reason: Optional[str] = None
        self.passenger_count = passenger_count
        self.direct_only = direct_only

    def fetch(
        self,
        origin: str,
        dest: str,
        date: str,
        trip_type: str,
        log: Optional[Callable[[str], None]] = None,
    ) -> list[RawFlight]:
        log = log or (lambda _: None)
        if self.disabled_reason:
            return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log(f"playwright 未安裝，略過 {origin}->{dest} {date}")
            return []

        url = self._build_search_url(origin, dest, date)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                try:
                    page = browser.new_page(locale="zh-TW")
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    body_text = page.locator("body").inner_text()
                    if self._is_challenge_page(page.url, body_text):
                        self.disabled_reason = "Skyscanner CAPTCHA 阻擋自動瀏覽器"
                        log(f"{self.disabled_reason}；本次 Pipeline 將停用此來源並繼續其他來源")
                        return []
                    page.wait_for_timeout(2500)
                    cards = []
                    for selector in CARD_SELECTORS:
                        cards = page.query_selector_all(selector)
                        if cards:
                            break
                    if not cards:
                        log(f"{origin}->{dest} {date} 找不到結果卡片，可能尚未開放或頁面結構已變更")
                        return []
                    results = []
                    for card in cards:
                        parsed = self._parse_card(card.inner_text(), origin, dest, date, trip_type)
                        if parsed:
                            results.append(parsed)
                    return results
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            log(f"{origin}->{dest} {date} 抓取失敗：{exc}")
            return []

    @staticmethod
    def _is_challenge_page(url: str, body_text: str) -> bool:
        normalized = body_text.lower()
        return "captcha" in url.lower() or "person or a robot" in normalized

    @staticmethod
    def _build_search_url(origin: str, dest: str, date: str) -> str:
        compact_date = datetime.strptime(date, "%Y-%m-%d").strftime("%y%m%d")
        return (
            f"{SKYSCANNER_URL}/{origin.lower()}/{dest.lower()}/{compact_date}/"
            "?adultsv2=1&cabinclass=economy&currency=TWD&locale=zh-TW&market=TW"
        )

    @staticmethod
    def _parse_card(text: str, origin: str, dest: str, date: str, trip_type: str) -> Optional[RawFlight]:
        times = re.findall(r"(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)", text)
        price_match = re.search(r"(?:NT\$|TWD|\$)\s*([\d,]+)", text, re.IGNORECASE)
        if len(times) < 2 or not price_match:
            return None
        flight_match = re.search(r"\b([A-Z0-9]{2})\s?(\d{2,4})\b", text)
        flight_number = "".join(flight_match.groups()) if flight_match else "UNKNOWN"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        airline = next(
            (line for line in lines if "航空" in line or "Airlines" in line or "Airways" in line),
            None,
        )
        return RawFlight(
            flight_date=date,
            trip_type=trip_type,
            origin_airport=origin,
            dest_airport=dest,
            flight_number=flight_number,
            departure_time=times[0],
            arrival_time=times[1],
            original_currency="TWD",
            original_price=float(price_match.group(1).replace(",", "")),
            airline_code=airline,
            source="skyscanner",
        )
