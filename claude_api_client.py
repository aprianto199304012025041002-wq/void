"""
Direct HTTP Client untuk Claude.ai internal API menggunakan curl_cffi.
Bypass TLS fingerprinting Cloudflare tanpa perlu Playwright atau browser!
"""

import json
import re
import time
from typing import Optional, Tuple, Dict, Any
from curl_cffi import requests

class ClaudeAPIError(Exception):
    pass

class ClaudeRateLimitError(Exception):
    def __init__(self, message: str, reset_seconds: Optional[int] = None):
        super().__init__(message)
        self.reset_seconds = reset_seconds

class ClaudeAuthError(Exception):
    pass

class ClaudeWebClient:
    BASE_URL = "https://claude.ai"
    
    def __init__(self, session_key: str):
        """
        session_key: Nilai cookie 'sessionKey' dari claude.ai (dimulai dengan 'sk-ant-sid01-...')
        """
        self.session_key = session_key.strip()
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://claude.ai/chats",
            "Origin": "https://claude.ai",
        })
        self.session.cookies.set("sessionKey", self.session_key, domain="claude.ai")
        self.org_id: Optional[str] = None

    def get_organization_id(self) -> str:
        """Mengambil ID organisasi user saat ini."""
        if self.org_id:
            return self.org_id
            
        url = f"{self.BASE_URL}/api/organizations"
        resp = self.session.get(url, timeout=15)
        
        if resp.status_code == 401 or resp.status_code == 403:
            raise ClaudeAuthError(f"Session key tidak valid atau kedaluwarsa (HTTP {resp.status_code}).")
            
        if resp.status_code != 200:
            raise ClaudeAPIError(f"Gagal mengambil organisasi: HTTP {resp.status_code} - {resp.text}")
            
        orgs = resp.json()
        if not orgs or not isinstance(orgs, list):
            raise ClaudeAuthError("Tidak ada organisasi yang ditemukan untuk akun ini.")
            
        self.org_id = orgs[0]["uuid"]
        return self.org_id

    def list_conversations(self) -> list:
        org_id = self.get_organization_id()
        url = f"{self.BASE_URL}/api/organizations/{org_id}/chat_conversations"
        resp = self.session.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return []

    def create_conversation(self, title: str = "Chat") -> str:
        org_id = self.get_organization_id()
        import uuid
        chat_uuid = str(uuid.uuid4())
        url = f"{self.BASE_URL}/api/organizations/{org_id}/chat_conversations"
        payload = {
            "uuid": chat_uuid,
            "name": title
        }
        resp = self.session.post(url, json=payload, timeout=15)
        if resp.status_code in [200, 201]:
            return chat_uuid
        raise ClaudeAPIError(f"Gagal membuat percakapan: HTTP {resp.status_code} - {resp.text}")

    def send_message(self, prompt: str, conversation_uuid: Optional[str] = None) -> str:
        """
        Mengirim prompt ke Claude dan menerima teks streaming respons sampai selesai.
        """
        org_id = self.get_organization_id()
        
        # Jika chat_uuid tidak diberikan atau berupa URL, ekstrak uuid-nya
        if conversation_uuid and "chat/" in conversation_uuid:
            conversation_uuid = conversation_uuid.split("chat/")[-1].strip("/")
            
        if not conversation_uuid:
            conversation_uuid = self.create_conversation(title="TAPIR")

        url = f"{self.BASE_URL}/api/organizations/{org_id}/chat_conversations/{conversation_uuid}/completion"
        
        payload = {
            "prompt": prompt,
            "timezone": "Asia/Jakarta",
            "model": "claude-3-7-sonnet-latest",
            "rendering_mode": "messages"
        }
        
        resp = self.session.post(url, json=payload, stream=True, timeout=120)
        
        if resp.status_code == 429:
            # Rate limit terdeteksi
            reset_secs = 5 * 3600
            try:
                err_data = resp.json()
                msg = err_data.get("error", {}).get("message", "")
                # Deteksi waktu reset jika ada
                m = re.search(r"(\d+)\s+hour", msg)
                if m:
                    reset_secs = int(m.group(1)) * 3600
            except Exception:
                pass
            raise ClaudeRateLimitError("Rate limit / kuota 5 jam tercapai pada akun ini.", reset_seconds=reset_secs)
            
        if resp.status_code in [401, 403]:
            raise ClaudeAuthError(f"Autentikasi gagal atau sessionKey hangus (HTTP {resp.status_code}).")
            
        if resp.status_code != 200:
            raise ClaudeAPIError(f"Error mengirim pesan: HTTP {resp.status_code} - {resp.text}")

        # Parsing SSE response
        full_text = []
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8") if isinstance(line, bytes) else line
            if line_str.startswith("data: "):
                raw_json = line_str[6:].strip()
                if raw_json == "[DONE]":
                    break
                try:
                    data = json.loads(raw_json)
                    # format completions SSE Claude
                    if "completion" in data:
                        full_text.append(data["completion"])
                except Exception:
                    continue

        result = "".join(full_text).strip()
        if not result:
            # Fallback jika Claude mengembalikan full json biasa bukan event-stream
            try:
                data = resp.json()
                result = data.get("completion", "") or data.get("text", "")
            except Exception:
                pass
                
        return result
