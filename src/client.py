"""
Official Anthropic API Client for Cloud-Native Execution.
100% Bebas Cloudflare WAF • Resmi Didukung di Streamlit Cloud.
"""

from typing import Optional, Tuple
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

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key.strip()
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

    def test_connection(self) -> Tuple[bool, str]:
        """Tes validitas API Key dengan request minimal."""
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
                return False, "HTTP 401 (API Key Salah / Tidak Valid)"
            elif resp.status_code == 429:
                return False, "HTTP 429 (Rate Limit / Saldo Habis)"
            else:
                err_msg = resp.json().get("error", {}).get("message", resp.text[:40])
                return False, f"Err {resp.status_code}: {err_msg}"
        except Exception as e:
            return False, f"Network Err: {str(e)[:40]}"

    def send_message(self, prompt: str, conversation_uuid: Optional[str] = None) -> str:
        """Mengirim prompt ke model Claude resmi."""
        # Menggunakan model Claude 3.5 Sonnet terbaru, atau fallback ke Haiku jika hemat token
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            resp = requests.post(self.API_URL, headers=self.headers, json=payload, timeout=180)
        except Exception as e:
            raise ClaudeAPIError(f"Gagal mengirim request ke Anthropic: {e}")

        if resp.status_code == 401:
            raise ClaudeAuthError("API Key tidak valid atau dinonaktifkan.")

        if resp.status_code == 429:
            raise ClaudeRateLimitError("Rate limit / kuota token tercapai pada API Key ini.", reset_seconds=3600)

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
            raise ClaudeAPIError(f"Gagal memproses jawaban dari Anthropic: {e}")
