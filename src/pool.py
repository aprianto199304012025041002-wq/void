"""
Pool Manager — Mengelola node API Key untuk Google Gemini & Groq.
Mendukung Single-Key maupun Multi-Key pooling dari st.secrets.
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

STATUS_READY    = "ready"
STATUS_WORKING  = "working"
STATUS_COOLDOWN = "cooldown"
STATUS_ERROR    = "error"

# Cooldown default untuk API rate-limit (60 detik untuk rotasi TPM/RPM)
DEFAULT_COOLDOWN_SECONDS = 60


def _load_all_secrets() -> dict:
    """Membaca semua secret dari st.secrets atau environment variables."""
    out = {}
    if _HAS_ST:
        try:
            for k in st.secrets:
                out[k] = st.secrets[k]
        except Exception:
            pass
    # Overwrite/tambah dari env vars jika ada
    for k, v in os.environ.items():
        if k not in out:
            out[k] = v
    return out


class KeyNode:
    """Representasi satu node / API Key dalam cluster."""

    def __init__(self, node_id: str, label: str, provider: str, api_key: str, model: str):
        self.id = node_id
        self.label = label
        self.provider = provider
        self.api_key = api_key
        self.model = model
        
        self.status = STATUS_READY if bool(api_key) else STATUS_ERROR
        self.cooldown_until: float = 0.0
        self.total_sent: int = 0
        self.last_response: str = ""
        self.error_msg: str = ""
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        if not self.api_key:
            return False
        if self.status == STATUS_COOLDOWN:
            if time.time() >= self.cooldown_until:
                self.status = STATUS_READY
        return self.status == STATUS_READY

    @property
    def cooldown_remaining(self) -> int:
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

    def mark_cooldown(self, seconds: int = DEFAULT_COOLDOWN_SECONDS):
        with self._lock:
            self.status = STATUS_COOLDOWN
            self.cooldown_until = time.time() + seconds

    def mark_error(self, msg: str = ""):
        with self._lock:
            self.status = STATUS_ERROR
            self.error_msg = msg

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "has_key": bool(self.api_key),
            "key_preview": f"{self.api_key[:6]}...{self.api_key[-4:]}" if len(self.api_key) > 10 else "—",
            "status": self.status,
            "cooldown_remaining": self.cooldown_remaining,
            "total_sent": self.total_sent,
            "last_response": self.last_response[-200:] if self.last_response else "",
            "error_msg": self.error_msg,
        }


class ClusterPool:
    """
    Cluster Pool Manager untuk mengelola rotasi API Key Gemini & Groq.
    Thread-safe & Reactive.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.nodes: List[KeyNode] = []
        self.current_index: int = 0
        self.active_provider: str = "gemini"
        self.active_model: str = "gemini-2.0-flash"
        self._load_nodes()

    def _load_nodes(self):
        secrets = _load_all_secrets()
        
        provider = secrets.get("MODEL_PROVIDER", "gemini").lower()
        self.active_provider = "groq" if "groq" in provider else "gemini"

        nodes: List[KeyNode] = []

        if self.active_provider == "groq":
            self.active_model = secrets.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            
            # Cek multi-key pooling GROQ_API_KEY_1..4
            multi_keys = []
            for i in range(1, 9):
                k = secrets.get(f"GROQ_API_KEY_{i}")
                if k:
                    multi_keys.append((f"groq_{i}", f"Groq Key #{i}", k))
            
            if multi_keys:
                for nid, lbl, k in multi_keys:
                    nodes.append(KeyNode(nid, lbl, "groq", k, self.active_model))
            else:
                # Single key fallback
                sk = secrets.get("GROQ_API_KEY", "")
                nodes.append(KeyNode("groq_1", "Groq Primary", "groq", sk, self.active_model))

        else: # Gemini
            self.active_model = secrets.get("GEMINI_MODEL", "gemini-2.0-flash")
            
            # Cek multi-key pooling GEMINI_API_KEY_1..4
            multi_keys = []
            for i in range(1, 9):
                k = secrets.get(f"GEMINI_API_KEY_{i}")
                if k:
                    multi_keys.append((f"gemini_{i}", f"Gemini Key #{i}", k))
                    
            if multi_keys:
                for nid, lbl, k in multi_keys:
                    nodes.append(KeyNode(nid, lbl, "gemini", k, self.active_model))
            else:
                # Single key fallback
                sk = secrets.get("GEMINI_API_KEY", "")
                nodes.append(KeyNode("gemini_1", "Gemini Primary", "gemini", sk, self.active_model))

        self.nodes = nodes

    def reload(self):
        with self._lock:
            self._load_nodes()

    def set_provider_and_model(self, provider: str, model: str):
        with self._lock:
            self.active_provider = provider
            self.active_model = model
            self._load_nodes()

    def get_ready_node(self) -> Optional[KeyNode]:
        """Round-robin memilih node yang berstatus ready."""
        with self._lock:
            n = len(self.nodes)
            if n == 0:
                return None
            for _ in range(n):
                node = self.nodes[self.current_index % n]
                self.current_index = (self.current_index + 1) % n
                if node.is_ready:
                    return node
            return None

    def get_node_by_id(self, node_id: str) -> Optional[KeyNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

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
            "provider": self.active_provider,
            "model":    self.active_model,
        }

    def all_exhausted(self) -> bool:
        return all(not n.is_ready for n in self.nodes)

    def min_cooldown_remaining(self) -> int:
        cd_nodes = [n for n in self.nodes if n.status == STATUS_COOLDOWN]
        if not cd_nodes:
            return 0
        return min(n.cooldown_remaining for n in cd_nodes)
