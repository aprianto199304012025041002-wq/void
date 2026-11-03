"""
Pool Manager — mengelola rotasi akun Claude free web.
Membaca konfigurasi dari config.json dan menginjeksi
session keys dari st.secrets (Streamlit Cloud).
"""

import json
import os
import time
import threading
from typing import Dict, List, Optional, Any

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

# Status akun
STATUS_READY    = "ready"
STATUS_WORKING  = "working"
STATUS_COOLDOWN = "cooldown"
STATUS_ERROR    = "error"

# Cooldown 5 jam (18000 detik)
COOLDOWN_SECONDS = 18_000


def _load_secrets() -> dict:
    """Ambil secrets dari st.secrets jika tersedia, fallback ke env vars."""
    out = {}
    if _HAS_ST:
        try:
            for k in st.secrets:
                out[k] = st.secrets[k]
            return out
        except Exception:
            pass
    # Fallback: environment variables
    for k in ["MODEL_PROVIDER", "SESSION_KEY_1", "SESSION_KEY_2",
              "SESSION_KEY_3", "SESSION_KEY_4",
              "TAPIR_CONV_1", "TAPIR_CONV_2", "TAPIR_CONV_3", "TAPIR_CONV_4"]:
        v = os.environ.get(k)
        if v:
            out[k] = v
    return out


class AccountNode:
    """Representasi satu akun Claude dalam pool."""

    def __init__(self, data: dict):
        self.id: str           = data.get("id", "")
        self.label: str        = data.get("label", self.id)
        self.session_key: str  = data.get("session_key", "")
        self.conv_id: str      = data.get("tapir_conv_id", data.get("conv_id", ""))
        self.org_id: Optional[str] = data.get("org_id", None)

        self.status: str       = STATUS_READY if self.session_key else STATUS_ERROR
        self.cooldown_until: float = 0.0
        self.total_sent: int   = data.get("total_sent", 0)
        self.last_response: str = ""
        self.error_msg: str    = ""
        self._lock             = threading.Lock()

    @property
    def is_ready(self) -> bool:
        if self.status == STATUS_COOLDOWN:
            if time.time() >= self.cooldown_until:
                self.status = STATUS_READY
        return self.status == STATUS_READY and bool(self.session_key)

    @property
    def cooldown_remaining(self) -> int:
        """Sisa cooldown dalam detik."""
        if self.status != STATUS_COOLDOWN:
            return 0
        return max(0, int(self.cooldown_until - time.time()))

    def mark_working(self):
        with self._lock:
            self.status = STATUS_WORKING

    def mark_ready(self):
        with self._lock:
            self.status = STATUS_READY
            self.error_msg = ""

    def mark_cooldown(self):
        with self._lock:
            self.status = STATUS_COOLDOWN
            self.cooldown_until = time.time() + COOLDOWN_SECONDS

    def mark_error(self, msg: str = ""):
        with self._lock:
            self.status = STATUS_ERROR
            self.error_msg = msg

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "session_key": self.session_key,
            "tapir_conv_id": self.conv_id,
            "org_id": self.org_id,
            "status": self.status,
            "cooldown_remaining": self.cooldown_remaining,
            "total_sent": self.total_sent,
            "last_response": self.last_response[-200:] if self.last_response else "",
            "error_msg": self.error_msg,
        }


class ClusterPool:
    """
    Pool manager untuk rotasi akun Claude free web.
    Thread-safe. Mendukung Streamlit Cloud via st.secrets.
    """

    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")

    def __init__(self):
        self._lock   = threading.Lock()
        self.nodes: List[AccountNode] = []
        self.current_index: int = 0
        self.model_provider: str = "claude_web"
        self._load_config()

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self):
        """Load config.json lalu inject secrets dari Streamlit."""
        config = self._read_config_file()
        secrets = _load_secrets()

        self.model_provider = secrets.get("MODEL_PROVIDER", "claude_web")

        accounts_raw: List[dict] = config.get("accounts", [])

        # Inject session keys & conv IDs dari secrets
        for i, acc in enumerate(accounts_raw, start=1):
            sk  = secrets.get(f"SESSION_KEY_{i}", acc.get("session_key", ""))
            cid = secrets.get(f"TAPIR_CONV_{i}", acc.get("tapir_conv_id", acc.get("conv_id", "")))
            if sk:
                acc["session_key"]  = sk
            if cid:
                acc["tapir_conv_id"] = cid

        self.nodes = [AccountNode(a) for a in accounts_raw]

    def _read_config_file(self) -> dict:
        try:
            path = self.CONFIG_PATH
            if not os.path.exists(path):
                # Fallback: cari config.json di direktori kerja
                path = "config.json"
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # Default kosong — semua akan diisi dari secrets
            return {
                "accounts": [
                    {"id": f"akun{i}", "label": f"Akun {i}", "session_key": "", "tapir_conv_id": ""}
                    for i in range(1, 5)
                ]
            }

    def reload(self):
        """Reload config (e.g., setelah user update secrets)."""
        with self._lock:
            self._load_config()

    # ------------------------------------------------------------------
    # Node selection
    # ------------------------------------------------------------------

    def get_ready_node(self) -> Optional[AccountNode]:
        """Round-robin pilih node yang ready. Return None jika semua cooldown/error."""
        with self._lock:
            n = len(self.nodes)
            for _ in range(n):
                node = self.nodes[self.current_index % n]
                self.current_index = (self.current_index + 1) % n
                if node.is_ready:
                    return node
            return None

    def get_node_by_id(self, node_id: str) -> Optional[AccountNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        ready    = [n for n in self.nodes if n.is_ready]
        cooldown = [n for n in self.nodes if n.status == STATUS_COOLDOWN]
        working  = [n for n in self.nodes if n.status == STATUS_WORKING]
        error    = [n for n in self.nodes if n.status == STATUS_ERROR]

        return {
            "total":    len(self.nodes),
            "ready":    len(ready),
            "working":  len(working),
            "cooldown": len(cooldown),
            "error":    len(error),
            "nodes":    [n.to_dict() for n in self.nodes],
            "provider": self.model_provider,
        }

    def all_exhausted(self) -> bool:
        return all(not n.is_ready for n in self.nodes)

    def min_cooldown_remaining(self) -> int:
        cd_nodes = [n for n in self.nodes if n.status == STATUS_COOLDOWN]
        if not cd_nodes:
            return 0
        return min(n.cooldown_remaining for n in cd_nodes)
