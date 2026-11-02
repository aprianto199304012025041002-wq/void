"""
Claude Multi-Account Orchestrator — Cloud-Native Edition
100% Berjalan di Streamlit Cloud tanpa memerlukan PC Backend / Browser Automation.
Menggunakan Session API langsung dengan auto-failover 4 akun.
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
# PAGE CONFIG
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

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE INITIALIZATION
# ──────────────────────────────────────────────────────────────────────────────
if "task_running" not in st.session_state:
    st.session_state.task_running = False
if "task_logs" not in st.session_state:
    st.session_state.task_logs = []
if "task_result" not in st.session_state:
    st.session_state.task_result = None
if "task_error" not in st.session_state:
    st.session_state.task_error = None
if "task_account" not in st.session_state:
    st.session_state.task_account = None

if "auto_running" not in st.session_state:
    st.session_state.auto_running = False
if "auto_logs" not in st.session_state:
    st.session_state.auto_logs = []
if "auto_iteration" not in st.session_state:
    st.session_state.auto_iteration = 0
if "auto_max" not in st.session_state:
    st.session_state.auto_max = 100
if "auto_stop_event" not in st.session_state:
    st.session_state.auto_stop_event = threading.Event()

acc_mgr = AccountManager(BASE_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING HELPER
# ──────────────────────────────────────────────────────────────────────────────
def append_log(target: list, text: str):
    ts = datetime.now().strftime("%H:%M:%S")
    target.append(f"[{ts}] {text}")

def render_log(log_list: list, max_lines: int = 100):
    text = "\n".join(log_list[-max_lines:]) if log_list else "Menunggu instruksi..."
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="log-terminal">{text}</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# WORKER: SINGLE TASK
# ──────────────────────────────────────────────────────────────────────────────
def execute_single_task(prompt_text: str):
    st.session_state.task_running = True
    st.session_state.task_logs = []
    st.session_state.task_result = None
    st.session_state.task_error = None

    append_log(st.session_state.task_logs, f"Memulai task: '{prompt_text[:60]}...'")
    
    max_attempts = len(acc_mgr.config.get("accounts", []))
    attempts = 0
    success = False

    while attempts < max_attempts:
        account = acc_mgr.get_available_account()
        if not account:
            append_log(st.session_state.task_logs, "⚠️ Semua akun Claude sedang cooldown atau belum diisi Session Key!")
            st.session_state.task_error = "Semua akun dalam masa jeda 5 jam atau sessionKey kosong."
            break

        append_log(st.session_state.task_logs, f"🚀 Mengirim ke {account['name']} (ID: {account['id']})...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            append_log(st.session_state.task_logs, f"✅ Berhasil mendapatkan respons ({len(resp):,} karakter).")
            
            st.session_state.task_result = resp
            st.session_state.task_account = account["name"]
            success = True
            break

        except ClaudeRateLimitError as e:
            append_log(st.session_state.task_logs, f"⏳ {account['name']} terkena Rate Limit 5 Jam. Melakukan auto-failover...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
            attempts += 1
        except ClaudeAuthError as e:
            append_log(st.session_state.task_logs, f"🔐 Auth Error pada {account['name']}: {e}")
            attempts += 1
        except Exception as e:
            append_log(st.session_state.task_logs, f"❌ Terjadi kesalahan pada {account['name']}: {e}")
            attempts += 1

    if not success and not st.session_state.task_error:
        st.session_state.task_error = "Gagal menyelesaikan task di semua akun."

    st.session_state.task_running = False

# ──────────────────────────────────────────────────────────────────────────────
# WORKER: AUTO RUNNER LOOP (BACKGROUND THREAD)
# ──────────────────────────────────────────────────────────────────────────────
def auto_runner_thread(max_iter: int, prompt_text: str, stop_event: threading.Event, logs: list):
    append_log(logs, f"🔄 Auto-Runner dimulai. Target: {max_iter} iterasi | Prompt: '{prompt_text}'")
    
    for i in range(1, max_iter + 1):
        if stop_event.is_set():
            append_log(logs, "⏹️ Auto-runner dihentikan pengguna.")
            break

        st.session_state.auto_iteration = i
        append_log(logs, f"\n>>> Iterasi #{i} / {max_iter}")

        account = acc_mgr.get_available_account()
        if not account:
            append_log(logs, "💤 Semua akun sedang cooldown. Menunggu 60 detik sebelum periksa kembali...")
            for _ in range(60):
                if stop_event.is_set():
                    break
                time.sleep(1)
            continue

        append_log(logs, f"Mengirim perintah ke {account['name']}...")
        client = ClaudeWebClient(account["session_key"])
        chat_url = account.get("tapir_chat_url", "")

        try:
            resp = client.send_message(prompt_text, conversation_uuid=chat_url)
            acc_mgr.record_task_success(account["id"])
            append_log(logs, f"✅ Sukses [{account['name']}] - {len(resp)} karakter")

            # Cek sinyal selesai
            resp_lower = resp.lower()
            if any(sig in resp_lower for sig in ["seluruh audit selesai", "pekerjaan sudah selesai", "tidak ada lagi"]):
                append_log(logs, "🎉 Claude mengindikasikan seluruh pekerjaan SELESAI!")
                break

        except ClaudeRateLimitError as e:
            append_log(logs, f"⏳ Rate limit pada {account['name']}. Beralih ke akun berikutnya...")
            acc_mgr.mark_rate_limited(account["id"], reset_seconds=e.reset_seconds)
        except Exception as e:
            append_log(logs, f"❌ Error: {e}")

        # Jeda
        if not stop_event.is_set():
            time.sleep(5)

    append_log(logs, "🏁 Auto-runner selesai.")
    st.session_state.auto_running = False

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
    
    if st.session_state.auto_running:
        st.warning(f"🔄 Auto-Runner Aktif (#{st.session_state.auto_iteration})")
    
    if st.button("🔃 Refresh Status", use_container_width=True):
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Status Pool Akun Claude (Cloud)")
    st.caption("Terhubung langsung ke API Claude via Cloud-Safe Session")

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
        st.info("💡 Beberapa akun belum memiliki sessionKey. Buka menu **🔑 Setup Akun (Cookies)** di sebelah kiri untuk memasukkannya.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: JALANKAN TASK
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🚀 Jalankan Task":
    st.title("🚀 Jalankan Task ke Claude")

    task_input = st.text_area(
        "Instruksi / Pertanyaan untuk Claude:",
        placeholder="Contoh: Lakukan audit modul autentikasi atau analisa bug...",
        height=140
    )

    if st.button("▶️ Kirim Task", type="primary", disabled=st.session_state.task_running, use_container_width=True):
        if task_input.strip():
            execute_single_task(task_input)
            st.rerun()

    if st.session_state.task_logs:
        st.subheader("📟 Log Eksekusi")
        render_log(st.session_state.task_logs)

    if st.session_state.task_result:
        st.success(f"✅ Selesai! Dijawab oleh: **{st.session_state.task_account}**")
        with st.expander("💬 Respons Claude", expanded=True):
            st.markdown(st.session_state.task_result)

    if st.session_state.task_error:
        st.error(f"❌ {st.session_state.task_error}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: AUTO RUNNER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Auto Runner":
    st.title("🔄 Auto Runner")
    st.info("Auto Runner akan mengirim pesan berulang (misal 'lanjut') secara otomatis dan memutar 4 akun jika terkena rate limit.")

    c1, c2 = st.columns(2)
    with c1:
        max_i = st.number_input("Maksimum Iterasi", 1, 500, 100, disabled=st.session_state.auto_running)
    with c2:
        prompt_auto = st.text_input("Prompt Tiap Langkah", value="lanjut", disabled=st.session_state.auto_running)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("▶️ Mulai Auto-Runner", type="primary", disabled=st.session_state.auto_running, use_container_width=True):
            st.session_state.auto_stop_event.clear()
            st.session_state.auto_running = True
            st.session_state.auto_logs = []
            st.session_state.auto_iteration = 0
            st.session_state.auto_max = max_i
            t = threading.Thread(
                target=auto_runner_thread,
                args=(max_i, prompt_auto, st.session_state.auto_stop_event, st.session_state.auto_logs),
                daemon=True
            )
            t.start()
            st.rerun()

    with b2:
        if st.button("⏹️ Hentikan", disabled=not st.session_state.auto_running, use_container_width=True):
            st.session_state.auto_stop_event.set()
            st.session_state.auto_running = False
            st.warning("Mengirim sinyal berhenti...")
            st.rerun()

    if st.session_state.auto_running or st.session_state.auto_logs:
        if st.session_state.auto_max > 0:
            st.progress(min(1.0, st.session_state.auto_iteration / st.session_state.auto_max), 
                        text=f"Iterasi {st.session_state.auto_iteration} / {st.session_state.auto_max}")
        render_log(st.session_state.auto_logs)

        if st.session_state.auto_running:
            time.sleep(3)
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETUP AKUN (COOKIES)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔑 Setup Akun (Cookies)":
    st.title("🔑 Setup Session Key Akun Claude")
    
    st.markdown("""
    ### 📌 Cara Mengambil `sessionKey` dari Browser (1 Menit):
    1. Buka browser dan login ke akun Claude Anda di **https://claude.ai**.
    2. Tekan **F12** (atau klik kanan -> *Inspect*), lalu buka tab **Application** (atau **Storage** di Firefox).
    3. Di panel kiri, klik **Cookies** -> `https://claude.ai`.
    4. Cari nama cookie **`sessionKey`** (nilainya biasanya dimulai dengan `sk-ant-sid01-...`).
    5. Klik dua kali nilainya, salin (*Copy*), dan tempelkan pada form akun di bawah ini.
    """)

    st.divider()

    accounts = acc_mgr.config.get("accounts", [])
    updated = False

    for acc in accounts:
        with st.expander(f"⚙️ {acc['name']} (Akun #{acc['id']})", expanded=not bool(acc.get("session_key"))):
            current_key = acc.get("session_key", "")
            masked = current_key[:15] + "..." + current_key[-6:] if len(current_key) > 25 else current_key
            
            st.caption(f"Status saat ini: {'🟢 Terisi (' + masked + ')' if current_key else '🔴 Belum diisi'}")
            
            new_key = st.text_input(
                f"sessionKey untuk {acc['name']}",
                value=current_key,
                type="password",
                placeholder="sk-ant-sid01-xxxx-xxxx...",
                key=f"input_key_{acc['id']}"
            )
            
            chat_url = st.text_input(
                f"Chat URL / UUID (Opsional, untuk melanjutkan thread tertentu):",
                value=acc.get("tapir_chat_url", ""),
                key=f"input_url_{acc['id']}"
            )
            
            if new_key != current_key or chat_url != acc.get("tapir_chat_url"):
                acc["session_key"] = new_key.strip()
                acc["tapir_chat_url"] = chat_url.strip()
                updated = True

    if updated or st.button("💾 Simpan Semua Session Key", type="primary", use_container_width=True):
        acc_mgr.save_config()
        st.success("✅ Semua session key berhasil disimpan! Sekarang Anda bisa langsung menjalankan task.")
        st.rerun()

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
