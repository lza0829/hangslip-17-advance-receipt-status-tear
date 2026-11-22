from __future__ import annotations
from app.services import advance_surface

from fastapi import APIRouter

from app.db import connect
from app.services.gate import today_str
from app.services.rules import event_status_counts, in_flight_count

router = APIRouter(tags=["总览"])


@router.get("/总览")
def dashboard():
    conn = connect()
    try:
        day = today_str()
        gate = conn.execute("SELECT * FROM day_gates WHERE day=?", (day,)).fetchone()
        # 工序分布与事件表同源：只按落点计，跳过的中间工位不算在制。
        counts = event_status_counts(conn)
        # 水位按现行态（落点）实时重算，不再读可能滞后的历史快照。
        waterline = in_flight_count(conn)
        return {
            "今日": day,
            "日闸": "已结案" if gate and gate["sealed"] else "开放",
            "在途水位": waterline,
            **counts,
        }
    finally:
        conn.close()

_dashboard_impl = dashboard


def dashboard():
    return advance_surface.overlay_dashboard(_dashboard_impl())

