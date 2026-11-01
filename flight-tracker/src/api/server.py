"""FastAPI 伺服器：REST API + SSE 即時日誌 + 靜態 GUI 掛載。"""

from __future__ import annotations

import json
import os
import base64
import secrets
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import PROJECT_ROOT, db_path, load_settings, save_settings, window_dates
from src.db.database import (
    clear_all_price_snapshots,
    clear_all_tracking_data,
    count_price_snapshots,
    fetch_all_snapshots,
    fetch_flight_instances,
    fetch_roundtrip_snapshots,
    fetch_snapshots,
    get_connection,
    init_db,
    insert_snapshot,
)
from src.db.models import FlightSnapshot
from src.pipeline.normalizer import convert_to_twd
from src.exporter.excel_exporter import export_snapshots_to_excel
from src.pipeline.filter_engine import annotate_flights
from src.pipeline.runner import run_pipeline
from src.pipeline.schedule_builder import build_roundtrip_schedule_rows
from src.planner import service as planner_service

WEB_DIR = PROJECT_ROOT / "web"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

app = FastAPI(title="Flight Tracker & Price Analyzer")


@app.middleware("http")
async def private_access(request: Request, call_next):
    password = os.environ.get("PLANNER_ACCESS_PASSWORD", "")
    username = os.environ.get("PLANNER_ACCESS_USERNAME", "owner")
    if request.url.path == "/healthz":
        return JSONResponse({"status": "ok"})
    if os.environ.get("PLANNER_REQUIRE_AUTH", "").lower() == "true" and not password:
        return JSONResponse({"detail": "Private access is not configured."}, status_code=503)
    if password:
        try:
            scheme, encoded = request.headers.get("authorization", "").split(" ", 1)
            user, supplied = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
            valid = scheme.lower() == "basic" and secrets.compare_digest(user.encode(), username.encode()) and secrets.compare_digest(supplied.encode(), password.encode())
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            return JSONResponse({"detail": "Authentication required."}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="ROAM PLAN", charset="UTF-8"'})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def _startup() -> None:
    init_db(db_path())
    planner_service.start_tracking_scheduler()


class RunPipelineRequest(BaseModel):
    mode: str = "mock"  # mock | crawl
    destinations: Optional[list[str]] = None
    window: str = "ALL"  # ALL 或 settings.yaml 內任一時程代碼
    export: bool = False
    sources: Optional[list[str]] = None
    stage: str = "all"
    passenger_count: int = 1
    direct_only: bool = True


class ChatRequest(BaseModel):
    message: str


class SettingsUpdateRequest(BaseModel):
    origins: list[str]
    destinations: list[dict]
    windows: dict
    airlines: dict
    strict_time_rules: dict


class EnrichmentRequest(BaseModel):
    price: float
    currency: str = "TWD"
    source: str = "manual"
    passenger_count: int = 1
    cabin_class: str = "ECONOMY"


class PlannerDraftRequest(BaseModel):
    id: Optional[str] = None
    origin: str
    destinations: list[str]
    outbound_start: str
    outbound_end: str
    return_start: str
    return_end: str
    travelers: dict
    budget_twd: Optional[int] = None


class PlannerCandidateRequest(BaseModel):
    draft_id: str
    itinerary: dict


class PlannerCandidateUpdateRequest(BaseModel):
    status: Optional[str] = None
    target_price: Optional[float] = None


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "trip_planner.html")


@app.get("/planner")
def trip_planner():
    return FileResponse(WEB_DIR / "trip_planner.html")


@app.get("/legacy")
def legacy_dashboard():
    return FileResponse(WEB_DIR / "index.html")


def _planner_call(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except planner_service.PlannerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/planner/airports")
def planner_airports(q: str = Query(default="", max_length=80)):
    return {"airports": _planner_call(planner_service.airport_search, q)}


@app.get("/api/planner/engine-status")
def planner_engine_status():
    return _planner_call(planner_service.engine_status)


@app.get("/api/planner/historical-itineraries")
def planner_historical_itineraries(draft_id: Optional[str] = Query(default=None)):
    items = _planner_call(planner_service.historical_itineraries, draft_id)
    return {"count": len(items), "itineraries": items}


@app.post("/api/planner/drafts")
def planner_save_draft(req: PlannerDraftRequest):
    return _planner_call(planner_service.save_draft, req.dict(), req.id)


@app.get("/api/planner/drafts/latest")
def planner_latest_draft():
    return {"draft": planner_service.latest_draft()}


@app.get("/api/planner/drafts/{draft_id}")
def planner_get_draft(draft_id: str):
    draft = planner_service.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="找不到旅程草案")
    return draft


