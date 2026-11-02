"""
Official Anthropic API Client with Stateful Conversation Memory.
Mendukung looping 'lanjut' dengan konteks percakapan bersambung.
"""

from typing import Optional, Tuple, List, Dict
import requests

class ClaudeAPIError(Exception):
    pass

class ClaudeRateLimitError(Exception):
    def __init__(self, message: str, reset_seconds: Optional[int] = None):
        super().__init__(message)
        self.reset_seconds = reset_seconds

class ClaudeAuthError(Exception):
    pass

class ClaudeWebClient:
    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key.strip()
        self.model = model
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

    def test_connection(self) -> Tuple[bool, str]:
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "ping"}]
        }
        try:
            resp = requests.post(self.API_URL, headers=self.headers, json=payload, timeout=12)
            if resp.status_code == 200:
                return True, "API Key Valid & Terhubung"
            elif resp.status_code == 401:
                return False, "HTTP 401 (API Key Salah)"
            elif resp.status_code == 429:
                return False, "HTTP 429 (Rate Limit / Saldo Habis)"
            else:
                err_msg = resp.json().get("error", {}).get("message", resp.text[:40])
                return False, f"Err {resp.status_code}: {err_msg}"
        except Exception as e:
            return False, f"Network Err: {str(e)[:40]}"

    def send_conversation(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        """
        Mengirim percakapan multi-turn lengkap (user & assistant)
        sehingga Claude bisa merespons 'lanjut' secara bersambung!
        """
        # Batasi riwayat maksimal 10 pertukaran terakhir agar tidak over-token
        trimmed_messages = messages[-10:] if len(messages) > 10 else messages

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": trimmed_messages
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = requests.post(self.API_URL, headers=self.headers, json=payload, timeout=180)
        except Exception as e:
            raise ClaudeAPIError(f"Request gagal: {e}")

        if resp.status_code == 401:
            raise ClaudeAuthError("API Key tidak valid.")

        if resp.status_code == 429:
            raise ClaudeRateLimitError("Rate limit / saldo habis pada key ini.", reset_seconds=3600)

        if resp.status_code != 200:
            err_detail = ""
            try:
                err_detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                err_detail = resp.text[:200]
            raise ClaudeAPIError(f"Anthropic API Error ({resp.status_code}): {err_detail}")

        try:
            data = resp.json()
            content_blocks = data.get("content", [])
            full_text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            return full_text.strip()
        except Exception as e:
            raise ClaudeAPIError(f"Gagal memproses data jawaban: {e}")
