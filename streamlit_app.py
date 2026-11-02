"""
Claude Multi-Account Orchestrator — Cloud-Native Edition
100% Berjalan di Streamlit Cloud tanpa memerlukan PC Backend / Browser Automation.
Audited & Thread-Safe.
"""

import streamlit as st
import threading
import time
import os
import sys
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from account_manager import AccountManager
from claude_api_client import ClaudeWebClient, ClaudeRateLimitError, ClaudeAuthError, ClaudeAPIError

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL THREAD-SAFE STATE (Menghindari Streamlit NoSessionContext Bug)
# ──────────────────────────────────────────────────────────────────────────────
class GlobalWorkerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.task_running = False
        self.task_logs = []
        self.task_result = None
        self.task_error = None
        self.task_account = None

        self.auto_running = False
        self.auto_logs = []
        self.auto_iteration = 0
        self.auto_max = 100
        self.auto_stop_event = threading.Event()

    def log_task(self, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.task_logs.append(f"[{ts}] {text}")

    def log_auto(self, text: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.auto_logs.append(f"[{ts}] {text}")

if "global_state" not in st.session_state:
    st.session_state.global_state = GlobalWorkerState()

GSTATE = st.session_state.global_state

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG & CSS
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claude Cloud Orchestrator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.log-terminal {
    background: #0d1117;
    color: #58a6ff;
    padding: 14px 16px;
    border-radius: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.6;
    max-height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    border: 1px solid #30363d;
}
.badge-ready  { color: #22c55e; font-weight: 700; font-size: 14px; }
.badge-limit  { color: #ef4444; font-weight: 700; font-size: 14px; }
.badge-nokey  { color: #eab308; font-weight: 700; font-size: 14px; }
</style>
""", unsafe_allow_html=True)

acc_mgr = AccountManager(BASE_DIR)

def render_log(log_list: list, max_lines: int = 100):
    text = "\n".join(log_list[-max_lines:]) if log_list else "Belum ada log aktif..."
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="log-terminal">{text}</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# WORKERS
# ──────────────────────────────────────────────────────────────────────────────
def _thread_single_task(prompt_text: str):
    GSTATE.task_running = True
    GSTATE.task_logs = []
    GSTATE.task_result = None
    GSTATE.task_error = None
    GSTATE.task_account = None

    GSTATE.log_task(f"Memulai task: '{prompt_text[:60]}...'")
    
    max_attempts = len(acc_mgr.config.get("accounts", []))
    attempts = 0
    success = False

    while attempts < max_attempts:
        account = acc_mgr.get_available_account()
        if not account:
            GSTATE.log_task("⚠️ Semua akun Claude sedang cooldown atau belum diisi Session Key!")
            GSTATE.task_error = "Semua akun dalam masa jeda 5 jam atau sessionKey kosong."
            break

        GSTATE.log_task(f"🚀 Mengirim ke {account['name']} (ID: {account['id']})...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log_task(f"✅ Sukses! Diterima {len(resp):,} karakter respons.")
            
            GSTATE.task_result = resp
            GSTATE.task_account = account["name"]
            success = True
            break

        except ClaudeRateLimitError as e:
            GSTATE.log_task(f"⏳ {account['name']} terkena Rate Limit 5 Jam: {e}. Auto-failover...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            attempts += 1
        except ClaudeAuthError as e:
            GSTATE.log_task(f"🔐 Auth Error pada {account['name']}: {e}")
            attempts += 1
        except Exception as e:
            GSTATE.log_task(f"❌ Error pada {account['name']}: {e}")
            attempts += 1

    if not success and not GSTATE.task_error:
        GSTATE.task_error = "Gagal menyelesaikan task di seluruh akun Claude."

    GSTATE.task_running = False

def _thread_auto_runner(max_iter: int, prompt_text: str):
    GSTATE.log_auto(f"🔄 Auto-Runner aktif. Target: {max_iter} iterasi | Prompt: '{prompt_text}'")
    
    for i in range(1, max_iter + 1):
        if GSTATE.auto_stop_event.is_set():
            GSTATE.log_auto("⏹️ Auto-runner dihentikan pengguna.")
            break

        GSTATE.auto_iteration = i
        GSTATE.log_auto(f"\n>>> Iterasi #{i} / {max_iter}")

        account = acc_mgr.get_available_account()
        if not account:
            GSTATE.log_auto("💤 Semua akun cooldown. Istirahat 60 detik sebelum periksa kembali...")
            for _ in range(60):
                if GSTATE.auto_stop_event.is_set():
                    break
                time.sleep(1)
            continue

        GSTATE.log_auto(f"Kirim instruksi ke {account['name']}...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            GSTATE.log_auto(f"✅ Selesai [{account['name']}] - {len(resp):,} karakter")

            resp_lower = resp.lower()
            if any(sig in resp_lower for sig in ["seluruh audit selesai", "pekerjaan sudah selesai", "tidak ada lagi"]):
                GSTATE.log_auto("🎉 Claude menandakan bahwa seluruh pekerjaan SELESAI!")
                break

        except ClaudeRateLimitError as e:
            GSTATE.log_auto(f"⏳ Rate limit [{account['name']}]. Beralih ke akun berikutnya...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
        except Exception as e:
            GSTATE.log_auto(f"❌ Error [{account['name']}]: {e}")

        if not GSTATE.auto_stop_event.is_set():
            time.sleep(5)

    GSTATE.log_auto("🏁 Auto-runner selesai.")
    GSTATE.auto_running = False

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ Claude Orchestrator")
    st.caption("Cloud Native • No PC Required")
    st.divider()

    page = st.radio(
        "Menu",
        ["📊 Dashboard", "🚀 Jalankan Task", "🔄 Auto Runner", "🔑 Setup Akun (Cookies)", "⚙️ Pengaturan"],
        label_visibility="collapsed"
    )

    st.divider()
    summary = acc_mgr.get_status_summary()
    ready_count = sum(1 for s in summary if s["status"] == "READY")
    st.write(f"Akun Siap: **{ready_count} / {len(summary)}**")
    
    if GSTATE.auto_running:
        st.warning(f"🔄 Auto-Runner Aktif (#{GSTATE.auto_iteration})")
    elif GSTATE.task_running:
        st.info("⏳ Single task sedang berjalan...")
    
    if st.button("🔃 Refresh Status", use_container_width=True):
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Status Pool Akun Claude (Cloud)")
    st.caption("Auto-failover antar 4 akun tanpa server lokal")

    summary = acc_mgr.get_status_summary()
    ready_n = sum(1 for s in summary if s["status"] == "READY")
    limit_n = sum(1 for s in summary if s["status"] == "RATE_LIMITED")
    nokey_n = sum(1 for s in summary if s["status"] == "NO_KEY")
    total_t = sum(s.get("total_tasks", 0) for s in summary)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Akun Siap", ready_n)
    c2.metric("🔴 Cooldown 5 Jam", limit_n)
    c3.metric("⚠️ Belum Diisi Key", nokey_n)
    c4.metric("📨 Total Selesai", total_t)

    st.divider()

    cols = st.columns(len(summary))
    for col, s in zip(cols, summary):
        with col:
            with st.container(border=True):
                st.markdown(f"**{s['name']}**")
                if s["status"] == "READY":
                    st.markdown('<span class="badge-ready">🟢 READY</span>', unsafe_allow_html=True)
                    st.caption("Siap dieksekusi")
                elif s["status"] == "RATE_LIMITED":
                    st.markdown('<span class="badge-limit">🔴 COOLDOWN</span>', unsafe_allow_html=True)
                    st.caption(f"⏱ {s['cooldown']}")
                else:
                    st.markdown('<span class="badge-nokey">⚠️ BELUM ADA KEY</span>', unsafe_allow_html=True)
                    st.caption("Isi di menu Setup Akun")
                st.caption(f"Tasks: {s['total_tasks']}")

    if nokey_n > 0:
        st.info("💡 Beberapa akun belum memiliki sessionKey. Buka menu **🔑 Setup Akun (Cookies)** di sidebar untuk memasukkannya.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: JALANKAN TASK
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🚀 Jalankan Task":
    st.title("🚀 Jalankan Task ke Claude")

    task_input = st.text_area(
        "Instruksi / Pertanyaan untuk Claude:",
        placeholder="Contoh: Lakukan audit modul autentikasi atau periksa bug...",
        height=140
    )

    if st.button("▶️ Kirim Task", type="primary", disabled=GSTATE.task_running, use_container_width=True):
        if task_input.strip():
            t = threading.Thread(target=_thread_single_task, args=(task_input,), daemon=True)
            t.start()
            st.rerun()

    if GSTATE.task_running or GSTATE.task_logs:
        st.subheader("📟 Log Eksekusi")
        render_log(GSTATE.task_logs)

        if GSTATE.task_running:
            time.sleep(2)
            st.rerun()

    if GSTATE.task_result:
        st.success(f"✅ Selesai! Dijawab oleh: **{GSTATE.task_account}**")
        with st.expander("💬 Respons Claude", expanded=True):
            st.markdown(GSTATE.task_result)

    if GSTATE.task_error:
        st.error(f"❌ {GSTATE.task_error}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: AUTO RUNNER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Auto Runner":
    st.title("🔄 Auto Runner")
    st.info("Auto Runner mengirim perintah berulang kali (misal: 'lanjut') dan otomatis memutar akun jika limit 5 jam tercapai.")

    c1, c2 = st.columns(2)
    with c1:
        max_i = st.number_input("Maksimum Iterasi", 1, 500, 100, disabled=GSTATE.auto_running)
    with c2:
        prompt_auto = st.text_input("Prompt Tiap Langkah", value="lanjut", disabled=GSTATE.auto_running)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("▶️ Mulai Auto-Runner", type="primary", disabled=GSTATE.auto_running, use_container_width=True):
            GSTATE.auto_stop_event.clear()
            GSTATE.auto_running = True
            GSTATE.auto_logs = []
            GSTATE.auto_iteration = 0
            GSTATE.auto_max = max_i
            t = threading.Thread(target=_thread_auto_runner, args=(max_i, prompt_auto), daemon=True)
            t.start()
            st.rerun()

    with b2:
        if st.button("⏹️ Hentikan", disabled=not GSTATE.auto_running, use_container_width=True):
            GSTATE.auto_stop_event.set()
            GSTATE.auto_running = False
            st.warning("Mengirim sinyal berhenti...")
            st.rerun()

    if GSTATE.auto_running or GSTATE.auto_logs:
        if GSTATE.auto_max > 0:
            st.progress(min(1.0, GSTATE.auto_iteration / GSTATE.auto_max), 
                        text=f"Iterasi {GSTATE.auto_iteration} / {GSTATE.auto_max}")
        render_log(GSTATE.auto_logs)

        if GSTATE.auto_running:
            time.sleep(3)
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETUP AKUN (COOKIES)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔑 Setup Akun (Cookies)":
    st.title("🔑 Setup Session Key Akun Claude")
    
    st.markdown("""
    ### 📌 Cara Mengambil `sessionKey` dari Browser:
    1. Buka browser dan login ke akun Claude Anda di **https://claude.ai**.
    2. Tekan **F12** (Developer Tools) -> Tab **Application** (Chrome/Edge) atau **Storage** (Firefox).
    3. Di panel kiri, klik **Cookies** -> `https://claude.ai`.
    4. Cari baris bernama **`sessionKey`** (dimulai dengan `sk-ant-sid01-...`).
    5. Salin nilainya dan tempelkan ke kolom form akun di bawah.
    """)

    st.divider()

    accounts = acc_mgr.config.get("accounts", [])
    updated = False

    for acc in accounts:
        with st.expander(f"⚙️ {acc['name']} (Akun #{acc['id']})", expanded=not bool(acc.get("session_key"))):
            current_key = acc.get("session_key", "")
            
            c_input, c_test = st.columns([4, 1])
            with c_input:
                new_key = st.text_input(
                    f"sessionKey untuk {acc['name']}",
                    value=current_key,
                    type="password",
                    placeholder="sk-ant-sid01-xxxx-xxxx...",
                    key=f"input_key_{acc['id']}"
                )
            with c_test:
                st.write("")
                st.write("")
                if st.button("🔍 Uji Key", key=f"btn_test_{acc['id']}"):
                    if new_key.strip():
                        test_cli = ClaudeWebClient(new_key.strip())
                        ok, msg = test_cli.test_connection()
                        if ok:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")
                    else:
                        st.warning("Masukkan sessionKey terlebih dahulu.")

            chat_url = st.text_input(
                f"Thread URL / UUID (Opsional, untuk melanjutkan percakapan TAPIR):",
                value=acc.get("tapir_chat_url", ""),
                key=f"input_url_{acc['id']}"
            )
            
            if new_key != current_key or chat_url != acc.get("tapir_chat_url"):
                acc["session_key"] = new_key.strip()
                acc["tapir_chat_url"] = chat_url.strip()
                updated = True

    if updated or st.button("💾 Simpan Konfigurasi", type="primary", use_container_width=True):
        acc_mgr.save_config()
        st.success("✅ Konfigurasi akun berhasil disimpan!")
        st.rerun()

    st.divider()
    with st.expander("🛡️ Tips: Simpan Permanen di Streamlit Secrets (Anti-Reset)"):
        st.markdown("""
        Agar `sessionKey` tidak hilang saat container Streamlit Cloud restart, Anda bisa memasukkannya ke **Streamlit Dashboard -> App Settings -> Secrets**:
        ```toml
        [[accounts]]
        id = 1
        name = "Claude Account 1"
        session_key = "sk-ant-sid01-..."

        [[accounts]]
        id = 2
        name = "Claude Account 2"
        session_key = "sk-ant-sid01-..."
        ```
        """)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PENGATURAN
# ══════════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Pengaturan":
    st.title("⚙️ Pengaturan Pool")
    
    cd_hours = st.number_input(
        "Cooldown Rate Limit (Jam)",
        min_value=1.0,
        max_value=12.0,
        value=float(acc_mgr.config.get("cooldown_hours", 5.0)),
        step=0.5
    )
    
    if st.button("Simpan Pengaturan", type="primary"):
        acc_mgr.config["cooldown_hours"] = cd_hours
        acc_mgr.save_config()
        st.success("Pengaturan tersimpan!")

    st.divider()
    st.subheader("Reset State")
    if st.button("🗑️ Reset Status Cooldown Semua Akun"):
        for acc in acc_mgr.state["accounts"].values():
            acc["status"] = "ready"
            acc["available_at"] = 0
            acc["cooldown_until_str"] = ""
        acc_mgr.save_state()
        st.success("Semua akun telah dikembalikan ke status READY!")
        st.rerun()
