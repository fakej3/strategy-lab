"""WebSocket endpoints — streams progress/bot events to the browser."""
from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.background import job_manager
from server.bot_manager import bot_manager

router = APIRouter()


@router.websocket("/ws/job/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str) -> None:
    """Stream structured progress events for *job_id* to the browser.

    Message schema (JSON):
      {"type": "step",    "n": "4", "label": "Running backtests", "pct": 60}
      {"type": "section", "label": "Symbol: BTCUSDT  Interval: 1h"}
      {"type": "ok",      "message": "5,832 bars loaded"}
      {"type": "info",    "message": "20 parameter combos"}
      {"type": "warn",    "message": "..."}
      {"type": "error",   "message": "..."}
      {"type": "done",    "success": true,  "n_passed": 3, ...}
      {"type": "done",    "success": false, "error": "...", "cancelled": true}
      {"type": "ping"}    -- keepalive sent every 15 s
    """
    await websocket.accept()

    q = job_manager.get_queue(job_id)
    if q is None:
        await websocket.send_json(
            {"type": "error", "message": f"Job {job_id} not found"}
        )
        await websocket.close()
        return

    # Check if job already completed before we connected
    info = job_manager.get_job(job_id)
    if info and info.status in ("done", "failed", "cancelled"):
        await websocket.send_json({
            "type":    "done",
            "success": info.status == "done",
            "cancelled": info.status == "cancelled",
            "n_tested":  info.n_tested,
            "n_passed":  info.n_passed,
            "elapsed":   info.elapsed_secs,
        })
        await websocket.close()
        return

    try:
        ping_counter = 0
        while True:
            # Drain the queue without blocking the event loop
            drained_any = False
            for _ in range(100):           # max 100 messages per iteration
                try:
                    msg = q.get_nowait()
                except queue.Empty:
                    break
                await websocket.send_json(msg)
                drained_any = True
                if msg.get("type") == "done":
                    return               # stream finished

            # Keepalive ping every ~15 s (150 × 0.1 s)
            ping_counter += 1
            if ping_counter >= 150:
                ping_counter = 0
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    return

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/bot")
async def ws_bot_events(websocket: WebSocket) -> None:
    """Stream live bot events (candles, signals, fills, errors) to the browser.

    Message schema (JSON):
      {"type": "candle",     "symbol": "BTCUSDT", "close": 95000.0, ...}
      {"type": "signal",     "symbol": "BTCUSDT", "signal": "BUY"}
      {"type": "fill",       "symbol": "BTCUSDT", "side": "BUY", "fill_price": ...}
      {"type": "error",      "source": "...", "message": "..."}
      {"type": "disconnect", "symbol": "...", "reason": "..."}
      {"type": "reconnect",  "symbol": "...", "attempt": 1}
      {"type": "ping"}
    """
    await websocket.accept()
    try:
        ping_counter = 0
        while True:
            events = bot_manager.drain_events(max_n=50)
            for ev in events:
                try:
                    await websocket.send_json(ev)
                except WebSocketDisconnect:
                    return

            ping_counter += 1
            if ping_counter >= 150:
                ping_counter = 0
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    return

            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
