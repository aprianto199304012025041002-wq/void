"""
Claude Multi-Account Orchestrator — Streamlit Cloud UI
Hanya UI: semua eksekusi dilakukan oleh server.py di PC lokal.
"""

import streamlit as st
import requests
import time
import json
import os
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claude Orchestrator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.log-terminal {
    background: #0d1117;
    color: #79c0ff;
    padding: 14px 16px;
    border-radius: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.7;
    max-height: 450px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    border: 1px solid #21262d;
}
.badge-ready { color: #3fb950; font-weight: 700; }
.badge-limit { color: #f85149; font-weight: 700; }
.conn-ok  { color: #3fb950; }
.conn-err { color: #f85149; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
def _init():
    if "server_url" not in st.session_state:
        st.session_state.server_url = os.environ.get("ORCHESTRATOR_URL", "")
    if "task_polling" not in st.session_state:
        st.session_state.task_polling = False
    if "auto_polling" not in st.session_state:
        st.session_state.auto_polling = False

_init()


# ──────────────────────────────────────────────────────────────────────────────
# API HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _url(path: str) -> str:
    base = st.session_state.server_url.rstrip("/")
    return f"{base}{path}"


def _get(path: str, timeout: int = 8):
    try:
        r = requests.get(_url(path), timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "❌ Tidak bisa terhubung ke server. Pastikan `server.py` + tunnel sudah aktif."
    except Exception as e:
        return None, f"❌ {e}"


def _post(path: str, payload: dict = None, timeout: int = 10):
    try:
        r = requests.post(_url(path), json=payload or {}, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "❌ Tidak bisa terhubung ke server."
    except Exception as e:
        return None, f"❌ {e}"


def _render_log(lines: list, max_lines: int = 80):
    text = "\n".join(lines[-max_lines:]) if lines else "Menunggu output ..."
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="log-terminal">{text}</div>', unsafe_allow_html=True)


def _check_connection() -> bool:
    if not st.session_state.server_url:
        return False
    data, err = _get("/")
    return err is None


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

    # ── Server URL config ──────────────────────────────────────────
    st.caption("🔌 **URL Server (PC lokal)**")
    new_url = st.text_input(
        "Server URL",
        value=st.session_state.server_url,
        placeholder="https://xxxx.trycloudflare.com",
        label_visibility="collapsed",
    )
    if new_url != st.session_state.server_url:
        st.session_state.server_url = new_url
        st.rerun()

    connected = _check_connection()
    if connected:
        st.markdown('<span class="conn-ok">🟢 Terhubung ke server</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="conn-err">🔴 Server tidak terhubung</span>', unsafe_allow_html=True)

    st.divider()
    if st.button("🔃 Refresh", use_container_width=True):
        st.rerun()


# ── Guard: server harus terhubung ─────────────────────────────────────────────
if not st.session_state.server_url:
    st.warning(
        "### ⚙️ Isi URL Server di sidebar kiri\n\n"
        "1. Jalankan `Jalankan_Server.bat` di PC kamu\n"
        "2. Salin URL Cloudflare Tunnel yang muncul (contoh: `https://abc123.trycloudflare.com`)\n"
        "3. Paste di kolom **URL Server** di sidebar kiri"
    )
    st.stop()

if not connected:
    st.error(
        "### 🔴 Tidak bisa terhubung ke server\n\n"
        "Pastikan:\n"
        "- `Jalankan_Server.bat` sudah dijalankan di PC\n"
        "- URL tunnel sudah benar dan masih aktif\n"
        "- Firewall tidak memblokir\n\n"
        f"URL yang digunakan: `{st.session_state.server_url}`"
    )
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Status Pool Akun Claude")
    st.caption(f"Diperbarui: {datetime.now().strftime('%d %b %Y, %H:%M:%S')}")

    data, err = _get("/status")
    if err:
        st.error(err)
        st.stop()

    accounts = data.get("accounts", [])
    task_st  = data.get("task", {})
    auto_st  = data.get("auto", {})

    # Metrics
    ready_n = sum(1 for a in accounts if a["status"] == "READY")
    limit_n = len(accounts) - ready_n
    total_t = sum(a.get("total_tasks", 0) for a in accounts)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Akun Ready",    ready_n)
    c2.metric("🔴 Akun Cooldown", limit_n)
    c3.metric("📨 Total Task",    total_t)
    c4.metric("👥 Total Akun",    len(accounts))

    st.divider()

    # Account cards
    cols = st.columns(max(len(accounts), 1))
    for col, acc in zip(cols, accounts):
        is_ready = acc["status"] == "READY"
        with col:
            with st.container(border=True):
                st.markdown(f"**{acc['name']}**")
                if is_ready:
                    st.markdown('<span class="badge-ready">🟢 READY</span>', unsafe_allow_html=True)
                    st.caption("Siap menerima task")
                else:
                    st.markdown('<span class="badge-limit">🔴 COOLDOWN</span>', unsafe_allow_html=True)
                    st.caption(f"⏱ {acc.get('cooldown', '-')}")
                st.caption(f"✅ {acc.get('total_tasks', 0)} task selesai")

    st.divider()

    # Running process status
    col_t, col_a = st.columns(2)
    with col_t:
        with st.container(border=True):
            st.markdown("**🚀 Single Task**")
            if task_st.get("running"):
                st.success("⏳ Sedang berjalan ...")
            else:
                st.caption("Tidak ada task berjalan")

    with col_a:
        with st.container(border=True):
            st.markdown("**🔄 Auto Runner**")
            if auto_st.get("running"):
                cur = auto_st.get("iteration", 0)
                mx  = auto_st.get("max", 0)
                st.success(f"⏳ Iterasi {cur}/{mx}")
            else:
                st.caption("Tidak aktif")

    # Auto-refresh
    with st.expander("⚡ Auto-Refresh"):
        if st.checkbox("Refresh otomatis setiap 10 detik"):
            time.sleep(10)
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
            headless = st.checkbox("Headless (browser tersembunyi di PC)", value=True)

        submitted = st.form_submit_button("▶️ Jalankan", type="primary", use_container_width=True)

    if submitted and task_text.strip():
        result, err = _post("/task/run", {
            "task": task_text,
            "include_git": include_git,
            "headless": headless,
        })
        if err:
            st.error(err)
        else:
            st.session_state.task_polling = True
            st.success("✅ Task dimulai di PC!")
            st.rerun()

    # ── Polling result ──────────────────────────────────────────────
    if st.session_state.task_polling:
        data, err = _get("/task/result")
        if err:
            st.error(err)
        else:
            st.subheader("📟 Log Eksekusi (PC)")
            _render_log(data.get("logs", []))

            if data.get("running"):
                with st.spinner("Menunggu respons Claude ..."):
                    time.sleep(3)
                st.rerun()
            else:
                st.session_state.task_polling = False

                if data.get("result"):
                    st.success(f"✅ Selesai! Dijawab oleh: **{data.get('account','?')}**")
                    with st.expander("💬 Lihat Respons Claude", expanded=True):
                        st.markdown(data["result"])
                elif data.get("error"):
                    st.error(f"❌ {data['error']}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ AUTO RUNNER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Auto Runner":
    st.title("🔄 Auto Runner")
    st.info(
        "Auto Runner mengirim prompt berulang-ulang ke Claude, bergantian antar akun "
        "yang tersedia. Browser Playwright berjalan di PC lokal kamu.",
        icon="ℹ️"
    )

    # Get current auto state
    auto_data, _ = _get("/auto/logs")
    is_running = auto_data.get("running", False) if auto_data else False

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            max_iter    = st.number_input("Maksimum Iterasi", 1, 1000, 100, disabled=is_running)
            prompt_text = st.text_input("Prompt tiap iterasi", value="lanjut", disabled=is_running)
        with col2:
            headless_auto = st.checkbox("Headless", value=True, disabled=is_running)

        c_start, c_stop = st.columns(2)
        with c_start:
            start_btn = st.button("▶️ Mulai", disabled=is_running,
                                  type="primary", use_container_width=True)
        with c_stop:
            stop_btn = st.button("⏹️ Stop", disabled=not is_running,
                                 use_container_width=True)

    if start_btn:
        result, err = _post("/auto/start", {
            "max_iter": max_iter,
            "prompt": prompt_text,
            "headless": headless_auto,
        })
        if err:
            st.error(err)
        else:
            st.session_state.auto_polling = True
            st.success("🔄 Auto runner dimulai!")
            st.rerun()

    if stop_btn:
        result, err = _post("/auto/stop")
        if err:
            st.error(err)
        else:
            st.warning("⏹️ Stop signal terkirim.")
            st.session_state.auto_polling = False

    # ── Live logs polling ───────────────────────────────────────────
    if is_running or st.session_state.auto_polling or (auto_data and auto_data.get("logs")):
        if auto_data:
            cur = auto_data.get("iteration", 0)
            mx  = auto_data.get("max", 0)
            if mx > 0:
                st.progress(min(1.0, cur / mx), text=f"Iterasi {cur} / {mx}")

            st.subheader("📟 Log Auto Runner (PC)")
            _render_log(auto_data.get("logs", []), max_lines=100)

        if is_running:
            time.sleep(4)
            st.rerun()
        else:
            st.session_state.auto_polling = False


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ▸ RIWAYAT OUTPUT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📁 Riwayat Output":
    st.title("📁 Riwayat Output")

    files_data, err = _get("/outputs")
    if err:
        st.error(err)
        st.stop()

    if not files_data:
        st.info("Belum ada output. Jalankan task atau auto runner terlebih dahulu.")
    else:
        st.caption(f"📂 {len(files_data)} file output di PC")
        st.dataframe(files_data, use_container_width=True, hide_index=True)

        st.divider()
        filenames = [f["name"] for f in files_data]
        selected = st.selectbox("Buka file", filenames)

        if selected:
            content_data, err2 = _get(f"/outputs/{selected}")
            if err2:
                st.error(err2)
            else:
                content = content_data.get("content", "")
                col1, col2 = st.columns([5, 1])
                with col2:
                    st.download_button(
                        "⬇️ Download",
                        data=content,
                        file_name=selected,
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

    cfg_data, err = _get("/config")
    if err:
        st.error(err)
        st.stop()

    st.subheader("🔧 Pengaturan Umum")
    col1, col2 = st.columns(2)
    with col1:
        repo_path    = st.text_input("📁 Path Repository Git (di PC)", value=cfg_data.get("repo_path", ""))
        cooldown_hrs = st.number_input("⏱️ Cooldown per akun (jam)",
                                        value=float(cfg_data.get("cooldown_hours", 5.0)),
                                        min_value=0.5, step=0.5)
    with col2:
        github_pat   = st.text_input("🔑 GitHub PAT (opsional)", value="", type="password",
                                      placeholder="Kosongkan jika tidak ingin mengubah")
        headless_cfg = st.checkbox("🖥️ Headless mode", value=cfg_data.get("headless", False))

    st.subheader("👥 Akun Claude")
    accounts = cfg_data.get("accounts", [])
    updated_accounts = []
    for acc in accounts:
        with st.expander(f"Akun #{acc['id']} — {acc.get('name', '')}"):
            a_name = st.text_input("Nama", value=acc.get("name", ""), key=f"n_{acc['id']}")
            a_url  = st.text_input("URL Chat TAPIR", value=acc.get("tapir_chat_url", ""), key=f"u_{acc['id']}")
            updated_accounts.append({**acc, "name": a_name, "tapir_chat_url": a_url})

    if st.button("💾 Simpan ke PC", type="primary", use_container_width=True):
        new_cfg = {
            **cfg_data,
            "repo_path":      repo_path,
            "cooldown_hours": cooldown_hrs,
            "github_pat":     github_pat,
            "headless":       headless_cfg,
            "accounts":       updated_accounts,
        }
        result, err2 = _post("/config", new_cfg) if hasattr(requests, "put") else (None, None)
        # Use PUT
        try:
            r = requests.put(_url("/config"), json=new_cfg, timeout=8)
            r.raise_for_status()
            st.success("✅ Konfigurasi disimpan ke PC!")
        except Exception as e:
            st.error(f"Gagal menyimpan: {e}")

    st.divider()
    with st.expander("⚠️ Reset State Akun"):
        st.warning("Reset akan menghapus cooldown semua akun → semua jadi READY.")
        if st.button("🗑️ Reset State", type="secondary"):
            # Call a reset endpoint
            result, err2 = _post("/auto/stop")
            st.info("Silakan hapus `state.json` manual di PC dan restart server.")
