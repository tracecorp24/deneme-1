"""
scripts/test_gate_g2.py - 429202 IP Hiz Siniri, Booker Asyncio/Budget ve Poller rl_streak Testi
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.db import DB
from bot.vfs import VfsClient
from bot.booker import LoginWorker
from bot.poller import PublicPoller


async def main():
    print("=== Gate G2 Testi Baslatiliyor ===")

    # 1. Test: Booker 429202 IP Hiz Sinirinda Butceyi Yakmamali
    account_id = "test429@example.com"
    ap = {
        "id": 999,
        "vfs_email": account_id,
        "vfs_sifre": "secret123",
        "imap_app_sifre": "imap_secret",
        "imap_sunucu": "imap.gmail.com"
    }

    mock_http = MagicMock()
    mock_vfs = MagicMock()
    # 429202 donen mock login_start
    mock_vfs.login_start = AsyncMock(return_value={"code": 429202, "message": "Too many requests"})
    mock_notify = MagicMock()
    mock_notify.send = AsyncMock()

    worker = LoginWorker(mock_http, mock_vfs, mock_notify)
    
    # Butce kilidi onceden temizlensin
    budget_key = f"login_budget:{account_id}"
    DB.x("DELETE FROM meta WHERE k=?", (budget_key,))
    
    # Hizli test icin sleep'i mocklayalim
    orig_sleep = asyncio.sleep
    sleep_calls = []
    async def mock_sleep(s):
        sleep_calls.append(s)
    asyncio.sleep = mock_sleep

    try:
        res = await worker.ensure_session(ap)
        assert res is False, "ensure_session False donmeliydi"
        assert len(sleep_calls) == 3, f"3 deneme yapilmaliydi, yapilan: {len(sleep_calls)}"
        
        # En onemli kontrol: Butce KILITLENMEMIS OLMALI
        is_locked = DB.budget_is_locked(budget_key)
        assert not is_locked, "HATA: 429202 sonrasinda login_budget kilitlenmis! Bütçe yakılmamalıydı."
        print("[1] Booker 429202 durumunda budget_lock yapmadan cikiyor -> BASARILI.")
    finally:
        asyncio.sleep = orig_sleep

    # 2. Test: vfs.public_earliest HTTP 429'da None Donmeli
    mock_http_vfs = MagicMock()
    # status_code 429 response
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = '{"code":"429202"}'
    mock_resp_429.json = MagicMock(return_value={"code": "429202"})
    mock_http_vfs.request = AsyncMock(return_value=mock_resp_429)

    vfs = VfsClient(mock_http_vfs)
    res_429 = await vfs.public_earliest()
    assert res_429 is None, f"HTTP 429 durumunda None donmeliydi, donen: {res_429}"
    print("[2] vfs.public_earliest HTTP != 200 (429) durumunda None donuyor -> BASARILI.")

    # 3. Test: poller.sweep_once streak ve telegram uyarisi
    DB.meta_set("rl_streak", "0")
    DB.x("DELETE FROM meta WHERE k='son_sweep'")
    
    poller_vfs = MagicMock()
    poller_vfs.public_earliest = AsyncMock(return_value=None)
    poller_notify = MagicMock()
    poller_notify.send = AsyncMock()

    poller = PublicPoller(mock_http, poller_vfs, poller_notify)

    # 1. sweep: streak -> 1
    hits1 = await poller.sweep_once()
    assert hits1 == 0
    assert DB.meta_get("rl_streak") == "1"
    assert DB.meta_get("son_sweep") is None, "Hata aninda son_sweep guncellenmemeli"
    assert poller_notify.send.call_count == 0

    # 2. sweep: streak -> 2
    hits2 = await poller.sweep_once()
    assert hits2 == 0
    assert DB.meta_get("rl_streak") == "2"
    assert poller_notify.send.call_count == 0

    # 3. sweep: streak -> 3 (Telegram bildirimi tetiklenmeli)
    hits3 = await poller.sweep_once()
    assert hits3 == 0
    assert DB.meta_get("rl_streak") == "3"
    assert poller_notify.send.call_count == 1
    alert_text = poller_notify.send.call_args[0][0]
    assert "proxy şart" in alert_text
    print("[3] poller.sweep_once 3 pespese rate limit sonrasi Telegram uyarisi gonderdi -> BASARILI.")

    # 4. sweep: Basarili sweep gelince streak sifirlanmali
    poller_vfs.public_earliest = AsyncMock(return_value={"vacList": [], "lastUpdatedOn": "2026-10-28"})
    poller_vfs.parse_public = MagicMock(return_value=[])
    hits_ok = await poller.sweep_once()
    assert hits_ok == 0
    assert DB.meta_get("rl_streak") == "0"
    assert DB.meta_get("son_sweep") is not None
    print("[4] Basarili sweep sonrasinda rl_streak sifirlandi ve son_sweep guncellendi -> BASARILI.")

    print("\nGate G2 BUTUN TESTLER BASARIYLA GECILDI!")


if __name__ == "__main__":
    asyncio.run(main())
