"""
Cyberpunk Ultra-Compact High-Density CSS
"""

import streamlit as st

def inject_styles():
    st.markdown("""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

    <style>
    /* Streamlit Cloud top bar fix so content is NEVER cut off */
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 2.8rem !important;
    }
    .block-container {
        padding-top: 3.2rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 100% !important;
    }
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
        color: #CBD5E1;
    }
    code, pre, .mono {
        font-family: 'Fira Code', monospace !important;
    }

    /* Background */
    .stApp {
        background-color: #06090E;
    }

    /* Compact Top Header Bar */
    .compact-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 16px;
        background: #0B111A;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        margin-bottom: 10px;
    }
    .compact-header .title-badge {
        display: flex;
        align-items: center;
        gap: 10px;
        font-family: 'Fira Code', monospace;
        font-size: 0.85rem;
        font-weight: 700;
        color: #38BDF8;
    }
    .compact-header .stats-inline {
        display: flex;
        gap: 16px;
        font-family: 'Fira Code', monospace;
        font-size: 0.75rem;
        color: #94A3B8;
    }
    .compact-header .stats-inline span {
        font-weight: 600;
    }

    /* Micro Node Cards */
    .micro-node {
        background: #0B111A;
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 6px;
        padding: 6px 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        font-family: 'Fira Code', monospace;
        font-size: 0.75rem;
    }
    .micro-node.ready { border-left: 3px solid #10B981; }
    .micro-node.limit { border-left: 3px solid #F43F5E; }
    .micro-node.nokey { border-left: 3px solid #F59E0B; }

    .pulse-dot {
        display: inline-block;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        margin-right: 5px;
    }
    .dot-green { background: #10B981; box-shadow: 0 0 6px #10B981; }
    .dot-red   { background: #F43F5E; box-shadow: 0 0 6px #F43F5E; }
    .dot-amber { background: #F59E0B; }

    /* Ultra-Compact Terminal */
    .term-box {
        background: #04060A;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        height: 510px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
    .term-head {
        background: #0B111A;
        padding: 6px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: 'Fira Code', monospace;
        font-size: 0.7rem;
        color: #64748B;
    }
    .term-body {
        padding: 10px 14px;
        overflow-y: auto;
        font-family: 'Fira Code', monospace;
        font-size: 0.75rem;
        line-height: 1.6;
        color: #94A3B8;
        flex-grow: 1;
    }
    .row-log { display: flex; gap: 8px; margin-bottom: 2px; }
    .ts { color: #475569; }
    .c-info { color: #38BDF8; font-weight: 600; }
    .c-succ { color: #34D399; font-weight: 600; }
    .c-warn { color: #FBBF24; font-weight: 600; }
    .c-err  { color: #F87171; font-weight: 600; }
    .c-loop { color: #818CF8; font-weight: 600; }

    /* Auth Gate Card */
    .auth-box {
        max-width: 400px;
        margin: 80px auto;
        background: #0B111A;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 28px;
        text-align: center;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8);
    }
    </style>
    """, unsafe_allow_html=True)
