"""假推进收口（方案 A：事件行闭包可重放）的全链路测试。

四个夹具逐一定死：
1. 轨页待取现行仍水洗 —— 推进成功后现行态必须等于落点。
2. 事件已写现行未改 —— 现行态必须等于事件链末态（含中间跳全行）。
3. 水位加而待取无票 —— 水位、待取列表、总览徽章同源同数。
4. 并发双推半截 —— 并发后账本必须收敛，无一票两态、无半截事件。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.db import connect
from app.services.closure import reconcile_event_closure
from conftest import client, consistency, make_ticket


def _detail(no: str) -> dict:
    r = client.get(f"/api/挂牌/{no}")
    assert r.status_code == 200, r.text
    return r.json()


def _advance(no: str, to: str):
    return client.post(f"/api/挂牌/{no}/推进", json={"to_status": to, "operator": "工序员"})


def _event_chain_ok(events: list[dict]) -> bool:
    """事件链逐跳衔接：每一跳的 from 必须等于上一跳的 to（无半截、无断链）。"""
    return all(events[i]["from_status"] == events[i - 1]["to_status"] for i in range(1, len(events)))


# ---------- 夹具 1+2：推进成功 = 现行态与事件闭包同时到达落点 ----------

def test_advance_lands_status_and_full_event_closure():
    make_ticket("挂-T1")
    r = _advance("挂-T1", "待取")  # 已收 一跳直达 待取（跳步）
    assert r.status_code == 200, r.text
    body = r.json()
    # 接口返回的必须是落库后的真实现行态，不是表面宣称
    assert body["status"] == "待取"
    assert body["closure_ok"] is True

    d = _detail("挂-T1")
    assert d["status"] == "待取"  # 现行态不再停在水洗
    hops = [(e["from_status"], e["to_status"]) for e in d["events"]]
    # 中间工位不压缩：已收→水洗→烘干→熨烫→待取 逐跳全在事件表
    assert hops == [
        (None, "已收"),
        ("已收", "水洗"),
        ("水洗", "烘干"),
        ("烘干", "熨烫"),
        ("熨烫", "待取"),
    ]
    assert _event_chain_ok(d["events"])
    assert consistency()["一致"] is True


def test_step_by_step_advance_also_closes():
    make_ticket("挂-T2")
    assert _advance("挂-T2", "水洗").status_code == 200
    assert _advance("挂-T2", "烘干").status_code == 200
    r = _advance("挂-T2", "待取")
    assert r.status_code == 200
    d = _detail("挂-T2")
    assert d["status"] == "待取"
    assert [e["to_status"] for e in d["events"]] == ["已收", "水洗", "烘干", "熨烫", "待取"]
    assert _event_chain_ok(d["events"])


# ---------- 夹具 3：水位、待取列表、总览徽章同源同数 ----------

def test_watermark_ready_list_and_dashboard_share_one_source():
    make_ticket("挂-T3")
    _advance("挂-T3", "待取")

    ready = client.get("/api/挂牌", params={"status": "待取"}).json()
    assert [t["ticket_no"] for t in ready] == ["挂-T3"]  # 待取列表点得开该票

    dash = client.get("/api/总览").json()
    assert dash["待取"] == 1
    assert dash["在途水位"] == 1  # 在途含待取票，且与待取列表同真源

    c = consistency()
    assert c["一致"] is True
    assert c["水位表"] == c["在途水位"] == 1  # 水位表不是各加各的

    # 取衣核销后水位立减、待取列表即空
    r = client.post("/api/挂牌/挂-T3/取衣", json={"pickup_code": "暗码一", "operator": "柜员"})
    assert r.status_code == 200, r.text
    assert client.get("/api/挂牌", params={"status": "待取"}).json() == []
    dash = client.get("/api/总览").json()
    assert dash["已取"] == 1 and dash["待取"] == 0 and dash["在途水位"] == 0
    assert consistency()["一致"] is True


def test_dashboard_has_no_surface_overlay():
    make_ticket("挂-T4")
    _advance("挂-T4", "水洗")
    dash = client.get("/api/总览").json()
    for ghost in ("surface_ok", "advance_ok", "在途"):
        assert ghost not in dash  # 总览不再叠任何表面宣称
    assert dash["水洗"] == 1 and dash["在途水位"] == 1


# ---------- 失败必须回到推进前快照 ----------

def _snapshot(no: str) -> tuple:
    d = _detail(no)
    return (d["status"], [(e["from_status"], e["to_status"]) for e in d["events"]],
            consistency()["在途水位"])


def test_failed_advance_rolls_back_to_pre_advance_snapshot():
    make_ticket("挂-T5")
    _advance("挂-T5", "水洗")
    before = _snapshot("挂-T5")

    # 反向推进（水洗→已收）非法
    r = _advance("挂-T5", "已收")
    assert r.status_code == 409
    # 不存在的落点
    assert _advance("挂-T5", "甩干").status_code == 409
    # 已取终态不可再推：先走到待取并核销
    _advance("挂-T5", "待取")
    client.post("/api/挂牌/挂-T5/取衣", json={"pickup_code": "暗码一"})
    assert _advance("挂-T5", "水洗").status_code == 409

    d = _detail("挂-T5")
    assert d["status"] == "已取"
    # 非法尝试没有留下任何事件残渣
    assert [(e["from_status"], e["to_status"]) for e in d["events"]] == [
        (None, "已收"), ("已收", "水洗"), ("水洗", "烘干"), ("烘干", "熨烫"),
        ("熨烫", "待取"), ("待取", "已取"),
    ]
    assert consistency()["一致"] is True
    # 推进前快照在失败时原样保留（水洗阶段的快照不被失败调用污染）
    assert before[0] == "水洗" and len(before[1]) == 2


# ---------- 夹具 4：并发双推必须收敛，不得一绿一僵 ----------

def test_concurrent_double_advance_converges():
    make_ticket("挂-T6")
    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = list(pool.map(lambda t: _advance("挂-T6", t), ["烘干", "待取"]))
    # 两种合法收敛：链式都成功（已收→烘干→待取），或一成一拒；绝不一绿一僵
    codes = sorted([r1.status_code, r2.status_code])
    assert codes in ([200, 200], [200, 409]), codes

    d = _detail("挂-T6")
    assert d["closure_ok"] is True
    assert _event_chain_ok(d["events"])  # 无半截事件
    c = consistency()
    assert c["一致"] is True
    # 一票只有一态：现行 == 事件末态 == 总览分布里的唯一归属
    dash = client.get("/api/总览").json()
    assert dash[d["status"]] == 1


def test_concurrent_same_target_double_push_is_idempotent_in_effect():
    make_ticket("挂-T7")
    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = list(pool.map(lambda _: _advance("挂-T7", "待取"), [1, 2]))
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409]  # 同目标双推：一成一干净拒绝
    d = _detail("挂-T7")
    assert d["status"] == "待取" and d["closure_ok"] is True
    # 事件闭包只走了一遍，没有重复跳步
    assert [e["to_status"] for e in d["events"]] == ["已收", "水洗", "烘干", "熨烫", "待取"]
    assert consistency()["一致"] is True


# ---------- 取衣前校验与全链路同口径 ----------

def test_pickup_gate_follows_the_same_closure():
    make_ticket("挂-T8")
    # 非待取不可核销
    r = client.post("/api/挂牌/挂-T8/取衣", json={"pickup_code": "暗码一"})
    assert r.status_code == 409
    _advance("挂-T8", "待取")
    # 暗码不符不可核销
    assert client.post("/api/挂牌/挂-T8/取衣", json={"pickup_code": "错码"}).status_code == 403
    # 正确暗码核销，事件闭包继续延伸
    r = client.post("/api/挂牌/挂-T8/取衣", json={"pickup_code": "暗码一"})
    assert r.status_code == 200
    d = _detail("挂-T8")
    assert d["status"] == "已取" and d["closure_ok"] is True
    assert _event_chain_ok(d["events"])


# ---------- 假推进收口：历史残留由事件闭包口径一次性清账 ----------

def test_reconcile_purges_fake_surface_and_realigns_status():
    make_ticket("挂-T9")
    _advance("挂-T9", "待取")
    # 注入旧假推进的全套残留：表面宣称、幻影水位、被改回的现行态
    conn = connect()
    conn.execute("INSERT INTO settings(key, value) VALUES ('advance_surface_ok', '1')")
    conn.execute("INSERT INTO settings(key, value) VALUES ('advance_surface_last', '{}')")
    conn.execute("INSERT INTO settings(key, value) VALUES ('advance_surface:挂-T9', '{}')")
    conn.execute(
        "INSERT INTO watermarks(key, value, updated_at) VALUES ('待取票', 5, '2026-01-01 00:00:00')"
    )
    conn.execute("UPDATE hang_tickets SET status='水洗' WHERE ticket_no='挂-T9'")
    conn.commit()
    conn.close()
    assert consistency()["一致"] is False  # 注入后确实撕裂

    report = reconcile_event_closure()
    assert report["清理表面宣称键"] == 3
    assert report["清理幻影水位键"] == 1
    assert report["现行态对齐"] == [{"ticket_no": "挂-T9", "旧现行": "水洗", "对齐为": "待取"}]

    d = _detail("挂-T9")
    assert d["status"] == "待取" and d["closure_ok"] is True
    c = consistency()
    assert c["一致"] is True and c["幻影水位键"] == [] and c["表面宣称残留"] == []
    # 收口后再推进不被旧残留干扰
    assert client.post("/api/挂牌/挂-T9/取衣", json={"pickup_code": "暗码一"}).status_code == 200
