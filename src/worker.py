"""
Continuous Bug Hunter & Code Auditor Worker — Multi-Repo Edition.
Mendukung:
- Audit 1 repo spesifik maupun rotasi otomatis multi-repo (misal 3 repo sekaligus)
- File laporan terpisah per repositori (reports/<repo_name>_bug_report.md)
- Auto-Restore spesifik per repositori dari GitHub saat reboot
- Smart Deduplication per repositori
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
    from src.github_sync import GitHubReportSyncer, get_safe_report_path
except ImportError:
    from .pool import ClusterPool, load_all_secrets
    from .client import get_ai_client, AIRateLimitError, AIAuthError
    from .github_scanner import GitHubRepoReader
    from .github_sync import GitHubReportSyncer, get_safe_report_path

REPORTS_DIR = os.path.join(_ROOT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

_pool: Optional[ClusterPool] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_running = threading.Event()
_daemon_lock = threading.Lock()

log_queue: queue.Queue = queue.Queue(maxsize=500)

_report_lock = threading.Lock()
repo_reports: Dict[str, List[str]] = {}
repo_hashes: Dict[str, Set[str]] = {}

scanned_files_set: Set[str] = set()
files_queue: List[dict] = []

stats = {
    "total_files_scanned": 0,
    "total_bugs_found": 0,
    "current_repo": "",
    "current_file": "",
    "daemon_active": False,
    "target_repos": [],
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
# Multi-Repo Isolated Persistence & Auto-Restore
# ────────────────────────────────────────────────────────────────
def _local_report_path(repo_name: str) -> str:
    clean = repo_name.strip().strip("/").replace("/", "_").replace(" ", "_")
    return os.path.join(REPORTS_DIR, f"{clean}_bug_report.md")


def _local_hashes_path(repo_name: str) -> str:
    clean = repo_name.strip().strip("/").replace("/", "_").replace(" ", "_")
    return os.path.join(REPORTS_DIR, f"{clean}_hashes.json")


def ensure_repo_loaded(repo_name: str):
    with _report_lock:
        if repo_name in repo_reports and repo_reports[repo_name]:
            return

        repo_reports[repo_name] = []
        repo_hashes[repo_name] = set()

        lpath = _local_report_path(repo_name)
        hpath = _local_hashes_path(repo_name)

        loaded = False
        if os.path.exists(lpath):
            try:
                with open(lpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content and "### 🐛" in content:
                        parts = content.split("\n\n---\n\n")
                        items = [p.strip() for p in parts if p.strip().startswith("### 🐛")]
                        repo_reports[repo_name] = items
                        loaded = True
            except Exception:
                pass

        if os.path.exists(hpath):
            try:
                with open(hpath, "r", encoding="utf-8") as f:
                    repo_hashes[repo_name] = set(json.load(f))
            except Exception:
                pass

        # Auto-Restore spesifik untuk repo ini jika di disk kosong
        if not loaded:
            token = _get_write_token()
            if token:
                try:
                    syncer = GitHubReportSyncer(token)
                    cloud_content = syncer.fetch_report(repo_name)
                    if cloud_content and "### 🐛" in cloud_content:
                        parts = cloud_content.split("\n\n---\n\n")
                        items = [p.strip() for p in parts if p.strip().startswith("### 🐛")]
                        repo_reports[repo_name] = items
                        with open(lpath, "w", encoding="utf-8") as f:
                            f.write(cloud_content)
                        _log(f"☁️ [Auto-Restore] Memulihkan {len(items)} bug untuk '{repo_name}' dari GitHub branch 'audit-reports'!")
                except Exception as e:
                    _log(f"⚠️ Gagal restore laporan '{repo_name}': {e}")


def _build_markdown_for_repo(repo_name: str) -> str:
    items = repo_reports.get(repo_name, [])
    header = f"# 🛡️ Bug Audit Report — `{repo_name}`\n\n"
    header += f"- **Target Repository:** `{repo_name}`\n"
    header += f"- **Total Bug Unik:** `{len(items)}`\n"
    header += f"- **Storage Path:** `{get_safe_report_path(repo_name)}`\n"
    header += f"- **Status:** `Continuous Automated Looping`\n\n---\n\n"
    if not items:
        return header + "*Belum ada bug yang ditemukan pada repositori ini.*"
    return header + "\n\n---\n\n".join(items)


def _async_sync_repo_to_github(repo_name: str, full_md: str):
    def _worker():
        token = _get_write_token()
        if not token:
            return
        syncer = GitHubReportSyncer(token)
        ok, msg = syncer.push_report(repo_name, full_md)
        if ok:
            ts = time.strftime("%H:%M:%S")
            with _stats_lock:
                stats["last_github_sync"] = ts
            _log(f"☁️ [Auto-Sync GitHub] Laporan '{repo_name}' tersimpan di branch 'audit-reports' ({ts}).")
        else:
            _log(f"⚠️ [Sync GitHub Warning] {msg}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def get_available_repos_with_reports() -> List[str]:
    with _report_lock:
        return list(repo_reports.keys())


def get_bug_report_markdown(target_repo: Optional[str] = None) -> str:
    with _report_lock:
        repo = target_repo or stats.get("current_repo")
        if not repo:
            if repo_reports:
                repo = list(repo_reports.keys())[0]
            else:
                return "# 🛡️ Bug Hunting & Code Audit Report\n\n*Belum ada repositori yang diaudit.*"
        
        ensure_repo_loaded(repo)
        return _build_markdown_for_repo(repo)


def clear_bug_reports(target_repo: Optional[str] = None):
    with _report_lock:
        repos_to_clear = [target_repo] if target_repo else list(repo_reports.keys())
        for r in repos_to_clear:
            if r in repo_reports:
                repo_reports[r].clear()
            if r in repo_hashes:
                repo_hashes[r].clear()
            lp = _local_report_path(r)
            hp = _local_hashes_path(r)
            for p in [lp, hp]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        scanned_files_set.clear()
        files_queue.clear()

    with _stats_lock:
        stats["total_files_scanned"] = 0
        stats["total_bugs_found"] = 0
        stats["last_bug_title"] = ""
        stats["duplicates_prevented"] = 0
    _log(f"🧹 Riwayat bug untuk {repos_to_clear} berhasil dibersihkan.")


# ────────────────────────────────────────────────────────────────
# Smart Fingerprinting & Scan Execution
# ────────────────────────────────────────────────────────────────
def _compute_bug_fingerprint(file_path: str, response_text: str) -> str:
    lines = [line.strip().lower() for line in response_text.split("\n") if line.strip()]
    first_heading = lines[0] if lines else "unknown_issue"
    clean_title = "".join(c for c in first_heading if c.isalnum() or c in " _-")
    sig = f"{file_path}::{clean_title}"
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


def scan_single_file(repo_name: str, file_info: dict, reader: GitHubRepoReader) -> dict:
    ensure_repo_loaded(repo_name)

    pool = get_pool()
    node = pool.get_ready_node()
    if not node:
        return {"success": False, "error": f"Semua node AI cooldown. Tunggu {pool.min_cooldown_remaining()}s"}

    file_path = file_info["path"]
    with _stats_lock:
        stats["current_repo"] = repo_name
        stats["current_file"] = file_path

    _log(f"🔍 [{node.label}] [{repo_name}] Mengaudit: {file_path} ({file_info.get('size', 0):,} bytes)")

    content = reader.get_file_content(file_path)
    if not content:
        _log(f"⚠️ Gagal membaca konten file: {file_path}")
        return {"success": False, "error": "Gagal membaca isi file"}

    ext = file_path.split(".")[-1] if "." in file_path else "text"
    prompt = f"""Anda adalah Senior Security & Code Quality Auditor.