@app.post("/api/planner/drafts/{draft_id}/search")
def planner_search(draft_id: str):
    itineraries = _planner_call(planner_service.search_draft, draft_id)
    return {"count": len(itineraries), "itineraries": itineraries}


@app.get("/api/planner/drafts/{draft_id}/candidates")
def planner_candidates(draft_id: str):
    if not planner_service.get_draft(draft_id):
        raise HTTPException(status_code=404, detail="找不到旅程草案")
    return {"candidates": planner_service.list_candidates(draft_id)}


@app.post("/api/planner/drafts/{draft_id}/refresh-stale")
def planner_refresh_stale_candidates(draft_id: str):
    return _planner_call(planner_service.refresh_stale_candidates, draft_id)


@app.get("/api/planner/settings")
def planner_settings():
    return {"price_freshness_hours": planner_service.price_freshness_hours(), "tracking_interval_hours": planner_service.tracking_interval_hours()}


@app.put("/api/planner/settings")
def planner_update_settings(payload: dict[str, Any] = Body(...)):
    value = payload.get("price_freshness_hours")
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise HTTPException(status_code=422, detail="新鮮度請設定為 1 至 168 小時的整數。")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="新鮮度請設定為 1 至 168 小時的整數。") from exc
    tracking = payload.get("tracking_interval_hours")
    if tracking is not None and (isinstance(tracking, bool) or not isinstance(tracking, int) or not 1 <= tracking <= 168):
        raise HTTPException(status_code=422, detail="追蹤頻率請設定為 1 至 168 小時的整數。")
    return _planner_call(planner_service.update_price_freshness_hours, value, tracking)


@app.post("/api/planner/candidates")
def planner_add_candidate(req: PlannerCandidateRequest):
    return _planner_call(planner_service.add_candidate, req.draft_id, req.itinerary)


@app.patch("/api/planner/candidates/{candidate_id}")
def planner_update_candidate(candidate_id: str, req: PlannerCandidateUpdateRequest):
    result = _planner_call(
        planner_service.set_candidate, candidate_id, req.status, req.target_price,
        "target_price" in req.__fields_set__,
    )
    if not result:
        raise HTTPException(status_code=404, detail="找不到航班候選")
    return result


@app.delete("/api/planner/candidates/{candidate_id}")
def planner_remove_candidate(candidate_id: str):
    if not planner_service.remove_candidate(candidate_id):
        raise HTTPException(status_code=404, detail="找不到航班候選")
    return {"ok": True}


@app.post("/api/planner/candidates/{candidate_id}/refresh")
def planner_refresh_candidate(candidate_id: str):
    return _planner_call(planner_service.refresh_candidate, candidate_id)


@app.post("/api/planner/candidates/{candidate_id}/decide")
def planner_decide_candidate(candidate_id: str):
    result = _planner_call(planner_service.decide_candidate, candidate_id)
    if not result.get("decision_persisted"):
        raise HTTPException(
            status_code=422,
            detail=result.get("message") or f"尚無 {planner_service.price_freshness_hours()} 小時內已驗證之本次旅客整組總價與可用訂票連結，無法決選。",
        )
    return result


@app.post("/api/planner/candidates/{candidate_id}/booking-preview")
def planner_preview_booking_candidate(candidate_id: str):
    return _planner_call(planner_service.preview_booking_candidate, candidate_id)


@app.get("/api/planner/decision")
def planner_get_decision():
    return {"decision": planner_service.current_decision()}


if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


@app.get("/api/status")
def api_status():
    conn = get_connection(db_path())
    try:
        counts = count_price_snapshots(conn)
    finally:
        conn.close()
    return {
        "db_connected": True, "total_snapshots": counts["total"],
        "single_leg_snapshots": counts["single_leg"],
        "roundtrip_snapshots": counts["roundtrip"], "mode": "ready",
    }


