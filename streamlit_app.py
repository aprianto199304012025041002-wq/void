"""
Claude Multi-Account Orchestrator — Streamlit Web UI
Pantau dan kendalikan dari browser, dari mana saja.
"""

import streamlit as st
import threading
import contextlib
import time
import os
import sys
import json
import io
from datetime import datetime
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from account_manager import AccountManager
from claude_worker import ClaudeWorker, ClaudeRateLimitError, ClaudeAuthError
from git_integration import GitManager

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claude Orchestrator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Dark log terminal */
.log-terminal {
    background: #0d1117;
    color: #58a6ff;
    padding: 14px 16px;
    border-radius: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.6;
    max-height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    border: 1px solid #30363d;
}
/* Account card badges */
.badge-ready  { color: #22c55e; font-weight: 700; font-size: 14px; }
.badge-limit  { color: #ef4444; font-weight: 700; font-size: 14px; }
/* Subtle dividers */
hr { border-color: #30363d !important; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
def _init():
    defaults: dict = {
        # Single task
        "task_running": False,
        "task_logs": [],
        "task_result": None,
        "task_error": None,
        "task_thread": None,
        "_task_result_holder": {},
        # Auto runner
        "auto_running": False,
        "auto_logs": [],
        "auto_iteration": 0,
        "auto_max": 100,
        "auto_thread": None,
        "auto_stop_event": threading.Event(),
        "_auto_iter_ref": [0],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ──────────────────────────────────────────────────────────────────────────────
# LOGGER UTILITY
# ──────────────────────────────────────────────────────────────────────────────
class _ListWriter:
    """Redirect print() to a shared list, safely from any thread."""
    def __init__(self, log_list: list):
        self._list = log_list

    def write(self, text: str):
        stripped = text.rstrip()
        if stripped:
            ts = datetime.now().strftime("%H:%M:%S")
            self._list.append(f"[{ts}] {stripped}")

    def flush(self):
        pass


# ──────────────────────────────────────────────────────────────────────────────
# BACKGROUND TASK: SINGLE TASK
# ──────────────────────────────────────────────────────────────────────────────
def _bg_single_task(task_text: str, include_git: bool, headless: bool,
                    logs: list, result: dict):
    writer = _ListWriter(logs)
    with contextlib.redirect_stdout(writer):
        try:
            acc_mgr = AccountManager(BASE_DIR)
            config = acc_mgr.config.copy()
            config["headless"] = headless

            # Build prompt
            prompt = task_text
            if include_git:
                git = GitManager(config.get("repo_path", ""), config.get("github_pat", ""))
                if git.is_valid_repo():
                    tree = git.get_repo_structure()
                    prompt = (
                        "Berikut adalah struktur file dalam repository GitHub saat ini:\n"
                        f"```\n{tree}\n```\n\n"
                        f"Instruksi tugas pengembangan aplikasi:\n{task_text}"
                    )

            max_attempts = len(config.get("accounts", []))
            attempts = 0

            while attempts < max_attempts:
                account = acc_mgr.get_available_account()
                if not account:
                    logs.append("⚠️  Semua akun sedang cooldown 5 jam!")
                    result["error"] = "Semua akun cooldown"
                    return

                print(f"🚀  Mengirim ke: {account['name']} (ID:{account['id']}) ...")
                worker = ClaudeWorker(
                    account_config=account,
                    base_dir=BASE_DIR,
                    headless=config["headless"],
                )
                try:
                    response = worker.send_prompt(prompt)
                    acc_mgr.record_task_success(account["id"])

                    # Save to outputs/
                    out_dir = os.path.join(BASE_DIR, "outputs")
                    os.makedirs(out_dir, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_file = os.path.join(out_dir, f"task_{ts}.md")
                    with open(out_file, "w", encoding="utf-8") as f:
                        f.write(
                            f"# Task Prompt:\n{task_text}\n\n---\n"
                            f"# Claude Response ({account['name']}):\n{response}\n"
                        )
                    print(f"✅  Respons diterima! Disimpan → {os.path.basename(out_file)}")
                    result["response"] = response
                    result["account"] = account["name"]
                    result["file"] = out_file
                    return

                except ClaudeRateLimitError as e:
                    print(f"⏳  {account['name']} rate-limited. Failover ...")
                    acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
                    attempts += 1
                except ClaudeAuthError as e:
                    print(f"🔐  Auth error [{account['name']}]: {e}")
                    attempts += 1
                except Exception as e:
                    print(f"❌  Error [{account['name']}]: {e}")
                    attempts += 1

            result["error"] = "Semua akun gagal menjalankan task."
            print("❌  Tidak ada akun yang berhasil.")

        except Exception as exc:
            result["error"] = str(exc)
            logs.append(f"❌  Fatal error: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# BACKGROUND TASK: AUTO RUNNER LOOP
# ──────────────────────────────────────────────────────────────────────────────
def _bg_auto_runner(max_iter: int, prompt_text: str, headless: bool,
                    stop_event: threading.Event, logs: list, iter_ref: list):
    writer = _ListWriter(logs)
    with contextlib.redirect_stdout(writer):
        try:
            acc_mgr = AccountManager(BASE_DIR)
            config = acc_mgr.config.copy()
            config["headless"] = headless

            print(f"🔄  Auto-runner dimulai. Max iterasi: {max_iter}")
            print(f"📝  Prompt: '{prompt_text}'")
            print("─" * 55)

            for i in range(1, max_iter + 1):
                if stop_event.is_set():
                    print("🛑  Dihentikan oleh user.")
                    break

                iter_ref[0] = i
                print(f"\n>>> ITERASI #{i} / {max_iter}  ({datetime.now().strftime('%H:%M:%S')})")

                account = acc_mgr.get_available_account()
                if not account:
                    # All cooling — find shortest wait
                    now = time.time()
                    avails = [
                        v.get("available_at", now)
                        for v in acc_mgr.state["accounts"].values()
                        if v.get("available_at", 0) > now
                    ]
                    wait_sec = max(60, int(min(avails) - now) if avails else 3600)
                    wait_min = wait_sec // 60
                    print(f"💤  Semua akun cooldown. Akun tercepat ~{wait_min} menit lagi.")
                    print(f"    Tidur 60 detik lalu cek ulang ...")
                    for _ in range(60):
                        if stop_event.is_set():
                            break
                        time.sleep(1)
                    continue

                print(f"    Akun  : {account['name']}")
                worker = ClaudeWorker(
                    account_config=account,
                    base_dir=BASE_DIR,
                    headless=config["headless"],
                )
                try:
                    response = worker.send_prompt(prompt_text)
                    acc_mgr.record_task_success(account["id"])

                    out_dir = os.path.join(BASE_DIR, "outputs")
                    os.makedirs(out_dir, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_file = os.path.join(out_dir, f"auto_{ts}.md")
                    with open(out_file, "w", encoding="utf-8") as f:
                        f.write(
                            f"# Auto-Run Iterasi #{i}\n"
                            f"Prompt: `{prompt_text}`\n\n---\n"
                            f"# Response ({account['name']}):\n{response}\n"
                        )
                    print(f"✅  Selesai ({len(response):,} karakter) → {os.path.basename(out_file)}")

                    # Check done signals
                    resp_lower = response.lower()
                    done_signals = [
                        "seluruh audit selesai", "semua perbandingan selesai",
                        "pekerjaan sudah selesai", "tidak ada lagi perbedaan",
                        "all tasks completed", "work is complete",
                    ]
                    if any(s in resp_lower for s in done_signals):
                        print("\n🎉  Claude menandakan pekerjaan SELESAI TOTAL!")
                        break

                except ClaudeRateLimitError as e:
                    print(f"⏳  Rate limit [{account['name']}]. Failover ...")
                    acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
                except ClaudeAuthError as e:
                    print(f"🔐  Auth error: {e}")
                except Exception as e:
                    print(f"❌  Error: {e}")

                # Jeda antar iterasi
                if not stop_event.is_set():
                    print(f"    Jeda 5 detik ...")
                    for _ in range(5):
                        if stop_event.is_set():
                            break
                        time.sleep(1)

            print("\n🏁  Auto-runner selesai.")

        except Exception as exc:
            logs.append(f"❌  Fatal error di auto-runner: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# HELPER: render log list as terminal block
# ──────────────────────────────────────────────────────────────────────────────
def _render_log(log_list: list, max_lines: int = 80):
    text = "\n".join(log_list[-max_lines:]) if log_list else "Menunggu output ..."
    # Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="log-terminal">{text}</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 Claude Orchestrator")
    st.divider()

    page = st.radio(
        "Menu",
        ["📊 Dashboard", "🚀 Jalankan Task", "🔄 Auto Runner",
         "📁 Riwayat Output", "⚙️ Konfigurasi"],
        label_visibility="collapsed",
    )

    st.divider()

    # Live status badges in sidebar
    if st.session_state.auto_running:
        cur = st.session_state._auto_iter_ref[0]
        mx = st.session_state.auto_max
        st.success(f"🔄 Auto Runner: Iterasi {cur}/{mx}")
    elif st.session_state.task_running:
        st.info("⏳ Task sedang berjalan ...")
    else:
        st.caption("Tidak ada proses aktif")

    st.divider()
    if st.button("🔃 Refresh", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Status Pool Akun Claude")
    st.caption(f"Diperbarui: {datetime.now().strftime('%d %b %Y, %H:%M:%S')}")

    try:
        acc_mgr = AccountManager(BASE_DIR)
        summary = acc_mgr.get_status_summary()

        ready_n  = sum(1 for s in summary if s["status"] == "READY")
        limit_n  = len(summary) - ready_n
        total_t  = sum(s.get("total_tasks", 0) for s in summary)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🟢 Akun Ready",   ready_n)
        c2.metric("🔴 Akun Cooldown", limit_n)
        c3.metric("📨 Total Task",    total_t)
        c4.metric("👥 Total Akun",    len(summary))

        st.divider()

        # Account cards
        cols = st.columns(len(summary))
        for col, s in zip(cols, summary):
            is_ready = s["status"] == "READY"
            with col:
                with st.container(border=True):
                    st.markdown(f"**{s['name']}**")
                    if is_ready:
                        st.markdown('<span class="badge-ready">🟢 READY</span>',
                                    unsafe_allow_html=True)
                        st.caption("Siap menerima task")
                    else:
                        st.markdown('<span class="badge-limit">🔴 COOLDOWN</span>',
                                    unsafe_allow_html=True)
                        st.caption(f"⏱ {s['cooldown']}")
                    st.caption(f"✅ {s.get('total_tasks', 0)} task selesai")

        st.divider()

        # Git repo section
        config = acc_mgr.config
        git = GitManager(config.get("repo_path", ""), config.get("github_pat", ""))
        st.subheader("📁 Repository Git")
        if git.is_valid_repo():
            branch = git.get_current_branch()
            gs = git.get_status()
            st.success(f"✅ `{config['repo_path']}` — Branch: **{branch}**")
            if gs:
                st.code(gs, language="bash")
            else:
                st.caption("Working tree clean ✓")
        else:
            st.warning("Repo belum dikonfigurasi. Isi `repo_path` di halaman **⚙️ Konfigurasi**.")

    except Exception as e:
        st.error(f"Gagal memuat status: {e}")

    # Auto-refresh
    with st.expander("⚡ Auto-Refresh Halaman"):
        do_auto = st.checkbox("Refresh otomatis setiap 15 detik")
        if do_auto:
            time.sleep(15)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ JALANKAN TASK
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🚀 Jalankan Task":
    st.title("🚀 Jalankan Task ke Claude")

    with st.form("task_form"):
        task_text = st.text_area(
            "Tugas untuk Claude",
            placeholder="Contoh: Buat fungsi autentikasi JWT di modul auth.py ...",
            height=160,
        )
        col1, col2 = st.columns(2)
        with col1:
            include_git = st.checkbox("Sertakan konteks struktur repo Git", value=True)
        with col2:
            headless = st.checkbox("Headless (browser tersembunyi)", value=True)

        submitted = st.form_submit_button(
            "▶️ Jalankan",
            disabled=st.session_state.task_running,
            type="primary",
            use_container_width=True,
        )

    if submitted and task_text.strip():
        st.session_state.task_logs = []
        st.session_state.task_result = None
        st.session_state.task_error = None
        st.session_state._task_result_holder = {}
        st.session_state.task_running = True

        t = threading.Thread(
            target=_bg_single_task,
            args=(task_text, include_git, headless,
                  st.session_state.task_logs,
                  st.session_state._task_result_holder),
            daemon=True,
        )
        t.start()
        st.session_state.task_thread = t

    # ── Live progress ──────────────────────────────────────────────
    if st.session_state.task_running or st.session_state.task_logs:
        st.subheader("📟 Log Eksekusi")
        _render_log(st.session_state.task_logs)

        if st.session_state.task_running:
            t = st.session_state.task_thread
            if t and not t.is_alive():
                rh = st.session_state._task_result_holder
                st.session_state.task_result = rh.get("response")
                st.session_state.task_error  = rh.get("error")
                st.session_state.task_running = False
                st.rerun()
            else:
                with st.spinner("Menunggu respons Claude ..."):
                    time.sleep(3)
                st.rerun()

    # ── Result ────────────────────────────────────────────────────
    if st.session_state.task_result:
        st.success("✅ Task selesai!")
        rh = st.session_state._task_result_holder
        st.caption(f"Dijawab oleh: **{rh.get('account', '?')}** · Disimpan: `{os.path.basename(rh.get('file', ''))}`")
        with st.expander("💬 Lihat Respons Claude", expanded=True):
            st.markdown(st.session_state.task_result)

    if st.session_state.task_error:
        st.error(f"❌ {st.session_state.task_error}")

    if (st.session_state.task_result or st.session_state.task_error) and \
            st.button("🗑️ Bersihkan"):
        st.session_state.task_logs   = []
        st.session_state.task_result = None
        st.session_state.task_error  = None
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ AUTO RUNNER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Auto Runner":
    st.title("🔄 Auto Runner")
    st.info(
        "Auto Runner mengirim prompt berulang-ulang (mis. `lanjut`) ke Claude, "
        "bergantian antar akun yang tersedia, hingga batas iterasi atau pekerjaan selesai.",
        icon="ℹ️",
    )

    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            max_iter = st.number_input("Maksimum Iterasi", 1, 1000, 100,
                                       disabled=st.session_state.auto_running)
        with col2:
            prompt_text = st.text_input("Prompt dikirim tiap iterasi", value="lanjut",
                                        disabled=st.session_state.auto_running)
        with col3:
            headless_auto = st.checkbox("Headless", value=True,
                                        disabled=st.session_state.auto_running)

        c_start, c_stop = st.columns(2)
        with c_start:
            start_btn = st.button(
                "▶️ Mulai",
                disabled=st.session_state.auto_running,
                type="primary",
                use_container_width=True,
            )
        with c_stop:
            stop_btn = st.button(
                "⏹️ Stop",
                disabled=not st.session_state.auto_running,
                use_container_width=True,
            )

    if start_btn:
        stop_ev = threading.Event()
        iter_ref = [0]
        st.session_state.auto_logs       = []
        st.session_state.auto_iteration  = 0
        st.session_state.auto_max        = max_iter
        st.session_state.auto_running    = True
        st.session_state.auto_stop_event = stop_ev
        st.session_state._auto_iter_ref  = iter_ref

        t = threading.Thread(
            target=_bg_auto_runner,
            args=(max_iter, prompt_text, headless_auto,
                  stop_ev, st.session_state.auto_logs, iter_ref),
            daemon=True,
        )
        t.start()
        st.session_state.auto_thread = t

    if stop_btn:
        st.session_state.auto_stop_event.set()
        st.session_state.auto_running = False
        st.warning("⏹️ Stop signal terkirim. Runner berhenti setelah iterasi saat ini.")

    # ── Progress & logs ───────────────────────────────────────────
    if st.session_state.auto_running or st.session_state.auto_logs:
        cur = st.session_state._auto_iter_ref[0]
        mx  = st.session_state.auto_max
        st.session_state.auto_iteration = cur

        if mx > 0:
            st.progress(min(1.0, cur / mx), text=f"Iterasi {cur} / {mx}")

        st.subheader("📟 Log Auto Runner")
        _render_log(st.session_state.auto_logs, max_lines=100)

        if st.session_state.auto_running:
            t = st.session_state.auto_thread
            if t and not t.is_alive():
                st.session_state.auto_running = False
                st.rerun()
            else:
                time.sleep(4)
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ RIWAYAT OUTPUT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📁 Riwayat Output":
    st.title("📁 Riwayat Output")

    out_dir = Path(BASE_DIR) / "outputs"
    out_dir.mkdir(exist_ok=True)

    files = sorted(out_dir.glob("*.md"), reverse=True)

    if not files:
        st.info("Belum ada output. Jalankan task atau auto runner terlebih dahulu.")
    else:
        st.caption(f"📂 {len(files)} file output tersimpan di `{out_dir}`")

        # Summary table
        rows = []
        for f in files[:50]:  # show latest 50
            size_kb = f.stat().st_size / 1024
            rows.append({
                "File": f.name,
                "Ukuran (KB)": f"{size_kb:.1f}",
                "Waktu": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.divider()

        selected = st.selectbox(
            "Buka file",
            options=files,
            format_func=lambda f: f.name,
        )
        if selected:
            content = selected.read_text(encoding="utf-8")
            col1, col2 = st.columns([5, 1])
            with col1:
                st.caption(f"📄 `{selected.name}` — {selected.stat().st_size / 1024:.1f} KB")
            with col2:
                st.download_button(
                    "⬇️ Download",
                    data=content,
                    file_name=selected.name,
                    mime="text/markdown",
                    use_container_width=True,
                )
            with st.expander("📖 Isi File", expanded=True):
                st.markdown(content)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ KONFIGURASI
# ══════════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Konfigurasi":
    st.title("⚙️ Konfigurasi")

    cfg_path = Path(BASE_DIR) / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # ── General settings ──────────────────────────────────────────
    st.subheader("🔧 Pengaturan Umum")
    col1, col2 = st.columns(2)
    with col1:
        repo_path     = st.text_input("📁 Path Repository Git lokal",
                                      value=config.get("repo_path", ""),
                                      placeholder=r"C:\Users\Anda\proyek-github")
        cooldown_hrs  = st.number_input("⏱️ Cooldown per akun (jam)",
                                         value=float(config.get("cooldown_hours", 5.0)),
                                         min_value=0.5, step=0.5)
    with col2:
        github_pat    = st.text_input("🔑 GitHub PAT (opsional, untuk git push)",
                                      value=config.get("github_pat", ""),
                                      type="password")
        headless_cfg  = st.checkbox("🖥️ Headless mode (browser tidak tampil di layar)",
                                    value=config.get("headless", False))

    # ── Account list ──────────────────────────────────────────────
    st.subheader("👥 Akun Claude")
    accounts = config.get("accounts", [])
    updated_accounts = []
    for acc in accounts:
        with st.expander(f"Akun #{acc['id']} — {acc.get('name', '')}"):
            a_name = st.text_input("Nama tampilan", value=acc.get("name", ""),
                                   key=f"acc_name_{acc['id']}")
            a_url  = st.text_input("URL Chat TAPIR", value=acc.get("tapir_chat_url", ""),
                                   key=f"acc_url_{acc['id']}")
            updated_accounts.append({**acc, "name": a_name, "tapir_chat_url": a_url})

    if st.button("💾 Simpan Konfigurasi", type="primary", use_container_width=True):
        new_cfg = {
            **config,
            "repo_path":     repo_path,
            "cooldown_hours": cooldown_hrs,
            "github_pat":    github_pat,
            "headless":      headless_cfg,
            "accounts":      updated_accounts,
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, indent=2, ensure_ascii=False)
        st.success("✅ Konfigurasi berhasil disimpan!")

    st.divider()

    # ── Danger zone ───────────────────────────────────────────────
    st.subheader("⚠️ Zona Berbahaya")
    with st.expander("Reset state akun (hapus cooldown)"):
        st.warning(
            "Reset akan menghapus `state.json` dan mengembalikan SEMUA akun ke status READY. "
            "Gunakan jika state korup atau ingin mulai dari awal."
        )
        if st.button("🗑️ Reset State Sekarang", type="secondary"):
            state_path = Path(BASE_DIR) / "state.json"
            if state_path.exists():
                state_path.unlink()
            st.success("✅ State direset! Semua akun kembali READY.")
            st.rerun()