Tugas Anda adalah memeriksa file kode berikut dari repositori '{repo_name}' untuk mendeteksi BUG, LOGIC ERROR, UNHANDLED EXCEPTIONS, RESOURCE LEAK, atau VULNERABILITY.

File: `{file_path}`
Kode:
```{ext}
{content[:15000]}
```

ATURAN RESPON:
1. Jika file bersih dan TIDAK ada bug/isu signifikan: BALAS HANYA DENGAN SATU KATA: "NO_BUG_DETECTED".
2. Jika DITEMUKAN bug/isu nyata, buat laporan Markdown terstruktur rapi:
### 🐛 [Severity: HIGH/MEDIUM/LOW] <Judul Singkat Bug>
- **Repository:** `{repo_name}`
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
                hashes = repo_hashes.setdefault(repo_name, set())
                reports = repo_reports.setdefault(repo_name, [])

                if fp in hashes:
                    _log(f"ℹ️ [Deduplikasi] Bug di {file_path} ({repo_name}) sudah ada di log. Dilewati.")
                    with _stats_lock:
                        stats["duplicates_prevented"] += 1
                    return {"success": True, "has_bug": True, "is_duplicate": True, "file": file_path}

                hashes.add(fp)
                reports.append(response)

                try:
                    with open(_local_hashes_path(repo_name), "w", encoding="utf-8") as f:
                        json.dump(list(hashes), f)
                    full_md = _build_markdown_for_repo(repo_name)
                    with open(_local_report_path(repo_name), "w", encoding="utf-8") as f:
                        f.write(full_md)
                except Exception as e:
                    _log(f"⚠️ Gagal save lokal: {e}")

            _async_sync_repo_to_github(repo_name, full_md)

            first_line = response.strip().split("\n")[0]
            _log(f"🚨 BUG BARU DICATAT: {first_line[:40]} [{repo_name} -> {file_path}]")

            with _stats_lock:
                stats["total_bugs_found"] = sum(len(v) for v in repo_reports.values())
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


