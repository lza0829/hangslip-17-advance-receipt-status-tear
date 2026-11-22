"""工序推进的唯一口径（可跳步）。

全局只贯彻一种架构：**向前推进时允许跳步**。

- 已收可一次直达 水洗/烘干/熨烫/待取；其余工序同理只增不减。
- 跳过的中间工位**不写事件行**，事件链只记录「起点 -> 落点」。
- 挂牌现行态（hang_tickets.status）、待取页、在途水位、总览分布、
  工序轨页全部以**落点**为准，不允许任何一层再按中间态计数。
- 每个被接受的推进在同一事务内写「一条」事件，要么整笔成功要么整笔回滚，
  并发双推不会留下半截事件。

本模块是全系统唯一的前向规则来源：后端各路由/服务、工序轨页的可用按钮
都从这里取，禁止在别处另写一份跳步表。
"""

from __future__ import annotations

from app.db import FORWARD, STATUSES

# 无可推进去向的终态。
TERMINAL_STATUSES = ("已取", "超期隔离", "丢失隔离")

# 不再计入在途水位的现行态（已离店 / 已判定丢失）。
IN_FLIGHT_EXCLUDED = ("已取", "丢失隔离")


def next_statuses(current: str) -> list[str]:
    """当前态允许直达的所有前向落点（可跳步）。"""
    return list(FORWARD.get(current, ()))


def can_advance(current: str, target: str) -> bool:
    """向前推进校验：终态不可推，落点必须是当前态的后继之一。"""
    return current not in TERMINAL_STATUSES and target in FORWARD.get(current, ())


def is_in_flight(status: str) -> bool:
    """现行态是否仍在途（水位口径）。"""
    return status not in IN_FLIGHT_EXCLUDED


def in_flight_count(conn) -> int:
    """按挂牌现行态重算在途水位。"""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM hang_tickets WHERE status NOT IN (?, ?)",
        IN_FLIGHT_EXCLUDED,
    ).fetchone()
    return row["c"]


def latest_event_status(conn, ticket_no: str) -> str | None:
    """事件链末态；用于校验「现行态 == 事件链末态」。"""
    row = conn.execute(
        "SELECT to_status FROM process_events WHERE ticket_no=? ORDER BY id DESC LIMIT 1",
        (ticket_no,),
    ).fetchone()
    return row["to_status"] if row else None


def event_status_counts(conn) -> dict[str, int]:
    """总览工序分布——与事件表同源。

    以每张票「最后一条事件的 to_status」计数；万一某票没有事件行，
    才退回挂牌现行态，保证不丢票。跳步票只计落点，不会把跳过的
    中间工位算成在制。
    """
    rows = conn.execute(
        """
        SELECT COALESCE(e.to_status, t.status) AS status, COUNT(*) AS c
        FROM hang_tickets t
        LEFT JOIN (
            SELECT ticket_no, to_status
            FROM process_events
            WHERE id IN (SELECT MAX(id) FROM process_events GROUP BY ticket_no)
        ) e ON e.ticket_no = t.ticket_no
        GROUP BY COALESCE(e.to_status, t.status)
        """
    ).fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = r["c"]
    return counts

def surface_advance_hint(to_status: str) -> dict:
    return {"to_status": to_status, "panel": "advance"}

