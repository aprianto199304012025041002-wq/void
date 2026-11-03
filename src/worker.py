"""
Worker Engine — Daemon loop dengan Stateful Conversation Memory.
Menjalankan auto-looping 'lanjut' 24/7 di background thread.
Otomatis failover / rotasi node saat kena limit 429.
"""

import threading
import time
import queue
from typing import Optional, List, Dict

from src.pool import ClusterPool, KeyNode, STATUS_COOLDOWN, STATUS_ERROR
from src.client import get_ai_client, AIRateLimitError, AIAuthError

_pool: Optional[ClusterPool] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = threading.Event()
_daemon_lock = threading.Lock()

# Log queue untuk realtime terminal (max 500 baris)
log_queue: queue.Queue = queue.Queue(maxsize=500)

# Stateful Conversation Memory (Multi-turn chat context)
active_chat_thread: List[Dict[str, str]] = []
_thread_lock = threading.Lock()
MAX_HISTORY_TURNS = 40

# Cluster Worker Telemetry
stats = {
    "total_sent":    0,
    "total_success": 0,
    "total_failed":  0,
    "current_node":  None,
    "last_prompt":   "",
    "last_response": "",
    "daemon_active": False,
    "history_count": 0,
}
_stats_lock = threading.Lock()


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    try:
        log_queue.put_nowait(entry)
    except queue.Full:
        try:
            log_queue.get_nowait()
        except queue.Empty:
            pass
        log_queue.put_nowait(entry)


def get_logs(max_lines: int = 100) -> list:
    items = list(log_queue.queue)
    return items[-max_lines:]


def get_pool() -> ClusterPool:
    global _pool
    if _pool is None:
        _pool = ClusterPool()
    return _pool


def get_chat_history() -> List[Dict[str, str]]:
    with _thread_lock:
        return list(active_chat_thread)


def clear_chat_history():
    with _thread_lock:
        active_chat_thread.clear()
    with _stats_lock:
        stats["history_count"] = 0
    _log("🧹 Riwayat percakapan dibersihkan (New Session).")


def run_single_task(prompt: str = "lanjut", node_id: Optional[str] = None) -> dict:
    """
    Eksekusi 1 giliran chat dengan stateful history.
    """
    pool = get_pool()

    if node_id:
        node = pool.get_node_by_id(node_id)
        if not node:
            return {"success": False, "node_id": node_id, "response": "", "error": "Node ID tidak ditemukan"}
    else:
        node = pool.get_ready_node()
        if not node:
            return {
                "success": False,
                "node_id": None,
                "response": "",
                "error": f"Semua node sedang cooldown/belum ada API Key. Tunggu {pool.min_cooldown_remaining()}s",
            }

    node.mark_working()
    _log(f"📤 [{node.label}] ({node.provider.upper()}) Kirim: '{prompt[:60]}'")

    with _stats_lock:
        stats["current_node"] = node.label
        stats["last_prompt"]  = prompt
        stats["total_sent"]  += 1

    try:
        client = get_ai_client(node.provider, node.api_key, node.model)

        with _thread_lock:
            history_copy = list(active_chat_thread)

        # Kirim ke AI engine
        response = client.send_chat(history_copy, prompt)

        # Update riwayat obrolan (Stateful)
        with _thread_lock:
            active_chat_thread.append({"role": "user", "content": prompt})
            active_chat_thread.append({"role": "assistant", "content": response})
            # Pangkas jika melebihi batas turn
            if len(active_chat_thread) > MAX_HISTORY_TURNS * 2:
                del active_chat_thread[:2]

        node.total_sent += 1
        node.last_response = response
        node.mark_ready()

        _log(f"✅ [{node.label}] Respon ({len(response)} chars): {response[:120].strip()}...")

        with _stats_lock:
            stats["total_success"] += 1
            stats["last_response"]  = response
            stats["current_node"]   = None
            stats["history_count"]  = len(active_chat_thread) // 2

        return {"success": True, "node_id": node.id, "response": response, "error": ""}

    except AIRateLimitError as e:
        node.mark_cooldown(seconds=60) # Cooldown 60s untuk rotasi RPM/TPM
        _log(f"⏳ [{node.label}] Kena Rate Limit (429). Masuk cooldown 60s. Auto-failover...")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": f"Rate limit: {e}"}

    except AIAuthError as e:
        node.mark_error(str(e))
        _log(f"🔴 [{node.label}] Auth Error: {e}")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": f"Auth: {e}"}

    except Exception as e:
        node.mark_error(str(e))
        _log(f"❌ [{node.label}] Error: {e}")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": str(e)}


DEFAULT_INTERVAL_OK     = 60    # detik antar iterasi sukses
DEFAULT_INTERVAL_RETRY  = 10    # detik saat gagal sebelum retry


def _daemon_loop(prompt: str, interval_ok: int, interval_retry: int):
    _log("🚀 Daemon Auto-Looping diaktifkan")
    pool = get_pool()

    while _daemon_running.is_set():
        if pool.all_exhausted():
            wait = pool.min_cooldown_remaining()
            wait = max(wait, 15)
            _log(f"😴 Semua node cooldown. Menunggu {wait}s...")
            for _ in range(wait):
                if not _daemon_running.is_set():
                    break
                time.sleep(1)
            continue

        result = run_single_task(prompt=prompt)

        if result["success"]:
            _sleep_interruptible(interval_ok)
        else:
            _sleep_interruptible(interval_retry)

    _log("🛑 Daemon Auto-Looping dihentikan")
    with _stats_lock:
        stats["daemon_active"] = False


def _sleep_interruptible(seconds: int):
    for _ in range(seconds):
        if not _daemon_running.is_set():
            break
        time.sleep(1)


def start_daemon(prompt: str = "lanjut", interval_ok: int = DEFAULT_INTERVAL_OK):
    global _daemon_thread
    with _daemon_lock:
        if _daemon_running.is_set():
            _log("⚠️ Daemon sudah aktif.")
            return False

        _daemon_running.set()
        with _stats_lock:
            stats["daemon_active"] = True

        _daemon_thread = threading.Thread(
            target=_daemon_loop,
            args=(prompt, interval_ok, DEFAULT_INTERVAL_RETRY),
            daemon=True,
            name="ai-daemon-worker",
        )
        _daemon_thread.start()
        _log(f"▶️ Daemon started | prompt='{prompt}' | interval={interval_ok}s")
        return True


def stop_daemon():
    global _daemon_thread
    with _daemon_lock:
        if not _daemon_running.is_set():
            return False
        _daemon_running.clear()
        _log("⏹️ Mengirim sinyal stop ke daemon...")
        return True


def daemon_is_running() -> bool:
    return _daemon_running.is_set()


def get_stats() -> dict:
    with _stats_lock:
        return dict(stats)
