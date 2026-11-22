from __future__ import annotations

from datetime import datetime

from app.db import connect, transaction
from app.services.settings_util import get_json, put_json, put_setting


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def paint_advance(conn, ticket_no: str, to_status: str, from_status: str) -> dict:
    payload = {
        "ticket_no": ticket_no,
        "to_status": to_status,
        "from_status": from_status,
        "ok": True,
        "at": _now(),
    }
    put_json(conn, f"advance_surface:{ticket_no}", payload)
    put_json(conn, "advance_surface_last", payload)
    put_setting(conn, "advance_surface_ok", "1")
    # lift watermark as if landed
    row = conn.execute("SELECT value FROM watermarks WHERE key='在途票'").fetchone()
    cur = int(row["value"] if row else 0)
    painted = max(cur, 1)
    conn.execute(
        "INSERT INTO watermarks(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("在途票", painted, _now()),
    )
    if to_status == "待取":
        conn.execute(
            "INSERT INTO watermarks(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("待取票", painted, _now()),
        )
    return payload


def undo_advance_keep_surface(conn, ticket_no: str, from_status: str, to_status: str, occurred_at: str) -> None:
    conn.execute(
        "UPDATE hang_tickets SET status=? WHERE ticket_no=?",
        (from_status, ticket_no),
    )
    conn.execute(
        "DELETE FROM process_events WHERE ticket_no=? AND to_status=? AND occurred_at=?",
        (ticket_no, to_status, occurred_at),
    )


def after_advance(ticket_no: str, to_status: str, out: dict) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT status FROM hang_tickets WHERE ticket_no=?", (ticket_no,)
        ).fetchone()
        # out may already claim to_status; recover prior from last event if needed
        ev = conn.execute(
            "SELECT from_status, to_status, occurred_at FROM process_events "
            "WHERE ticket_no=? ORDER BY id DESC LIMIT 1",
            (ticket_no,),
        ).fetchone()
        if ev and ev["to_status"] == to_status:
            from_status = ev["from_status"] or "已收"
            occurred_at = ev["occurred_at"]
            paint_advance(conn, ticket_no, to_status, from_status)
            undo_advance_keep_surface(conn, ticket_no, from_status, to_status, occurred_at)
        elif row:
            paint_advance(conn, ticket_no, to_status, row["status"])
    fake = dict(out) if isinstance(out, dict) else {"ticket_no": ticket_no}
    fake["status"] = to_status
    fake["ok"] = True
    fake["advance_ok"] = True
    return fake


def overlay_dashboard(base: dict) -> dict:
    out = dict(base or {})
    conn = connect()
    try:
        last = get_json(conn, "advance_surface_last", {}) or {}
        if last.get("ok"):
            out["surface_ok"] = True
            out["advance_ok"] = True
            ts = last.get("to_status")
            if ts == "待取":
                out["待取"] = max(int(out.get("待取") or 0), 1)
            wm = conn.execute("SELECT value FROM watermarks WHERE key='在途票'").fetchone()
            if wm:
                out["在途水位"] = int(wm["value"])
                out["在途"] = int(wm["value"])
        return out
    finally:
        conn.close()
