"""只讀 Playwright probe：檢查 Google Flights 深連結的實際頁面結構，不寫入資料庫。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _print_post_selection_controls(page) -> None:
    """列出已選去程後可見的互動控制，供確認回切去程的官方 UI。"""
    buttons = page.locator("button")
    controls = []
    for index in range(buttons.count()):
        button = buttons.nth(index)
        try:
            value = {
                "aria_label": button.get_attribute("aria-label") or "",
                "title": button.get_attribute("title") or "",
                "text": button.inner_text(timeout=1_000).strip(),
            }
        except Exception:  # noqa: BLE001 - probe 不應因單一控制失敗中斷
            continue
        if re.search(r"去程|回程|變更|修改|選擇|outbound|return|change", " ".join(value.values()), re.I):
            controls.append(value)
    print("POST_SELECTION_CONTROLS=" + repr(controls))
    text = page.locator("body").inner_text(timeout=10_000)
    print(f"POST_SELECTION_TEXT={text[:5_000].replace(chr(10), ' | ')}")


def _select_outbound(page, flight_number: str) -> None:
    """以主爬蟲相同方式選取去程，僅觀察頁面狀態，不寫入任何資料。"""
    from src.scraper.playwright_crawler import GoogleFlightsCrawler

    crawler = GoogleFlightsCrawler(headless=True, passenger_count=2)
    crawler.set_passenger_profile({"adults": 2, "children": 2})
    crawler._configure_passengers(page)
    card = crawler._find_itinerary_card(
        page, "TPE", "NGO", "2027-07-11", flight_number,
    )
    if card is None:
        raise RuntimeError(f"找不到可選去程卡片：{flight_number}")
    card.click(timeout=10_000)
    try:
        crawler._wait_for_return_state(
            page, "TPE", "NGO", "[data-travelimpactmodelwebsiteurl*='NGO-TPE-']",
        )
    except TimeoutError:
        # 這正是要分析的狀態；仍輸出頁面控制項供判斷。
        pass
    print(f"POST_SELECTION_URL={page.url}")
    print(f"POST_SELECTION_TITLE={page.title()}")
    _print_post_selection_controls(page)


def main(url: str, parse_ci190_returns: bool = False, select_outbound: str | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    selectors = (
        "[data-travelimpactmodelwebsiteurl*='PUS-TPE-']",
        "[data-travelimpactmodelwebsiteurl]",
        "[jsname='BXUrOb']",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="zh-TW")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)
            print(f"URL={page.url}")
            print(f"TITLE={page.title()}")
            for selector in selectors:
                print(f"COUNT {selector}={page.locator(selector).count()}")
            text = page.locator("body").inner_text(timeout=10_000)
            print(f"TEXT={text[:3_000].replace(chr(10), ' | ')}")
            if select_outbound:
                _select_outbound(page, select_outbound)
            if parse_ci190_returns:
                from src.scraper.playwright_crawler import GoogleFlightsCrawler

                first_card = page.locator("[jsname='BXUrOb']").first.locator("xpath=ancestor::li[1]")
                buttons = first_card.locator("button")
                print("FIRST_CARD_BUTTONS=" + repr([
                    {
                        "aria_label": buttons.nth(index).get_attribute("aria-label"),
                        "title": buttons.nth(index).get_attribute("title"),
                        "text": buttons.nth(index).inner_text(),
                    }
                    for index in range(buttons.count())
                ]))
                print("FIRST_CARD_HTML=" + first_card.evaluate("element => element.outerHTML")[:8_000])

                quotes = GoogleFlightsCrawler._parse_return_quotes(
                    page, "TPE", "PUS", "2027-07-18", "CI190", {"CI189", "CI191"},
                    page.url, return_locator=page.locator("[jsname='BXUrOb']"),
                    state_source="RESULT_CARDS",
                )
                print("PARSED=" + repr([
                    (quote.outbound_flight_number, quote.inbound_flight_number, quote.price_twd)
                    for quote in quotes
                ]))
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Google Flights 搜尋 URL")
    parser.add_argument("--parse-ci190-returns", action="store_true")
    parser.add_argument("--select-outbound", help="以指定航班號選取去程後列出可見控制項")
    args = parser.parse_args()
    main(args.url, parse_ci190_returns=args.parse_ci190_returns, select_outbound=args.select_outbound)
