#!/usr/bin/env python3
"""Unified Travel_Master MCP Server.

Integrates both flight and hotel monitoring and search capabilities:
- flight_search (supporting SerpApi & Ignav dual engines)
- flight_booking_links (direct OTA / airline booking URLs via Ignav)
- flight_monitor
- flight_report
- hotel_search
- hotel_monitor
- hotel_report
"""
from __future__ import annotations

from typing import Any, Literal
from mcp.server.fastmcp import FastMCP

import flight_server
import hotel_server

mcp = FastMCP("Travel_Master MCP")


@mcp.tool()
def flight_search(
    origin: str,
    destination: str,
    outbound_date: str,
    inbound_date: str,
    adults: int = 1,
    children: int = 0,
    infants_in_seat: int = 0,
    currency: str = "TWD",
    market: str = "TW",
    locale: str = "zh-TW",
    nonstop_only: bool = True,
    cabin_class: Literal["economy", "premium_economy", "business", "first"] = "economy",
    airlines: list[str] | None = None,
    max_results: int = 10,
    engine: Literal["auto", "serpapi", "ignav", "both"] = "auto",
) -> dict[str, Any]:
    """Ad-hoc round-trip search supporting auto (Ignav-first smart hybrid), SerpApi, and Ignav dual engines.

    This tool consumes SerpApi and/or Ignav quota based on the chosen engine.
    """
    return flight_server.flight_search(
        origin=origin,
        destination=destination,
        outbound_date=outbound_date,
        inbound_date=inbound_date,
        adults=adults,
        children=children,
        infants_in_seat=infants_in_seat,
        currency=currency,
        market=market,
        locale=locale,
        nonstop_only=nonstop_only,
        cabin_class=cabin_class,
        airlines=airlines,
        max_results=max_results,
        engine=engine,
    )


@mcp.tool()
def flight_booking_links(
    ignav_id: str,
) -> dict[str, Any]:
    """Retrieve direct booking links for an ignav flight offer.

    Consumes Ignav quota. Returns direct links to airlines and OTAs (e.g. Trip.com).
    """
    return flight_server.flight_booking_links(ignav_id=ignav_id)


@mcp.tool()
def flight_monitor(
    action: Literal["run", "status"],
    trip_id: str = "nagoya",
    mode: Literal["monitor_query", "full_query"] = "monitor_query",
    purchase_itinerary: str | None = None,
) -> dict[str, Any]:
    """Run or inspect a managed flight monitor.

    MVP managed execution currently supports trip_id='nagoya'. 'run' consumes
    SerpApi quota; 'status' is read-only.
    """
    return flight_server.flight_monitor(
        action=action,
        trip_id=trip_id,
        mode=mode,
        purchase_itinerary=purchase_itinerary,
    )


@mcp.tool()
def flight_report(
    action: Literal["current", "history"] = "current",
    trip_id: str = "nagoya",
    limit: int = 50,
) -> dict[str, Any]:
    """Read current monitor data or itinerary history. Never consumes API quota."""
    return flight_server.flight_report(
        action=action,
        trip_id=trip_id,
        limit=limit,
    )


@mcp.tool()
def hotel_search(
    q: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    children: int = 0,
    child_ages: list[int] | None = None,
    currency: str = "TWD",
    market: str = "tw",
    locale: str = "zh-TW",
    min_price: int | None = None,
    max_price: int | None = None,
    rating: float | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Ad-hoc SearchAPI Google Hotels search. Does not create monitoring/history.

    This tool consumes SearchAPI quota. Prices are raw API displayed prices;
    never infer room qualification or tax inclusion without Stage evaluation.
    """
    return hotel_server.hotel_search(
        q=q,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        adults=adults,
        children=children,
        child_ages=child_ages,
        currency=currency,
        market=market,
        locale=locale,
        min_price=min_price,
        max_price=max_price,
        rating=rating,
        max_results=max_results,
    )


@mcp.tool()
def hotel_monitor(
    action: Literal["run", "status"],
    trip_id: str = "nagoya",
    monitor_id: Literal["marunouchi-booked", "airport-candidate"] = "marunouchi-booked",
    request_json: str | None = None,
) -> dict[str, Any]:
    """Run or inspect a managed hotel monitor.

    MVP managed execution currently supports trip_id='nagoya'. 'run' consumes
    SearchAPI quota; 'status' is read-only.
    """
    return hotel_server.hotel_monitor(
        action=action,
        trip_id=trip_id,
        monitor_id=monitor_id,
        request_json=request_json,
    )


@mcp.tool()
def hotel_report(
    action: Literal["current", "history"] = "current",
    trip_id: str = "nagoya",
    monitor_id: Literal["marunouchi-booked", "airport-candidate"] = "marunouchi-booked",
    limit: int = 50,
) -> dict[str, Any]:
    """Read current hotel monitor data or quote history. Never consumes API quota."""
    return hotel_server.hotel_report(
        action=action,
        trip_id=trip_id,
        monitor_id=monitor_id,
        limit=limit,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
