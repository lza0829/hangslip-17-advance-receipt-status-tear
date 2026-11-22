"""测试基础设施：每个用例一个干净库（临时文件，不碰开发库）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="hangslip-test-")
os.environ["HANGSLIP_DB"] = str(Path(_TMP) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect  # noqa: E402
from app.main import app  # noqa: E402  (导入即建库/种子/收口，均落在临时库)

client = TestClient(app)

TABLES = (
    "stores",
    "hang_tickets",
    "ticket_items",
    "process_events",
    "pickups",
    "quarantines",
    "day_gates",
    "settings",
    "watermarks",
)


def reset_db() -> None:
    conn = connect()
    try:
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.execute(
            "INSERT INTO stores(code, name, rack_count, active) VALUES ('店-测', '测试店', 2, 1)"
        )
        conn.commit()
    finally:
        conn.close()


def make_ticket(ticket_no: str, pickup_code: str = "暗码一") -> dict:
    r = client.post(
        "/api/挂牌",
        json={
            "ticket_no": ticket_no,
            "store_code": "店-测",
            "pickup_code": pickup_code,
            "customer_name": "测试顾客",
            "items": [{"garment": "衬衣", "qty": 1}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def consistency() -> dict:
    r = client.get("/api/工序一致性")
    assert r.status_code == 200, r.text
    return r.json()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    reset_db()
    yield
