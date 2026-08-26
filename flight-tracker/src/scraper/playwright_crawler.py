"""Google Flights 專用 Playwright 爬蟲實作。

Google Flights 為動態 SPA，無穩定官方 API，故採「開啟搜尋頁 -> 等待結果卡片渲染 ->
解析 DOM」策略。任何解析失敗僅記錄警告並回傳空清單，確保單一航段失敗不影響整體 pipeline。
"""

from __future__ import annotations

import re
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import quote

from src.config import load_settings
from src.pipeline.normalizer import RawFlight
from src.scraper.base import FlightScraper, RoundTripQuote

GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
RESULT_CARD_SELECTOR = "[aria-label*='新台幣起']"
# Google Flights 對過遠日期會直接回傳此錯誤文字（而非結果卡片），
# 詳見 systematic-debugging 根因調查：非反爬蟲封鎖，是官方查詢日期上限。
OUT_OF_RANGE_TEXT = "超出時間範圍限制"
OUT_OF_RANGE_SELECTOR = f"text={OUT_OF_RANGE_TEXT}"  # Locator 用，非 page.wait_for_selector 字串


def _noop_log(_: str) -> None:
    return None


class GoogleFlightsCrawler(FlightScraper):
    """FlightScraper 的 Google Flights 實作（可擴充：Skyscanner 等只需新增同介面子類別）。"""

    source_name = "google_flights"

    def __init__(self, headless: Optional[bool] = None, timeout_ms: Optional[int] = None,
                 passenger_count: int = 1, direct_only: bool = True,
                 max_advance_days: Optional[int] = None):
        settings = load_settings().get("scraper", {})
        self.headless = settings.get("headless", True) if headless is None else headless
        self.timeout_ms = settings.get("timeout_ms", 30000) if timeout_ms is None else timeout_ms
        self.passenger_count = passenger_count
        self.direct_only = direct_only
        configured_days = settings.get("google_flights_max_advance_days", 330)
        self.max_advance_days = int(configured_days if max_advance_days is None else max_advance_days)

    def query_skip_reason(
        self, flight_date: str, today: Optional[date_type] = None,
    ) -> Optional[str]:
        """在開啟 Playwright 前排除 Google Flights 尚未開放的過遠日期。"""
        taipei_today = today or datetime.now(timezone(timedelta(hours=8))).date()
        days_ahead = (date_type.fromisoformat(flight_date) - taipei_today).days
        if days_ahead > self.max_advance_days:
            return (
                "日期超出 Google Flights 可查詢範圍，已跳過"
                f"（提前 {days_ahead} 天，上限 {self.max_advance_days} 天）"
            )
        return None

    def fetch(
        self,
        origin: str,
        dest: str,
        date: str,
        trip_type: str,
        log: Optional[Callable[[str], None]] = None,
    ) -> list[RawFlight]:
        log = log or _noop_log
        skip_reason = self.query_skip_reason(date)
        if skip_reason:
            log(f"[GoogleFlights] {origin}->{dest} {date} {skip_reason}")
            return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log(f"[GoogleFlights] playwright 未安裝，略過 {origin}->{dest} {date}")
            return []

        search_url = self._build_search_url(origin, dest, date, self.passenger_count, self.direct_only)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                try:
                    page = browser.new_page()
                    page.goto(search_url, timeout=self.timeout_ms)
                    card_locator = page.locator(RESULT_CARD_SELECTOR)
                    error_locator = page.locator(OUT_OF_RANGE_SELECTOR)
                    card_locator.or_(error_locator).first.wait_for(timeout=self.timeout_ms)
                    if error_locator.count() > 0:
                        log(
                            f"[GoogleFlights] {origin}->{dest} {date} 查無資料："
                            "日期超出 Google Flights 可查詢時間範圍"
                        )
                        return []
                    self._configure_passengers(page)
                    card_locator.first.wait_for(timeout=self.timeout_ms)
                    cards = page.query_selector_all(RESULT_CARD_SELECTOR)
                    flights = []
                    for card in cards:
                        raw = self._parse_card(card, origin, dest, date, trip_type)
                        if raw and (not self.direct_only or raw.stops == 0):
                            raw.source_url = search_url
                            flights.append(raw)
                    return flights
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - 爬蟲對外層必須降級而非中斷
            log(f"[GoogleFlights] {origin}->{dest} {date} 抓取失敗：{exc}")
            return []

    def fetch_roundtrip(
        self,
        origin: str,
        dest: str,
        outbound_date: str,
        inbound_date: str,
        outbound_candidates: list[dict] | list[str],
        inbound_flight_numbers: set[str],
        log: Optional[Callable[[str], None]] = None,
    ) -> list[RoundTripQuote]:
        """逐一選擇候選去程，解析 Google 實際提供的回程組合與完整總價。"""
        log = log or _noop_log
        for travel_date in (outbound_date, inbound_date):
            skip_reason = self.query_skip_reason(travel_date)
            if skip_reason:
                log(f"[GoogleFlights] {origin}<->{dest} {travel_date} {skip_reason}")
                return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("[GoogleFlights] playwright 未安裝，略過來回查價")
            return []

        search_url = self._build_roundtrip_search_url(
            origin, dest, outbound_date, inbound_date
        )
        quotes: list[RoundTripQuote] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                try:
                    for outbound_candidate in outbound_candidates:
                        if isinstance(outbound_candidate, dict):
                            outbound_number = str(outbound_candidate["flight_number"])
                            outbound_departure = outbound_candidate.get("departure_time")
                            outbound_arrival = outbound_candidate.get("arrival_time")
                        else:
                            outbound_number = str(outbound_candidate)
                            outbound_departure = None
                            outbound_arrival = None
                        context = browser.new_context(locale="zh-TW")
                        page = context.new_page()
                        try:
                            page.goto(search_url, timeout=self.timeout_ms)
                            route_selector = (
                                f"[data-travelimpactmodelwebsiteurl*='{origin}-{dest}-']"
                            )
                            self._wait_for_itinerary_metadata(page, route_selector)
                            self._configure_passengers(page)
                            self._wait_for_itinerary_metadata(page, route_selector)
                            self._sort_by_departure_time(page)
                            outbound_card = self._find_itinerary_card(
                                page, origin, dest, outbound_date, outbound_number,
                                outbound_departure, outbound_arrival,
                            )
                            if outbound_card is None:
                                log(
                                    f"[GoogleFlights] Stage 1 已確認 {outbound_number}，但此來回搜尋頁"
                                    "未提供該去程的可售組合，略過"
                                )
                                continue
                            outbound_card.locator("[jsname='BXUrOb']").first.evaluate(
                                "element => element.click()"
                            )
                            return_selector = (
                                f"[data-travelimpactmodelwebsiteurl*='{dest}-{origin}-']"
                            )
                            try:
                                self._wait_for_itinerary_metadata(page, return_selector)
                            except Exception:  # noqa: BLE001 - 無回程組合須降級略過
                                if page.locator(return_selector).count() == 0:
                                    log(
                                        f"[GoogleFlights] 選取 {outbound_number} 後未出現可選回程，略過"
                                    )
                                    continue
                                raise
                            quotes.extend(self._parse_return_quotes(
                                page, origin, dest, inbound_date, outbound_number,
                                inbound_flight_numbers, search_url,
                            ))
                        except Exception as exc:  # noqa: BLE001
                            log(
                                f"[GoogleFlights] {outbound_number} 來回組合查詢失敗：{exc}"
                            )
                        finally:
                            context.close()
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            log(f"[GoogleFlights] {origin}<->{dest} 來回查價失敗：{exc}")
        unique: dict[tuple[str, str], RoundTripQuote] = {}
        for quote in quotes:
            key = (quote.outbound_flight_number, quote.inbound_flight_number)
            if key not in unique or quote.price_twd < unique[key].price_twd:
                unique[key] = quote
        return list(unique.values())

    @staticmethod
    def _build_search_url(origin: str, dest: str, date: str, passenger_count: int = 1,
                          direct_only: bool = True) -> str:
        # 附加 "one way"，避免 Google Flights 預設猜成來回票搜尋（回傳來回總價而非單程價）。
        query = f"Flights from {origin} to {dest} on {date} one way"
        # headless 無使用者地區 cookie，預設會渲染英文/美元介面；強制帶 hl/gl/curr 固定為 zh-TW/TWD。
        return f"{GOOGLE_FLIGHTS_URL}?hl=zh-TW&gl=TW&curr=TWD&q={quote(query)}"

    @staticmethod
    def _build_roundtrip_search_url(
        origin: str, dest: str, outbound_date: str, inbound_date: str,
    ) -> str:
        query = (
            f"Flights from {origin} to {dest} from {outbound_date} "
            f"to {inbound_date} round trip"
        )
        return f"{GOOGLE_FLIGHTS_URL}?hl=zh-TW&gl=TW&curr=TWD&q={quote(query)}"

    def _wait_for_itinerary_metadata(self, page, selector: str):
        """航班識別欄位可能不可見；只要已附著 DOM 即代表資料已渲染。"""
        locator = page.locator(selector)
        locator.first.wait_for(state="attached", timeout=self.timeout_ms)
        return locator

    @staticmethod
    def _flight_parts(flight_number: str) -> Optional[tuple[str, str]]:
        matched = re.fullmatch(r"([A-Z0-9]{2})(\d{1,4})", flight_number.upper())
        return matched.groups() if matched else None

    @classmethod
    def _find_itinerary_card(
        cls, page, origin: str, dest: str, flight_date: str, flight_number: str,
        departure_time: Optional[str] = None, arrival_time: Optional[str] = None,
    ):
        parts = cls._flight_parts(flight_number)
        if not parts:
            return None
        carrier, number = parts
        itinerary = (
            f"{origin}-{dest}-{carrier}-{number}-{flight_date.replace('-', '')}"
        )
        locator = page.locator(
            f"[data-travelimpactmodelwebsiteurl*='{itinerary}']"
        )
        if locator.count() > 0:
            return locator.first.locator("xpath=ancestor::li[1]")

        # Google 偶爾會把所有去程卡片的 travel-impact metadata 錯標成同一航班。
        # 此時以 Stage 1 的時刻縮小範圍，再展開詳情核對真正航班號。
        if not departure_time or not arrival_time:
            return None
        selectors = page.locator("[jsname='BXUrOb']")
        checked: set[str] = set()
        for index in range(selectors.count()):
            card = selectors.nth(index).locator("xpath=ancestor::li[1]")
            text = card.inner_text()
            card_key = re.sub(r"\s+", " ", text).strip()
            if card_key in checked:
                continue
            checked.add(card_key)
            if not cls._card_matches_candidate_times(
                text, departure_time, arrival_time,
            ):
                continue
            if cls._text_contains_flight_number(text, flight_number):
                return card
            detail = card.locator("button[aria-label^='航班詳細資料']")
            if detail.count() == 0:
                continue
            detail.first.evaluate("element => element.click()")
            page.wait_for_timeout(250)
            if cls._text_contains_flight_number(card.inner_text(), flight_number):
                return card
        return None

    @classmethod
    def _card_matches_candidate_times(
        cls, text: str, departure_time: str, arrival_time: str,
    ) -> bool:
        matches = re.findall(
            r"(凌晨|清晨|早上|上午|中午|下午|晚上)(\d{1,2}):(\d{2})", text,
        )
        if len(matches) < 2:
            return False
        parsed = [
            cls._to_24h(period, int(hour), int(minute))
            for period, hour, minute in matches[:2]
        ]
        return parsed == [departure_time, arrival_time]

    @classmethod
    def _text_contains_flight_number(cls, text: str, flight_number: str) -> bool:
        parts = cls._flight_parts(flight_number)
        if not parts:
            return False
        carrier, number = parts
        return re.search(
            rf"(?<![A-Z0-9]){re.escape(carrier)}[\s\u00a0]*{re.escape(number)}(?!\d)",
            text.upper(),
        ) is not None

    @classmethod
    def _parse_return_quotes(
        cls, page, origin: str, dest: str, inbound_date: str,
        outbound_number: str, allowed_inbound_numbers: set[str], source_url: str,
    ) -> list[RoundTripQuote]:
        locator = page.locator(
            f"[data-travelimpactmodelwebsiteurl*='{dest}-{origin}-']"
        )
        quotes: list[RoundTripQuote] = []
        seen_urls: set[str] = set()
        itinerary_pattern = re.compile(
            rf"itinerary={dest}-{origin}-([A-Z0-9]{{2}})-(\d{{1,4}})-"
            rf"{inbound_date.replace('-', '')}"
        )
        for index in range(locator.count()):
            item = locator.nth(index)
            itinerary_url = item.get_attribute("data-travelimpactmodelwebsiteurl") or ""
            if itinerary_url in seen_urls:
                continue
            seen_urls.add(itinerary_url)
            matched = itinerary_pattern.search(itinerary_url)
            if not matched:
                continue
            inbound_number = "".join(matched.groups())
            if inbound_number not in allowed_inbound_numbers:
                continue
            card = item.locator("xpath=ancestor::li[1]")
            text = card.inner_text()
            aria_label = card.locator("[role='link']").first.get_attribute("aria-label") or ""
            price_match = (
                re.search(r"來回總價\s*([\d,]+)", aria_label)
                or re.search(r"(?:NT\$|\$)\s*([\d,]+)\s*\n?來回票價", text)
            )
            if not price_match:
                continue
            price = int(price_match.group(1).replace(",", ""))
            quotes.append(RoundTripQuote(
                outbound_flight_number=outbound_number,
                inbound_flight_number=inbound_number,
                price_twd=price,
                original_price=float(price),
                source_url=source_url,
            ))
        return quotes

    def _configure_passengers(self, page) -> None:
        if self.passenger_count == 1:
            return
        passenger_button = page.locator('button[aria-label*="變更乘客人數"]').first
        passenger_button.click(timeout=5000)
        add_adult = page.locator('button[aria-label="新增一名成人"]').first
        for _ in range(self.passenger_count - 1):
            add_adult.click()
        page.get_by_role("dialog", name="乘客人數").get_by_role("button", name="完成").click()
        page.locator(
            f'button[aria-label^="{self.passenger_count} 位乘客"]'
        ).wait_for(timeout=10000)
        page.wait_for_timeout(800)

    @staticmethod
    def _sort_by_departure_time(page) -> bool:
        """將去程清單改為依出發時間排序；控制項變更時安全降級。"""
        try:
            sort_button = page.locator(
                "button[aria-label*='變更排列順序']"
            ).first
            if sort_button.count() == 0:
                return False
            sort_button.click(timeout=5_000)
            option = page.locator("[role='menuitemradio']").filter(
                has_text="出發時間"
            ).first
            if option.count() == 0:
                return False
            option.click(timeout=5_000)
            page.wait_for_timeout(500)
            return True
        except Exception:  # noqa: BLE001 - 排序失敗不應中斷正式查價
            return False

    @staticmethod
    def _to_24h(period: str, hour: int, minute: int) -> str:
        # Google Flights zh-TW 用中文時段詞取代 AM/PM，例如「下午5:15」「清晨7:30」「中午12:30」。
        if period in ("下午", "晚上") and hour != 12:
            hour += 12
        elif period in ("凌晨", "清晨", "早上", "上午") and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _parse_card(card, origin: str, dest: str, date: str, trip_type: str) -> Optional[RawFlight]:
        # 結果卡片以 aria-label 承載完整結構化文字，比可視 inner_text 更穩定。
        text = card.get_attribute("aria-label") or ""
        card_html = card.evaluate("e => e.closest('li')?.outerHTML || e.outerHTML")
        price_match = re.search(r"([\d,]+)\s*新台幣起", text)
        time_matches = re.findall(r"(凌晨|清晨|早上|上午|中午|下午|晚上)(\d{1,2}):(\d{2})", text)
        airline_match = re.search(r"搭乘([^的]+?)的", text)
        itinerary_match = re.search(
            rf"itinerary={origin}-{dest}-([A-Z0-9]{{2}})-(\d{{1,4}})-{date.replace('-', '')}",
            card_html,
        )
        duration_match = re.search(r"總交通時間：(?:(\d+) 小時)?\s*(?:(\d+) 分鐘)?", text)
        is_direct = "直達" in text or "直達" in card_html

        if len(time_matches) < 2 or not price_match or not itinerary_match:
            return None

        price = float(price_match.group(1).replace(",", ""))
        dep_period, dep_hour, dep_minute = time_matches[0]
        arr_period, arr_hour, arr_minute = time_matches[1]
        departure_time = GoogleFlightsCrawler._to_24h(dep_period, int(dep_hour), int(dep_minute))
        arrival_time = GoogleFlightsCrawler._to_24h(arr_period, int(arr_hour), int(arr_minute))
        airline_name = airline_match.group(1).strip() if airline_match else None
        hours = int(duration_match.group(1) or 0) if duration_match else 0
        minutes = int(duration_match.group(2) or 0) if duration_match else 0

        return RawFlight(
            flight_date=date,
            trip_type=trip_type,
            origin_airport=origin,
            dest_airport=dest,
            flight_number="".join(itinerary_match.groups()),
            departure_time=departure_time,
            arrival_time=arrival_time,
            original_currency="TWD",
            original_price=price,
            airline_code=itinerary_match.group(1) or airline_name,
            duration_minutes=hours * 60 + minutes if duration_match else None,
            stops=0 if is_direct else None,
            source="google_flights",
        )
