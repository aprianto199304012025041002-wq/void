"""
Worker — daemon loop yang kirim 'lanjut' ke TAPIR conversation.
Thread-safe. Mendukung mode claude_web (session key) dan anthropic (legacy).
"""

import threading
import time
import queue
from typing import Optional, Callable

from src.pool import ClusterPool, AccountNode, STATUS_COOLDOWN, STATUS_ERROR
from src.client import ClaudeWebSessionClient, ClaudeRateLimitError, ClaudeAuthError

# ---------------------------------------------------------------
# Shared state (diakses dari UI thread maupun worker thread)
# ---------------------------------------------------------------

_pool: Optional[ClusterPool] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = threading.Event()
_daemon_lock = threading.Lock()

# Queue untuk log feed (max 500 baris)
log_queue: queue.Queue = queue.Queue(maxsize=500)

# Stats
stats = {
    "total_sent":    0,
    "total_success": 0,
    "total_failed":  0,
    "current_node":  None,
    "last_prompt":   "",
    "last_response": "",
    "daemon_active": False,
}
_stats_lock = threading.Lock()


def _log(msg: str):
    """Tambah ke log queue, drop yang paling lama kalau penuh."""
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
    """Ambil log terbaru tanpa menghapus dari queue."""
    items = list(log_queue.queue)
    return items[-max_lines:]


def get_pool() -> ClusterPool:
    global _pool
    if _pool is None:
        _pool = ClusterPool()
    return _pool


# ---------------------------------------------------------------
# Single task
# ---------------------------------------------------------------

def run_single_task(prompt: str = "lanjut", node_id: Optional[str] = None) -> dict:
    """
    Kirim satu prompt ke TAPIR. 
    Return dict: {success, node_id, response, error}
    """
    pool = get_pool()

    if node_id:
        node = pool.get_node_by_id(node_id)
        if node is None:
            return {"success": False, "node_id": node_id, "response": "", "error": "Node tidak ditemukan"}
    else:
        node = pool.get_ready_node()
        if node is None:
            return {
                "success": False,
                "node_id": None,
                "response": "",
                "error": f"Semua akun cooldown/error. Tunggu {pool.min_cooldown_remaining()}s",
            }

    node.mark_working()
    _log(f"📤 [{node.label}] Kirim: '{prompt[:50]}'")

    with _stats_lock:
        stats["current_node"] = node.label
        stats["last_prompt"]  = prompt
        stats["total_sent"]  += 1

    try:
        client = ClaudeWebSessionClient(
            session_key=node.session_key,
            conv_id=node.conv_id,
            org_id=node.org_id,
        )

        response = client.send_message(prompt)

        # Cache org_id supaya tidak re-fetch
        if client._org_id and not node.org_id:
            node.org_id = client._org_id

        node.total_sent += 1
        node.last_response = response
        node.mark_ready()

        _log(f"✅ [{node.label}] Respon ({len(response)} chars): {response[:100]}...")

        with _stats_lock:
            stats["total_success"] += 1
            stats["last_response"]  = response
            stats["current_node"]   = None

        return {"success": True, "node_id": node.id, "response": response, "error": ""}

    except ClaudeRateLimitError as e:
        node.mark_cooldown()
        _log(f"⏳ [{node.label}] Rate limit kena — cooldown 5 jam. {e}")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": f"Rate limit: {e}"}

    except ClaudeAuthError as e:
        node.mark_error(str(e))
        _log(f"🔴 [{node.label}] Auth error: {e}")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": f"Auth: {e}"}

    except Exception as e:
        node.mark_error(str(e))
        _log(f"❌ [{node.label}] Unexpected error: {e}")
        with _stats_lock:
            stats["total_failed"] += 1
            stats["current_node"]  = None
        return {"success": False, "node_id": node.id, "response": "", "error": str(e)}


# ---------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------

DEFAULT_INTERVAL_OK      = 90    # detik antar kirim saat normal
DEFAULT_INTERVAL_FAILED  = 30    # detik retry setelah error non-limit
DEFAULT_INTERVAL_EXHAUST = 300   # detik tunggu saat semua akun habis


def _daemon_loop(prompt: str, interval_ok: int, interval_failed: int):
    """Loop utama daemon — jalan di background thread."""
    _log("🚀 Daemon dimulai")
    pool = get_pool()

    while _daemon_running.is_set():
        if pool.all_exhausted():
            wait = pool.min_cooldown_remaining()
            wait = wait if wait > 0 else DEFAULT_INTERVAL_EXHAUST
            _log(f"😴 Semua akun exhausted. Tunggu {wait}s...")
            # Tunggu sambil cek stop setiap 10 detik
            for _ in range(wait // 10 + 1):
                if not _daemon_running.is_set():
                    break
                time.sleep(min(10, wait))
            continue

        result = run_single_task(prompt=prompt)

        if result["success"]:
            _sleep_interruptible(interval_ok)
        else:
            err = result.get("error", "")
            if "rate limit" in err.lower() or "cooldown" in err.lower():
                # Langsung coba akun lain tanpa tunggu lama
                time.sleep(2)
            else:
                _sleep_interruptible(interval_failed)

    _log("🛑 Daemon berhenti")
    with _stats_lock:
        stats["daemon_active"] = False


def _sleep_interruptible(seconds: int):
    """Sleep yang bisa diinterupsi saat daemon diminta stop."""
    for _ in range(seconds):
        if not _daemon_running.is_set():
            break
        time.sleep(1)


def start_daemon(prompt: str = "lanjut", interval_ok: int = DEFAULT_INTERVAL_OK):
    """Mulai daemon loop di background thread."""
    global _daemon_thread
    with _daemon_lock:
        if _daemon_running.is_set():
            _log("⚠️  Daemon sudah berjalan")
            return False

        _daemon_running.set()
        with _stats_lock:
            stats["daemon_active"] = True

        _daemon_thread = threading.Thread(
            target=_daemon_loop,
            args=(prompt, interval_ok, DEFAULT_INTERVAL_FAILED),
            daemon=True,
            name="claude-daemon",
        )
        _daemon_thread.start()
        _log(f"▶️  Daemon started | prompt='{prompt}' | interval={interval_ok}s")
        return True


def stop_daemon():
    """Hentikan daemon loop."""
    global _daemon_thread
    with _daemon_lock:
        if not _daemon_running.is_set():
            _log("⚠️  Daemon tidak sedang berjalan")
            return False

        _daemon_running.clear()
        _log("⏹️  Stop signal dikirim ke daemon...")
        return True


def daemon_is_running() -> bool:
    return _daemon_running.is_set()


def get_stats() -> dict:
    with _stats_lock:
        return dict(stats)
