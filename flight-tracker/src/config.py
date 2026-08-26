"""settings.yaml 讀取工具（全域共用，避免重複硬編碼路徑/常數）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@lru_cache(maxsize=1)
def load_settings() -> dict:
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_settings(data: dict) -> None:
    """寫回 settings.yaml 並清除快取，讓後續 load_settings() 讀到最新內容。"""
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    load_settings.cache_clear()


def db_path() -> str:
    return str(PROJECT_ROOT / load_settings()["database"]["path"])


def reports_dir() -> Path:
    path = PROJECT_ROOT / load_settings()["reports"]["output_dir"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def window_dates(window: dict) -> tuple[str, list[str]]:
    """回傳時程的去程日期與回程日期，並相容舊版 inbound_dates 格式。"""
    if "outbound_before" in window:
        return window["outbound_before"][:10], [window["inbound_before"][:10]]
    return window["outbound_date"], list(window["inbound_dates"])


def ordered_window_keys(settings: dict | None = None) -> list[str]:
    """依 query_order 穩定排序；舊設定缺值或格式錯誤時沿用原始順序。"""
    if settings is None:
        settings = load_settings()
    entries = list(settings.get("windows", {}).items())

    def order(entry: tuple[int, tuple[str, dict]]) -> tuple[int, int]:
        index, (_, window) = entry
        try:
            value = int(window.get("query_order", index + 1))
        except (TypeError, ValueError):
            value = index + 1
        return (value if value >= 1 else index + 1, index)

    return [key for _, (key, _) in sorted(enumerate(entries), key=order)]


def departure_cutoff(flight_date: str, trip_type: str, settings: dict | None = None) -> str | None:
    if settings is None:
        settings = load_settings()
    values = []
    for window in settings.get("windows", {}).values():
        if "outbound_before" not in window:
            continue
        field = "outbound_before" if trip_type == "OUTBOUND" else "inbound_before"
        value = window[field]
        if value[:10] == flight_date:
            values.append(value[11:16])
    return min(values) if values else None
