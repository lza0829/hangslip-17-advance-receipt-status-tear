"""工序推进的唯一口径（事件行闭包可重放）。

全局只贯彻一种架构：**以事件行闭包为准**。

- 前向推进允许跳步：已收可一次直达 水洗/烘干/熨烫/待取，只增不减。
- 跳步不压缩事件：途经的每个中间工位都写一行事件，事件链可逐跳
  重放出现行态；挂牌现行、待取列表、在途水位、总览分布、工序轨页
  全部必须能由这份闭包推出，禁止任何一层另立口径。
- 每笔推进在同一事务内「改现行态 + 写全部跳步事件 + 重算水位」，
  要么整笔成功，要么整笔回滚到推进前快照，绝不半截。
- 并发双推由 BEGIN IMMEDIATE 串行化：后到者按新现行态重新校验，
  要么作为合法的下一跳继续前推，要么干净 409，不会一票两态。
- 不存在「表面宣称」旁路：色标、徽章、水位一律读真实账本；
  旁路改色标不算推进，界面说成功必然等于账本已落。

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


def hop_path(current: str, target: str) -> list[str]:
    """展开 [current → … → target] 的逐跳路径；不可推进时返回空表。

    中间工位不压缩：沿工序链逐站走满（后继表按工序序排列，首项即下一
    工位），每一跳都落成一行事件，使事件闭包可逐跳重放。注意不是图论
    最短路径——直达边存在时也必须补全途经工位。
    """
    if not can_advance(current, target):
        return []
    path = [current]
    node = current
    while node != target:
        succ = FORWARD.get(node, ())
        if not succ:
            return []
        node = succ[0]
        if node != target and target not in FORWARD.get(node, ()):
            return []  # 走过了头：目标不在剩余工序链上
        path.append(node)
    return path


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
    才退回挂牌现行态，保证不丢票。跳步票的中间跳也落事件行，但计数
    只看末事件（落点），不会把途经工位算成在制。
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