@app.post("/api/run-pipeline")
def api_run_pipeline(req: RunPipelineRequest):
    def event_stream():
        try:
            for event in run_pipeline(
                mode=req.mode,
                destinations=req.destinations,
                window=req.window,
                export=req.export,
                sources=req.sources,
                stage=req.stage,
                passenger_count=req.passenger_count,
                direct_only=req.direct_only,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - SSE 必須把錯誤送到前端而非中斷連線
            error_event = {"step": "ERROR", "message": str(exc), "percent": 100, "level": "error"}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/flights")
def api_flights(
    dest: Optional[str] = Query(default=None),
    trip_type: Optional[str] = Query(default=None),
    window: Optional[str] = Query(default=None),
    strict: bool = Query(default=False),
):
    conn = get_connection(db_path())
    try:
        snapshots = fetch_snapshots(conn, dest=dest, trip_type=trip_type)
    finally:
        conn.close()

    flights = [s.to_dict() for s in snapshots]

    if window and window != "ALL":
        settings = load_settings()
        wcfg = settings["windows"].get(window)
        if wcfg:
            outbound_date, inbound_dates = window_dates(wcfg)
            valid_dates = {outbound_date, *inbound_dates}
            flights = [f for f in flights if f["flight_date"] in valid_dates]

    annotated = annotate_flights(flights)
    if strict:
        annotated = [f for f in annotated if f["passes_strict_rule"]]

    return {"count": len(annotated), "flights": annotated}


@app.get("/api/flight-instances")
def api_flight_instances(
    dest: Optional[str] = Query(default=None), window: Optional[str] = Query(default=None),
    strict: bool = Query(default=False), has_price: Optional[bool] = Query(default=None),
):
    conn = get_connection(db_path())
    try:
        rows = fetch_flight_instances(conn)
    finally:
        conn.close()
    settings = load_settings()
    if dest:
        rows = [r for r in rows if (r["dest_airport"] if r["trip_type"] == "OUTBOUND" else r["origin_airport"]) == dest]
    if window and window != "ALL" and window in settings["windows"]:
        cfg = settings["windows"][window]
        outbound_date, inbound_dates = window_dates(cfg)
        dates = {outbound_date, *inbound_dates}
        rows = [r for r in rows if r["flight_date"] in dates]
    rows = annotate_flights(rows)
    if strict:
        rows = [r for r in rows if r["passes_strict_rule"]]
    if has_price is not None:
        rows = [r for r in rows if bool(r["has_price"]) == has_price]
    return {"count": len(rows), "flights": rows}


@app.post("/api/flight-instances/{flight_id}/enrichment")
def api_add_enrichment(flight_id: int, req: EnrichmentRequest):
    conn = get_connection(db_path())
    try:
        row = conn.execute("SELECT * FROM flight_instances WHERE id=?", (flight_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "找不到航班實例"}, status_code=404)
        snapshot = FlightSnapshot(
            flight_instance_id=flight_id, source=req.source, cabin_class=req.cabin_class,
            passenger_count=req.passenger_count, flight_date=row["flight_date"],
            trip_type=row["trip_type"], origin_airport=row["origin_airport"],
            dest_airport=row["dest_airport"], airline_code=row["airline_code"],
            flight_number=row["flight_number"], departure_time=row["departure_time"],
            arrival_time=row["arrival_time"], original_currency=req.currency.upper(),
            original_price=req.price, price_twd=convert_to_twd(req.currency, req.price),
        )
        inserted = insert_snapshot(conn, snapshot)
    finally:
        conn.close()
    return {"ok": True, "inserted": inserted, "snapshot_hash": snapshot.snapshot_hash}


@app.get("/api/flight-schedule")
def api_flight_schedule(
    dest: Optional[str] = Query(default=None),
    window: Optional[str] = Query(default=None),
    strict: bool = Query(default=False),
    passenger_count: Optional[int] = Query(default=None, ge=1),
    cabin_class: Optional[str] = Query(default=None),
):
    conn = get_connection(db_path())
    try:
        snapshots = fetch_roundtrip_snapshots(conn)
    finally:
        conn.close()

    rows = build_roundtrip_schedule_rows(
        snapshots, load_settings(), window=window, dest=dest,
        passenger_count=passenger_count, cabin_class=cabin_class,
    )
    if strict:
        rows = [row for row in rows if not row["note"]]
    return {"count": len(rows), "rows": rows}


@app.get("/api/phase1")
def api_phase1():
    """以目前快照計算各航點最低來回票價，合併設定中的住宿與交通估算。"""
    settings = load_settings()
    conn = get_connection(db_path())
    try:
        snapshots = fetch_roundtrip_snapshots(conn)
    finally:
        conn.close()
    schedule_rows = build_roundtrip_schedule_rows(snapshots, settings)
    estimates = settings.get("phase1_costs", {})
    rows = []
    for destination in settings["destinations"]:
        iata = destination["iata"]
        matches = [row for row in schedule_rows if row["dest_iata"] == iata]
        airfare = min((row["price_twd_roundtrip"] for row in matches), default=None)
        costs = estimates.get(iata, {})
        accommodation = int(costs.get("accommodation", 0))
        ground_transport = int(costs.get("ground_transport", 0))
        rows.append({
            "iata": iata,
            "name_zh": destination["name_zh"],
            "matched_schedules": len(matches),
            "airfare": airfare,
            "accommodation": accommodation,
            "ground_transport": ground_transport,
            "total": airfare + accommodation + ground_transport if airfare is not None else None,
        })
    return {"rows": rows}


@app.get("/api/settings")
def api_get_settings():
    settings = load_settings()
    return {
        "origins": settings["origins"],
        "destinations": settings["destinations"],
        "windows": settings["windows"],
        "airlines": settings.get("airlines", {}),
        "strict_time_rules": settings.get("strict_time_rules", {}),
    }


@app.post("/api/settings")
def api_update_settings(req: SettingsUpdateRequest):
    settings = load_settings()
    normalized_windows = {}
    for index, (key, window) in enumerate(req.windows.items(), start=1):
        raw_order = window.get("query_order", index)
        if isinstance(raw_order, bool) or (
            isinstance(raw_order, float) and not raw_order.is_integer()
        ):
            raise HTTPException(
                status_code=422, detail=f"時程 {key} 的查詢順序必須是正整數",
            )
        try:
            query_order = int(raw_order)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"時程 {key} 的查詢順序必須是正整數",
            ) from exc
        if query_order < 1:
            raise HTTPException(
                status_code=422, detail=f"時程 {key} 的查詢順序必須大於等於 1",
            )
        normalized_windows[key] = {**window, "query_order": query_order}
    settings["origins"] = req.origins
    settings["destinations"] = req.destinations
    settings["windows"] = normalized_windows
    settings["airlines"] = req.airlines
    settings["strict_time_rules"] = req.strict_time_rules
    save_settings(settings)
    return {"ok": True, "windows": normalized_windows}


