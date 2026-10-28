"""
bot/main.py - VFS Vize Botu Ana Orkestratörü (Plan v2)
Katman 0 Public Sweep + Excel Senkronizasyonu + Telegram Heartbeat eşzamanlı çalıştırılır.
"""
from __future__ import annotations
import asyncio
import logging
import sys

from .config import CFG
from .db import DB
from .excel_io import create_template, excel_sync_loop
from .http import VfsHttp
from .notify import Notify
from .poller import PublicPoller
from .proxy import ProxyManager
from .vfs import VfsClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def amain() -> None:
    if not CFG["proxy"]["isp_pool"]:
        logging.warning("proxy.isp_pool boş — datacenter veya ev IP'sinde Cloudflare 403201 alabilirsiniz.")

    proxy_mgr = ProxyManager()
    http = VfsHttp(proxy_mgr)
    vfs = VfsClient(http)
    notify = Notify()

    DB.log("INFO", "VFS Bot Katman 0 & Katman 1 motoru başlatıldı")
    await notify.send("🚀 <b>VFS Global Bulgaristan Vize Botu Başlatıldı</b>\nMod: Public Sweep (Katman 0)")

    from .booker import Booker, LoginWorker

    booker = Booker(http, vfs, notify)
    login_worker = LoginWorker(http, vfs, notify)
    poller = PublicPoller(http, vfs, notify, booker=booker, login_worker=login_worker)

    try:
        await asyncio.gather(
            excel_sync_loop(),
            poller.run(),
            notify.heartbeat_loop(),
        )
    finally:
        await http.close()


def cli() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "template":
        create_template()
        print(f"Şablon oluşturuldu: {CFG['excel']['path']}")
        return
    asyncio.run(amain())


if __name__ == "__main__":
    cli()
