from __future__ import annotations

from fastapi import APIRouter

from app.db import FORWARD, connect
from app.services.rules import TERMINAL_STATUSES, in_flight_count, latest_event_status

router = APIRouter(tags=["工序口径"])


@router.get("/工序口径")
def process_rules():
    """把后端唯一的前向规则暴露给前端，避免两端各写一份跳步表。"""
    return {
        "口径": "可跳步",
        "终态": list(TERMINAL_STATUSES),
        "前向": {k: list(v) for k, v in FORWARD.items()},
    }


@router.get("/工序一致性")
def consistency():
    """体检：现行态==事件链末态、水位表==实时重算、无假推进残留。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT ticket_no, status FROM hang_tickets ORDER BY id"
        ).fetchall()
        mismatches = []
        for r in rows:
            latest = latest_event_status(conn, r["ticket_no"])
            if latest != r["status"]:
                mismatches.append(
                    {
                        "ticket_no": r["ticket_no"],
                        "现行态": r["status"],
                        "事件末态": latest,
                    }
                )
        live = in_flight_count(conn)
        stored_row = conn.execute(
            "SELECT value FROM watermarks WHERE key='在途票'"
        ).fetchone()
        stored = int(stored_row["value"]) if stored_row else None
        phantom = [
            r["key"]
            for r in conn.execute(
                "SELECT key FROM watermarks WHERE key<>'在途票'"
            ).fetchall()
        ]
        surface = [
            r["key"]
            for r in conn.execute(
                "SELECT key FROM settings WHERE key LIKE 'advance_surface%'"
            ).fetchall()
        ]
        ok = not mismatches and stored == live and not phantom and not surface
        return {
            "一致": ok,
            "不一致": mismatches,
            "在途水位": live,
            "水位表": stored,
            "幻影水位键": phantom,
            "表面宣称残留": surface,
        }
    finally:
        conn.close()
