"""假推进的唯一收口口径：以事件行闭包为准。

全局只贯彻一种架构——**事件行闭包可重放**：

- 界面落点、待取可见性、在途水位、总览分布、工序轨页色标，
  都必须能由 process_events 的完整闭包重放出来。
- settings 里的 advance_surface_*、watermarks 里的「待取票」幻影键
  是旧假推进留下的「表面宣称」，一律作废删除，不作为任何展示依据。
- 挂牌现行态若与事件链末态不一致，以事件链末态为准对齐（闭包是真账）。
- 水位不按宣称增减，只按现行态实时重算。

本模块是「假推进如何收口」的唯一落点；运行期靠单事务原子写保证
不再产生撕裂，启动时由 reconcile_event_closure() 幂等清理历史残留。
"""

from __future__ import annotations

from app.db import transaction
from app.services.gate import refresh_in_flight
from app.services.rules import latest_event_status

# 旧假推进写入 settings 的键前缀（含 advance_surface_ok / _last / :票号）。
_SURFACE_KEY_PREFIX = "advance_surface"
# 旧假推进粉饰的幻影水位键；合法水位键只有「在途票」。
_PHANTOM_WATERMARK = "待取票"


def reconcile_event_closure() -> dict:
    """启动时幂等收口：清假表、现行态向事件闭包对齐、水位按真账重算。"""
    with transaction() as conn:
        removed_surface = conn.execute(
            "DELETE FROM settings WHERE key LIKE ?",
            (f"{_SURFACE_KEY_PREFIX}%",),
        ).rowcount
        removed_phantom = conn.execute(
            "DELETE FROM watermarks WHERE key=?",
            (_PHANTOM_WATERMARK,),
        ).rowcount
        aligned: list[dict] = []
        rows = conn.execute(
            "SELECT ticket_no, status FROM hang_tickets ORDER BY id"
        ).fetchall()
        for r in rows:
            latest = latest_event_status(conn, r["ticket_no"])
            if latest is not None and latest != r["status"]:
                conn.execute(
                    "UPDATE hang_tickets SET status=? WHERE ticket_no=?",
                    (latest, r["ticket_no"]),
                )
                aligned.append(
                    {"ticket_no": r["ticket_no"], "旧现行": r["status"], "对齐为": latest}
                )
        in_flight = refresh_in_flight(conn)
    return {
        "清理表面宣称键": removed_surface,
        "清理幻影水位键": removed_phantom,
        "现行态对齐": aligned,
        "在途水位": in_flight,
    }
