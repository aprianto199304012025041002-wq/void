"""
Continuous Bug Hunter & Code Auditor Worker.
Memindai repositori GitHub secara terus-menerus, menganalisis kode menggunakan AI,
dan mencatat semua bug yang ditemukan secara mendalam ke dalam file Markdown (bug_report.md).
"""

import os
import sys
import threading
import time
import queue
from typing import Optional, List, Dict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from src.pool import ClusterPool, load_all_secrets
    from src.client import get_ai_client, AIRateLimitError, AIAuthError
    from src.github_scanner import GitHubRepoReader
except ImportError:
    from .pool import ClusterPool, load_all_secrets
    from .client import get_ai_client, AIRateLimitError, AIAuthError
    from .github_scanner import GitHubRepoReader

_pool: Optional[ClusterPool] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = threading.Event()
_daemon_lock = threading.Lock()

# Log queue untuk realtime console stream
log_queue: queue.Queue = queue.Queue(maxsize=500)

# Markdown Bug Report Storage
_report_lock = threading.Lock()
bug_reports_markdown: List[str] = []

# Scanned files tracker
scanned_files_set = set()
files_queue: List[dict] = []

stats = {
    "total_files_scanned": 0,
    "total_bugs_found": 0,
    "current_file": "",
    "daemon_active": False,
    "target_repo": "",
    "last_bug_title": "",
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


def get_bug_report_markdown() -> str:
    """Mengembalikan keseluruhan laporan bug dalam format Markdown murni."""
    with _report_lock:
        if not bug_reports_markdown:
            return "# 🛡️ Bug Hunting & Code Audit Report\n\n*Belum ada bug yang ditemukan atau pemindaian belum dimulai.*"
        
        target = stats.get("target_repo", "Unknown Repo")
        header = f"# 🛡️ Continuous Code & Bug Audit Report\n\n"
        header += f"- **Target Repository:** `{target}`\n"
        header += f"- **Total Bug Ditemukan:** `{len(bug_reports_markdown)}`\n"
        header += f"- **Total File Diperiksa:** `{stats.get('total_files_scanned', 0)}`\n"
        header += f"- **Status:** `Continuous Auditing Active`\n\n---\n\n"
        
        return header + "\n\n---\n\n".join(bug_reports_markdown)


def clear_bug_reports():
    with _report_lock:
        bug_reports_markdown.clear()
        scanned_files_set.clear()
        files_queue.clear()
    with _stats_lock:
        stats["total_files_scanned"] = 0
        stats["total_bugs_found"] = 0
        stats["last_bug_title"] = ""
    _log("🧹 Laporan bug dan riwayat scan berhasil di-reset.")


def scan_single_file(file_info: dict, reader: GitHubRepoReader) -> dict:
    """Memindai satu file menggunakan model AI."""
    pool = get_pool()
    node = pool.get_ready_node()
    if not node:
        return {"success": False, "error": f"Semua node AI cooldown. Tunggu {pool.min_cooldown_remaining()}s"}

    file_path = file_info["path"]
    with _stats_lock:
        stats["current_file"] = file_path

    _log(f"🔍 [{node.label}] Mengaudit file: {file_path} ({file_info.get('size', 0):,} bytes)")

    content = reader.get_file_content(file_path)
    if not content:
        _log(f"⚠️ Gagal membaca konten file: {file_path}")
        return {"success": False, "error": "Gagal membaca isi file"}

    # Susun prompt analisis kode & bug hunting
    ext = file_path.split(".")[-1] if "." in file_path else "text"
    prompt = f"""Anda adalah Senior Security & Code Quality Auditor.
Tugas Anda adalah memeriksa file kode berikut dari repositori GitHub untuk mendeteksi BUG, LOGIC ERROR, UNHANDLED EXCEPTIONS, RESOURCE LEAK, atau VULNERABILITY.

File: `{file_path}`
Kode:
```{ext}
{content[:15000]}
```

ATURAN RESPON:
1. Jika file bersih dan TIDAK ada bug/isu signifikan: BALAS HANYA DENGAN SATU KATA: "NO_BUG_DETECTED".
2. Jika DITEMUKAN bug/isu nyata, buat laporan Markdown terstruktur rapi:
### 🐛 [Severity: HIGH/MEDIUM/LOW] <Judul Singkat Bug>
- **File:** `{file_path}`
- **Lokasi Kode / Masalah:** <Tunjukkan baris/fungsi yang bermasalah>
- **Penyebab & Analisis:** <Jelaskan mengapa ini bug/berbahaya>
- **Rekomendasi Perbaikan Defensif:** <Berikan solusi kode perbaikan/patch yang aman>
"""

    node.mark_working()
    try:
        client = get_ai_client(node.provider, node.api_key, node.model)
        response = client.send_chat([], prompt)

        node.total_sent += 1
        node.mark_ready()

        with _stats_lock:
            stats["total_files_scanned"] += 1

        # Analisis hasil respon
        res_strip = response.strip()
        if "NO_BUG_DETECTED" in res_strip and len(res_strip) < 50:
            _log(f"✅ Clean: {file_path} (Tidak ada bug ditemukan)")
            return {"success": True, "has_bug": False, "file": file_path}
        else:
            # Bug ditemukan!
            _log(f"🚨 BUG DITEMUKAN di: {file_path}!")
            with _report_lock:
                bug_reports_markdown.append(response)
            with _stats_lock:
                stats["total_bugs_found"] += 1
                first_line = response.strip().split("\n")[0]
                stats["last_bug_title"] = first_line[:50]
            return {"success": True, "has_bug": True, "file": file_path, "report": response}

    except AIRateLimitError as e:
        node.mark_cooldown(60)
        _log(f"⏳ [{node.label}] AI Rate Limit (429). Rotasi node berikutnya...")
        return {"success": False, "error": str(e)}
    except AIAuthError as e:
        node.mark_error(str(e))
        _log(f"🔴 [{node.label}] Auth Error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        node.mark_error(str(e))
        _log(f"❌ [{node.label}] Error audit: {e}")
        return {"success": False, "error": str(e)}


def _daemon_audit_loop(repo_full_name: str, pat_token: str, interval_sec: int):
    """Loop pemindaian kontinu 24/7."""
    _log(f"🚀 Memulai Continuous Bug Hunter pada target: {repo_full_name}")
    reader = GitHubRepoReader(repo_full_name, pat_token)

    ok, msg = reader.test_access()
    if not ok:
        _log(f"❌ {msg}")
        with _stats_lock:
            stats["daemon_active"] = False
        return

    _log(f"✅ Koneksi repo terverifikasi: {repo_full_name}")

    while _daemon_running.is_set():
        # Ambil daftar file jika antrean kosong
        if not files_queue:
            _log("🔄 Mengambil daftar file terbaru dari repositori...")
            try:
                all_files = reader.get_repo_files()
                _log(f"📁 Ditemukan {len(all_files)} file kode yang dapat diaudit.")
                # Filter file yang belum pernah diaudit di sesi ini
                unscanned = [f for f in all_files if f["path"] not in scanned_files_set]
                if not unscanned:
                    _log("🔁 Semua file sudah diaudit. Mengulang siklus pemindaian berkala...")
                    scanned_files_set.clear()
                    unscanned = all_files
                files_queue.extend(unscanned)
            except Exception as e:
                _log(f"⚠️ Gagal membaca tree repo: {e}. Menunggu 30s...")
                _sleep_interruptible(30)
                continue

        if not files_queue:
            _sleep_interruptible(15)
            continue

        current_file = files_queue.pop(0)
        scanned_files_set.add(current_file["path"])

        res = scan_single_file(current_file, reader)

        # Jeda waktu antar audit file
        _sleep_interruptible(interval_sec)

    _log("🛑 Continuous Bug Hunter dihentikan.")
    with _stats_lock:
        stats["daemon_active"] = False


def _sleep_interruptible(seconds: int):
    for _ in range(seconds):
        if not _daemon_running.is_set():
            break
        time.sleep(1)


def start_bug_hunter(repo_full_name: str, pat_token: str = "", interval_sec: int = 15):
    global _daemon_thread
    with _daemon_lock:
        if _daemon_running.is_set():
            return False

        _daemon_running.set()
        with _stats_lock:
            stats["daemon_active"] = True
            stats["target_repo"] = repo_full_name

        _daemon_thread = threading.Thread(
            target=_daemon_audit_loop,
            args=(repo_full_name, pat_token, interval_sec),
            daemon=True,
            name="bug-hunter-daemon",
        )
        _daemon_thread.start()
        return True


def stop_bug_hunter():
    global _daemon_thread
    with _daemon_lock:
        if not _daemon_running.is_set():
            return False
        _daemon_running.clear()
        _log("⏹️ Mengirim sinyal stop ke Bug Hunter...")
        return True


def is_bug_hunter_running() -> bool:
    return _daemon_running.is_set()


def get_stats() -> dict:
    with _stats_lock:
        return dict(stats)