# ────────────────────────────────────────────────────────────────
# Multi-Repo Daemon Loop
# ────────────────────────────────────────────────────────────────
def _daemon_audit_loop(repos_list: List[str], pat_token: str, interval_sec: int):
    _log(f"🚀 Memulai Continuous Bug Hunter pada {len(repos_list)} target repositori: {repos_list}")

    readers = {}
    valid_repos = []
    for r in repos_list:
        reader = GitHubRepoReader(r, pat_token)
        ok, msg = reader.test_access()
        if ok:
            readers[r] = reader
            valid_repos.append(r)
            ensure_repo_loaded(r)
            _log(f"✅ Target terverifikasi: {r}")
        else:
            _log(f"⚠️ Melewati {r}: {msg}")

    if not valid_repos:
        _log("❌ Tidak ada repositori yang dapat diakses.")
        with _stats_lock:
            stats["daemon_active"] = False
        return

    repo_index = 0

    while _daemon_running.is_set():
        current_repo_name = valid_repos[repo_index % len(valid_repos)]
        current_reader = readers[current_repo_name]

        with _stats_lock:
            stats["current_repo"] = current_repo_name

        _log(f"📂 [Target: {current_repo_name}] Membaca daftar file...")
        try:
            repo_files = current_reader.get_repo_files()
            _log(f"📁 [{current_repo_name}] Ditemukan {len(repo_files)} file kode.")
        except Exception as e:
            _log(f"⚠️ Gagal membaca {current_repo_name}: {e}. Berlanjut ke target berikutnya...")
            repo_index += 1
            _sleep_interruptible(10)
            continue

        for f_info in repo_files:
            if not _daemon_running.is_set():
                break

            scan_single_file(current_repo_name, f_info, current_reader)
            _sleep_interruptible(interval_sec)

        _log(f"🔁 [{current_repo_name}] Siklus audit selesai. Beralih ke repositori berikutnya...")
        repo_index += 1
        _sleep_interruptible(5)

    _log("🛑 Continuous Bug Hunter dihentikan.")
    with _stats_lock:
        stats["daemon_active"] = False


def _sleep_interruptible(seconds: int):
    for _ in range(seconds):
        if not _daemon_running.is_set():
            break
        time.sleep(1)


def start_bug_hunter(repos_input: str, pat_token: str = "", interval_sec: int = 15):
    global _daemon_thread
    with _daemon_lock:
        if _daemon_running.is_set():
            return False

        raw_list = [r.strip() for r in repos_input.split(",") if r.strip()]
        if not raw_list:
            return False

        _daemon_running.set()
        with _stats_lock:
            stats["daemon_active"] = True
            stats["target_repos"] = raw_list
            stats["current_repo"] = raw_list[0]

        _daemon_thread = threading.Thread(
            target=_daemon_audit_loop,
            args=(raw_list, pat_token, interval_sec),
            daemon=True,
            name="multi-repo-bug-hunter",
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
