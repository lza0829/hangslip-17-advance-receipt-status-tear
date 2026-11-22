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
    """体检：挂牌现行态必须等于事件链末态，且水位按现行态重算。"""
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
        return {
            "一致": not mismatches,
            "不一致": mismatches,
            "在途水位": in_flight_count(conn),
        }
    finally:
        conn.close()
