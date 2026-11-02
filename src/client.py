"""
Direct HTTP Client untuk Claude.ai internal API menggunakan curl_cffi.
Bypass TLS Cloudflare tanpa browser.
"""

import json
import re
import uuid
from typing import Optional, Tuple
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
        self.session_key = session_key.strip()
        if "sessionKey=" in self.session_key:
            m = re.search(r"sessionKey=([^;]+)", self.session_key)
            if m:
                self.session_key = m.group(1).strip()

        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/event-stream, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://claude.ai/chats",
            "Origin": "https://claude.ai",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
        self.session.cookies.set("sessionKey", self.session_key, domain="claude.ai")
        self.org_id: Optional[str] = None

    def test_connection(self) -> Tuple[bool, str]:
        try:
            org_id = self.get_organization_id()
            return True, f"Terkoneksi (Org: {org_id[:8]}...)"
        except ClaudeAuthError as e:
            return False, f"Auth Gagal: {e}"
        except Exception as e:
            return False, f"Error: {e}"

    def get_organization_id(self) -> str:
        if self.org_id:
            return self.org_id

        url = f"{self.BASE_URL}/api/organizations"
        try:
            resp = self.session.get(url, timeout=15)
        except Exception as e:
            raise ClaudeAPIError(f"Koneksi jaringan gagal: {e}")

        if resp.status_code in [401, 403]:
            raise ClaudeAuthError(f"sessionKey tidak valid atau kedaluwarsa (HTTP {resp.status_code}).")

        if resp.status_code != 200:
            raise ClaudeAPIError(f"Gagal mengambil organisasi: HTTP {resp.status_code}")

        try:
            orgs = resp.json()
            if not orgs or not isinstance(orgs, list):
                raise ClaudeAuthError("Tidak ada organisasi yang ditemukan.")
            self.org_id = orgs[0]["uuid"]
            return self.org_id
        except Exception as e:
            raise ClaudeAPIError(f"Format respon organisasi tidak valid: {e}")

    def create_conversation(self, title: str = "TAPIR Orchestrator") -> str:
        org_id = self.get_organization_id()
        chat_uuid = str(uuid.uuid4())
        url = f"{self.BASE_URL}/api/organizations/{org_id}/chat_conversations"
        payload = {"uuid": chat_uuid, "name": title}
        resp = self.session.post(url, json=payload, timeout=15)
        if resp.status_code in [200, 201]:
            return chat_uuid
        raise ClaudeAPIError(f"Gagal membuat thread percakapan: HTTP {resp.status_code}")

    def send_message(self, prompt: str, conversation_uuid: Optional[str] = None) -> str:
        org_id = self.get_organization_id()

        if conversation_uuid:
            if "chat/" in conversation_uuid:
                conversation_uuid = conversation_uuid.split("chat/")[-1].split("?")[0].strip("/")
            conversation_uuid = conversation_uuid.strip()

        if not conversation_uuid:
            conversation_uuid = self.create_conversation(title="TAPIR Orchestrator")

        url = f"{self.BASE_URL}/api/organizations/{org_id}/chat_conversations/{conversation_uuid}/completion"
        payload = {
            "prompt": prompt,
            "timezone": "Asia/Jakarta",
            "model": "claude-3-5-sonnet-20241022",
            "rendering_mode": "messages",
            "attachments": [],
            "files": []
        }

        try:
            resp = self.session.post(url, json=payload, stream=True, timeout=180)
        except Exception as e:
            raise ClaudeAPIError(f"Request ke claude.ai gagal: {e}")

        if resp.status_code in [401, 403]:
            raise ClaudeAuthError(f"Autentikasi gagal / sessionKey hangus (HTTP {resp.status_code}).")

        if resp.status_code == 429:
            reset_secs = 5 * 3600
            try:
                msg = resp.text.lower()
                m = re.search(r"(\d+)\s+hour", msg)
                if m:
                    reset_secs = int(m.group(1)) * 3600
            except Exception:
                pass
            raise ClaudeRateLimitError("Akun mencapai batas kuota (HTTP 429).", reset_seconds=reset_secs)

        if resp.status_code not in [200, 201]:
            raise ClaudeAPIError(f"Claude mengembalikan HTTP {resp.status_code}: {resp.text[:300]}")

        full_text = []
        is_rate_limited = False
        rate_limit_reason = ""

        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else line

                if line_str.startswith("data: "):
                    raw_data = line_str[6:].strip()
                    if raw_data == "[DONE]":
                        break

                    try:
                        data = json.loads(raw_data)
                        if "completion" in data:
                            full_text.append(data["completion"])
                        elif "text" in data:
                            full_text.append(data["text"])

                        if data.get("type") == "error":
                            err_info = data.get("error", {})
                            err_msg = err_info.get("message", "")
                            if "limit" in err_msg.lower() or "resets" in err_msg.lower() or err_info.get("type") == "rate_limit_error":
                                is_rate_limited = True
                                rate_limit_reason = err_msg
                                break
                            else:
                                raise ClaudeAPIError(f"Claude Stream Error: {err_msg}")
                    except json.JSONDecodeError:
                        continue
        except ClaudeAPIError:
            raise
        except Exception as e:
            if not full_text:
                raise ClaudeAPIError(f"Gagal memproses stream: {e}")

        if is_rate_limited:
            reset_secs = 5 * 3600
            m = re.search(r"(\d+)\s+hour", rate_limit_reason.lower())
            if m:
                reset_secs = int(m.group(1)) * 3600
            raise ClaudeRateLimitError(f"Rate limit terdeteksi dalam stream: {rate_limit_reason}", reset_seconds=reset_secs)

        result = "".join(full_text).strip()
        patterns = [
            r"you(?:'ve| have) reached your (?:free )?(?:message )?limit",
            r"out of free messages until",
            r"free message limit",
            r"resets at \d+:\d+",
            r"resets in \d+ (?:hour|minute)",
        ]
        for pat in patterns:
            if re.search(pat, result.lower()):
                raise ClaudeRateLimitError("Pesan limit terdeteksi dalam jawaban Claude.", reset_seconds=5 * 3600)

        if not result:
            raise ClaudeAPIError("Claude mengembalikan respons kosong.")

        return result