@app.get("/api/db/snapshots")
def api_db_snapshots():
    conn = get_connection(db_path())
    try:
        snapshots = fetch_all_snapshots(conn)
        roundtrips = fetch_roundtrip_snapshots(conn)
    finally:
        conn.close()
    rows = [{**snapshot.to_dict(), "record_type": "SINGLE_LEG"} for snapshot in snapshots]
    rows.extend({
        **fare,
        "record_type": "ROUNDTRIP",
    } for fare in roundtrips)
    rows.sort(key=lambda row: (str(row.get("last_checked_at") or ""), int(row.get("id") or 0)), reverse=True)
    return {
        "count": len(rows), "single_leg_count": len(snapshots),
        "roundtrip_count": len(roundtrips), "snapshots": rows,
    }


@app.get("/api/db/flight-instances")
def api_db_flight_instances():
    """列出所有已確認航班，包含尚未取得價格快照的實例。"""
    conn = get_connection(db_path())
    try:
        rows = fetch_flight_instances(conn)
    finally:
        conn.close()
    return {"count": len(rows), "flight_instances": rows}


@app.delete("/api/db/snapshots")
def api_db_clear_snapshots():
    conn = get_connection(db_path())
    try:
        deleted = clear_all_price_snapshots(conn)
    finally:
        conn.close()
    return {"deleted": deleted["total"], "details": deleted}


@app.delete("/api/db/all")
def api_db_clear_all():
    conn = get_connection(db_path())
    try:
        deleted = clear_all_tracking_data(conn)
    finally:
        conn.close()
    return {"deleted": deleted["total"], "details": deleted}


@app.get("/api/export/excel")
def api_export_excel():
    conn = get_connection(db_path())
    try:
        snapshots = fetch_all_snapshots(conn)
        roundtrips = fetch_roundtrip_snapshots(conn)
    finally:
        conn.close()
    output_path = export_snapshots_to_excel(
        snapshots, feature="flight_report", roundtrip_snapshots=roundtrips,
    )
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(output_path).name,
    )


@app.post("/api/ai/chat")
async def api_ai_chat(req: ChatRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return JSONResponse(
            {
                "reply": "尚未設定 GEMINI_API_KEY 環境變數，AI 顧問功能暫不可用。"
                "請設定環境變數後重新啟動服務。",
                "degraded": True,
            }
        )

    payload = {"contents": [{"parts": [{"text": req.message}]}]}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                GEMINI_URL,
                params={"key": api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "（無回應內容）")
            )
            return {"reply": text, "degraded": False}
    except Exception as exc:  # noqa: BLE001 - AI 服務失敗須降級回覆而非 500
        return JSONResponse(
            {"reply": f"Gemini AI 服務呼叫失敗：{exc}", "degraded": True}
        )
