"""
Continuous Bug Hunter & Code Auditor Worker.
Fitur Unggulan:
- Persistent Disk Storage & Auto-Restore saat Reboot
- Auto-Sync ke GitHub Branch 'audit-reports' (Anti-Hilang Selamanya)
- Smart Bug Deduplication (Zero Spam Duplikat)
- Continuous Looping 24/7 di Cloud
"""

import os
import sys
import json
import hashlib
import threading
import time
import queue
from typing import Optional, List, Dict, Set

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from src.pool import ClusterPool, load_all_secrets
    from src.client import get_ai_client, AIRateLimitError, AIAuthError
    from src.github_scanner import GitHubRepoReader
    from src.github_sync import GitHubReportSyncer
except ImportError:
    from .pool import ClusterPool, load_all_secrets
    from .client import get_ai_client, AIRateLimitError, AIAuthError
    from .github_scanner import GitHubRepoReader
    from .github_sync import GitHubReportSyncer

REPORT_FILE_PATH = os.path.join(_ROOT, "bug_report.md")
HASHES_FILE_PATH = os.path.join(_ROOT, "known_bug_hashes.json")

_pool: Optional[ClusterPool] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = threading.Event()
_daemon_lock = threading.Lock()

log_queue: queue.Queue = queue.Queue(maxsize=500)

_report_lock = threading.Lock()
bug_reports_markdown: List[str] = []
seen_bug_hashes: Set[str] = set()

scanned_files_set: Set[str] = set()
files_queue: List[dict] = []

stats = {
    "total_files_scanned": 0,
    "total_bugs_found": 0,
    "current_file": "",
    "daemon_active": False,
    "target_repo": "",
    "last_bug_title": "",
    "duplicates_prevented": 0,
    "last_github_sync": "Never",
}
_stats_lock = threading.Lock()


def _get_write_token() -> str:
    sec = load_all_secrets()
    return sec.get("GITHUB_WRITE_PAT", sec.get("TARGET_GITHUB_PAT", sec.get("GITHUB_PAT", "")))


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


# ────────────────────────────────────────────────────────────────
# Persistence & Cloud Auto-Restore (Anti-Hilang saat Reboot)
# ────────────────────────────────────────────────────────────────
def _parse_raw_markdown_to_items(raw_content: str):
    global bug_reports_markdown, seen_bug_hashes
    if not raw_content:
        return
    parts = raw_content.split("\n\n---\n\n")
    items = [p.strip() for p in parts if p.strip().startswith("### 🐛")]
    bug_reports_markdown = items
    stats["total_bugs_found"] = len(items)

    for item in items:
        lines = [line.strip().lower() for line in item.split("\n") if line.strip()]
        heading = lines[0] if lines else ""
        file_line = next((l for l in lines if l.startswith("- **file:**")), "")
        sig = f"{file_line}::{heading}"
        fp = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
        seen_bug_hashes.add(fp)


