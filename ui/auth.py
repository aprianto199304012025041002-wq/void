"""
Security Gatekeeper Authentication Component.
Memvalidasi password terhadap st.secrets['pw'].
"""

import streamlit as st

def require_auth() -> bool:
    target_pw = None
    try:
        if hasattr(st, "secrets") and "pw" in st.secrets:
            target_pw = st.secrets["pw"]
    except Exception:
        pass

    # Lewati jika user belum mengatur secrets pw
    if not target_pw:
        return True

    if st.session_state.get("authenticated", False):
        return True

    st.markdown("""
    <div class="auth-box">
        <div style="font-size: 1.8rem; margin-bottom: 8px;">🔐</div>
        <div style="font-family: 'Fira Code', monospace; font-size: 0.95rem; font-weight: 700; color: #38BDF8; letter-spacing: 0.05em;">SECURE CLUSTER GATEWAY</div>
        <div style="font-size: 0.75rem; color: #64748B; margin-top: 4px; margin-bottom: 20px;">AUTHENTICATION REQUIRED TO ACCESS NODES</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        input_pass = st.text_input("Access Key", type="password", placeholder="Enter cluster password...", label_visibility="collapsed")
        if st.button("Unlock Console", type="primary", use_container_width=True):
            if input_pass == str(target_pw):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid Access Key.")
    return False

# Alias untuk backward compatibility
check_auth = require_auth
