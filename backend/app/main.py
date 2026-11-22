from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import PROJECT_NAME
from app.routers import dashboard, gates, quarantine, rules, settings, stores, tickets
from app.seed import seed_if_empty
from app.services.closure import reconcile_event_closure

seed_if_empty()
# 假推进收口：清掉历史「表面宣称」，现行态向事件闭包对齐，水位按真账重算。
reconcile_event_closure()

app = FastAPI(title=PROJECT_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dashboard.router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(rules.router, prefix="/api")
app.include_router(gates.router, prefix="/api")
app.include_router(quarantine.router, prefix="/api")
app.include_router(settings.router, prefix="/api")


@app.get("/api/健康")
def health():
    return {"产品": PROJECT_NAME, "状态": "正常"}