def _load_persisted_data():
    """Memuat dari disk lokal atau fetch otomatis dari GitHub jika baru saja di-reboot."""
    global bug_reports_markdown, seen_bug_hashes
    loaded_local = False
    with _report_lock:
        if os.path.exists(REPORT_FILE_PATH):
            try:
                with open(REPORT_FILE_PATH, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content and "### 🐛" in content:
                        _parse_raw_markdown_to_items(content)
                        loaded_local = True
            except Exception:
                pass

        if not loaded_local:
            token = _get_write_token()
            if token:
                try:
                    syncer = GitHubReportSyncer(token)
                    cloud_content = syncer.fetch_latest_report()
                    if cloud_content and "### 🐛" in cloud_content:
                        _parse_raw_markdown_to_items(cloud_content)
                        with open(REPORT_FILE_PATH, "w", encoding="utf-8") as f:
                            f.write(cloud_content)
                        _log(f"☁️ [Auto-Restore] Berhasil memulihkan {len(bug_reports_markdown)} bug dari GitHub branch 'audit-reports'!")
                except Exception as e:
                    _log(f"⚠️ Gagal auto-restore dari GitHub: {e}")


def _async_sync_to_github(full_md: str):
    """Jalankan push ke GitHub branch 'audit-reports' di background thread."""
    def _worker():
        token = _get_write_token()
        if not token:
            return
        syncer = GitHubReportSyncer(token)
        ok, msg = syncer.push_report(full_md, commit_msg=f"🛡️ Auto-sync bug report ({stats.get('total_bugs_found', 0)} bugs) [skip ci]")
        if ok:
            ts = time.strftime("%H:%M:%S")
            with _stats_lock:
                stats["last_github_sync"] = ts
            _log(f"☁️ [Auto-Sync GitHub] Laporan berhasil disimpan permanen ke branch 'audit-reports' ({ts}).")
        else:
            _log(f"⚠️ [Sync GitHub Warning] {msg}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _save_persisted_data():
    with _report_lock:
        try:
            with open(HASHES_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(list(seen_bug_hashes), f)

            full_md = _build_markdown_document()
            with open(REPORT_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(full_md)

            _async_sync_to_github(full_md)
        except Exception as e:
            _log(f"⚠️ Gagal menyimpan data: {e}")


def _build_markdown_document() -> str:
    target = stats.get("target_repo", "Target Repo")
    header = f"# 🛡️ Continuous Code & Bug Audit Report\n\n"
    header += f"- **Target Repository:** `{target}`\n"
    header += f"- **Total Bug Unik Ditemukan:** `{len(bug_reports_markdown)}`\n"
    header += f"- **Duplikat Dicegah:** `{stats.get('duplicates_prevented', 0)}`\n"
    header += f"- **Status:** `Continuous Automated Looping`\n"
    header += f"- **GitHub Auto-Sync:** `Active (branch: audit-reports)`\n\n---\n\n"
    return header + "\n\n---\n\n".join(bug_reports_markdown)


_load_persisted_data()


def get_bug_report_markdown() -> str:
    with _report_lock:
        if not bug_reports_markdown:
            return "# 🛡️ Bug Hunting & Code Audit Report\n\n*Belum ada bug yang ditemukan atau pemindaian belum dimulai.*"
        return _build_markdown_document()


def clear_bug_reports():
    with _report_lock:
        bug_reports_markdown.clear()
        seen_bug_hashes.clear()
        scanned_files_set.clear()
        files_queue.clear()
        for p in [REPORT_FILE_PATH, HASHES_FILE_PATH]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    with _stats_lock:
        stats["total_files_scanned"] = 0
        stats["total_bugs_found"] = 0
        stats["last_bug_title"] = ""
        stats["duplicates_prevented"] = 0
    _log("🧹 Seluruh riwayat bug di RAM dan disk berhasil dibersihkan.")


# ────────────────────────────────────────────────────────────────
# Smart Fingerprinting & Deduplication
# ────────────────────────────────────────────────────────────────
def _compute_bug_fingerprint(file_path: str, response_text: str) -> str:
    lines = [line.strip().lower() for line in response_text.split("\n") if line.strip()]
    first_heading = lines[0] if lines else "unknown_issue"
    clean_title = "".join(c for c in first_heading if c.isalnum() or c in " _-")
    sig = f"{file_path}::{clean_title}"
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


def scan_single_file(file_info: dict, reader: GitHubRepoReader) -> dict:
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

        res_strip = response.strip()
        if "NO_BUG_DETECTED" in res_strip and len(res_strip) < 50:
            _log(f"✅ Clean: {file_path} (Tidak ada bug)")
            return {"success": True, "has_bug": False, "file": file_path}
        else:
            fp = _compute_bug_fingerprint(file_path, response)

            with _report_lock:
                if fp in seen_bug_hashes:
                    _log(f"ℹ️ [Deduplikasi] Bug di {file_path} sudah ada di log. Dilewati agar tidak duplikat.")
                    with _stats_lock:
                        stats["duplicates_prevented"] += 1
                    return {"success": True, "has_bug": True, "is_duplicate": True, "file": file_path}

                seen_bug_hashes.add(fp)
                bug_reports_markdown.append(response)

            _save_persisted_data()

            first_line = response.strip().split("\n")[0]
            _log(f"🚨 BUG BARU DICATAT: {first_line[:50]} ({file_path})")

            with _stats_lock:
                stats["total_bugs_found"] = len(bug_reports_markdown)
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
        if not files_queue:
            _log("🔄 Membaca pohon file terbaru dari repositori...")
            try:
                all_files = reader.get_repo_files()
                _log(f"📁 Ditemukan {len(all_files)} file kode yang dapat diaudit.")
                unscanned = [f for f in all_files if f["path"] not in scanned_files_set]
                if not unscanned:
                    _log("🔁 Seluruh file dalam siklus ini telah selesai diaudit. Mengulang siklus pemindaian...")
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

        scan_single_file(current_file, reader)
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
