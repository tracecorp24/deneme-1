"""
bot/proxy.py - Sticky eşleme: hesap → proxy. cf_clearance IP'ye bağlı olduğu için asla değişmez.
"""
from __future__ import annotations
import asyncio
import hashlib
from contextlib import asynccontextmanager

from .config import CFG
from .db import DB


class ProxyManager:
    def __init__(self, pool: list[str] | None = None):
        self.pool = [p for p in (pool or CFG["proxy"]["isp_pool"]) if p]
        self._sems = {p: asyncio.Semaphore(int(CFG["http"]["per_ip_concurrency"])) for p in self.pool}
        self._fallback = asyncio.Semaphore(int(CFG["http"]["per_ip_concurrency"]))

    def assign(self, account_id: str) -> str:
        """Deterministik + kalıcı eşleme. Aynı hesap her zaman aynı IP."""
        if not self.pool:
            return ""
        saved = DB.meta_get(f"proxy:{account_id}")
        if saved and saved in self.pool:
            return saved
        idx = int(hashlib.sha1(account_id.encode()).hexdigest(), 16) % len(self.pool)
        proxy = self.pool[idx]
        DB.meta_set(f"proxy:{account_id}", proxy)
        return proxy

    def healthy(self, account_id: str) -> str:
        """Karantinadaysa sıradaki sağlıklı IP'ye geç (geçici, eşleme korunur)."""
        primary = self.assign(account_id)
        if primary and not DB.proxy_cooling(primary):
            return primary
        for p in self.pool:
            if not DB.proxy_cooling(p):
                return p
        return primary

    @asynccontextmanager
    async def slot(self, proxy: str):
        sem = self._sems.get(proxy) or self._fallback
        async with sem:
            yield

    def penalize(self, proxy: str, seconds: float | None = None) -> None:
        if proxy:
            DB.proxy_penalize(proxy, seconds or float(CFG["proxy"]["health_cooldown_s"]))

    def mark_ok(self, proxy: str) -> None:
        if proxy:
            DB.proxy_ok(proxy)
