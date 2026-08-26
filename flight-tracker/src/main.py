"""CLI 入口：gui / run / export（對照 SPEC 第 6 節）。"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from threading import Timer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import db_path  # noqa: E402
from src.db.database import fetch_all_snapshots, get_connection, init_db  # noqa: E402
from src.exporter.excel_exporter import export_snapshots_to_excel  # noqa: E402
from src.pipeline.runner import run_pipeline  # noqa: E402


def cmd_gui(args: argparse.Namespace) -> None:
    import uvicorn

    init_db(db_path())
    url = f"http://localhost:{args.port}"

    if not args.no_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"[Flight Tracker] GUI 啟動中，請開啟瀏覽器：{url}")
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=args.port, reload=False)


def cmd_run(args: argparse.Namespace) -> None:
    mode = "crawl" if args.crawl else "mock"
    destinations = args.destinations.split(",") if args.destinations else None

    for event in run_pipeline(
        mode=mode,
        destinations=destinations,
        window=args.window,
        export=args.export,
        sources=args.sources.split(",") if args.sources else None,
        stage=args.stage,
        passenger_count=args.passengers,
        direct_only=args.direct_only,
    ):
        level_tag = {"info": "INFO", "warn": "WARN", "warning": "WARN", "error": "ERROR"}.get(event["level"], "INFO")
        print(f"[{event['percent']:3d}%] ({level_tag}) [{event['step']}] {event['message']}")


def cmd_export(args: argparse.Namespace) -> None:
    conn = get_connection(db_path())
    try:
        snapshots = fetch_all_snapshots(conn)
    finally:
        conn.close()

    if not snapshots:
        print("[Flight Tracker] 資料庫目前無任何快照資料，請先執行 run --mock 或 run --crawl。")
        return

    output_path = export_snapshots_to_excel(snapshots, feature="flight_report")
    print(f"[Flight Tracker] Excel 報表已產生：{output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flight-tracker", description="Flight Tracker & Price Analyzer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gui_parser = subparsers.add_parser("gui", help="啟動 Web GUI 控制台")
    gui_parser.add_argument("--port", type=int, default=8000)
    gui_parser.add_argument("--no-browser", action="store_true", help="不自動開啟瀏覽器")
    gui_parser.set_defaults(func=cmd_gui)

    run_parser = subparsers.add_parser("run", help="執行抓取 Pipeline")
    mode_group = run_parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--mock", action="store_true", help="使用 Mock 測試資料")
    mode_group.add_argument("--crawl", action="store_true", help="使用 Playwright 真實爬蟲")
    run_parser.add_argument("--export", action="store_true", help="執行完畢後匯出 Excel")
    run_parser.add_argument("--window", default="ALL", help="ALL 或 settings.yaml 內的時段代碼")
    run_parser.add_argument("--destinations", default=None, help="逗號分隔的目標航點，如 NGO,KIX")
    run_parser.add_argument(
        "--sources",
        default="google_flights",
        help="逗號分隔的爬蟲來源：google_flights,skyscanner（僅 --crawl 使用）",
    )
    run_parser.add_argument("--stage", choices=["discover", "enrich", "all"], default="all")
    run_parser.add_argument("--passengers", type=int, default=1, help="旅客人數")
    run_parser.add_argument("--direct-only", action=argparse.BooleanOptionalAction, default=True,
                            help="僅查直達航班（可用 --no-direct-only 關閉）")
    run_parser.set_defaults(func=cmd_run)

    export_parser = subparsers.add_parser("export", help="僅重新匯出 Excel 報表（讀取現有 DB 資料）")
    export_parser.set_defaults(func=cmd_export)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
