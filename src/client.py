"""
AI Client Engine — Google Gemini & Groq REST APIs
Menggunakan Python Standard Library (urllib) + fallback requests.
Mendukung multi-turn conversation memory, auto-model fallback (503/404 handling),
dan deteksi Rate Limit (429) untuk auto-failover antar akun/key.
Zero-Dependency, 100% kompatibel dengan Python 3.10 - 3.14+.
"""

import json
import time
import urllib.request
import urllib.error
from typing import List, Dict, Tuple, Optional


class AIRateLimitError(Exception):
    """Kena 429 Resource Exhausted / TPM / RPM limit"""
    pass


class AIAuthError(Exception):
    """API Key invalid / unauthorized (401 / 403)"""
    pass


def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 60) -> Tuple[int, str]:
    """Helper HTTP POST JSON menggunakan urllib bawaan (zero external dependencies)."""
    hdrs = {
        "Content-Type": "application/json",
        "User-Agent": "AntigravityOrchestrator/2.0"
    }
    if headers:
        hdrs.update(headers)

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=hdrs, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return e.code, err_body
    except Exception as e:
        raise Exception(f"Network error: {e}")


class BaseAIClient:
    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        raise NotImplementedError

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError


# ────────────────────────────────────────────────────────────────
# Google Gemini Client (Official v1beta REST via urllib)
# ────────────────────────────────────────────────────────────────
class GeminiClient(BaseAIClient):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    FALLBACK_MODELS = [
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest"
    ]

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self.api_key = api_key
        if model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"):
            self.model = "gemini-3-flash-preview"
        else:
            self.model = model or "gemini-3-flash-preview"

    def _convert_history(self, history: List[Dict[str, str]], prompt: str) -> List[dict]:
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })
        return contents

    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        contents = self._convert_history(history, prompt)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096,
            }
        }

        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]

        last_error = ""
        for m in models_to_try:
            url = f"{self.BASE_URL}/{m}:generateContent?key={self.api_key}"
            try:
                code, body = _http_post_json(url, payload, timeout=60)
            except Exception as e:
                raise AIAuthError(f"Koneksi gagal ke Gemini: {e}")

            if code == 200:
                self.model = m
                try:
                    data = json.loads(body)
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in parts)
                    fb = data.get("promptFeedback", {})
                    return f"[Feedback: {fb}]"
                except Exception as e:
                    raise Exception(f"Gagal parse JSON Gemini: {e}")

            elif code == 429:
                raise AIRateLimitError("Gemini Quota Exceeded (429).")
            elif code in (401, 403):
                raise AIAuthError(f"Gemini Auth Gagal ({code}): {body[:200]}")
            elif code in (404, 503):
                last_error = f"Model {m} status {code}"
                continue
            else:
                last_error = f"HTTP {code}: {body[:200]}"
                break

        raise Exception(f"Semua model Gemini gagal: {last_error}")

    def test_connection(self) -> Tuple[bool, str]:
        models_to_test = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        for m in models_to_test:
            url = f"{self.BASE_URL}/{m}:generateContent?key={self.api_key}"
            payload = {"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}
            try:
                code, body = _http_post_json(url, payload, timeout=12)
                if code == 200:
                    self.model = m
                    return True, f"✅ Gemini OK ({m})"
                elif code == 429:
                    return False, "⏳ Gemini Rate Limited (429)"
            except Exception:
                pass
        return False, f"❌ Gemini Connection Failed (Periksa API Key)"


# ────────────────────────────────────────────────────────────────
# Groq Client (Official OpenAI-Compatible REST via urllib)
# ────────────────────────────────────────────────────────────────
class GroqClient(BaseAIClient):
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
    FALLBACK_MODELS = [
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]

    def __init__(self, api_key: str, model: str = "qwen/qwen3.8-27b"):
        self.api_key = api_key
        if not model or "llama" in model.lower():
            self.model = "qwen/qwen3.8-27b"
        else:
            self.model = model

    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        messages = list(history)
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]

        last_error = ""
        for m in models_to_try:
            payload = {
                "model": m,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 4096,
            }

            try:
                code, body = _http_post_json(self.BASE_URL, payload, headers=headers, timeout=90)
            except Exception as e:
                raise AIAuthError(f"Gagal koneksi ke Groq: {e}")

            if code == 200:
                self.model = m
                try:
                    data = json.loads(body)
                    choice = data["choices"][0]
                    content = choice.get("message", {}).get("content", "")
                    if content:
                        return content
                    reasoning = choice.get("message", {}).get("reasoning", "")
                    return reasoning if reasoning else "[Empty response]"
                except Exception as e:
                    raise Exception(f"Gagal parse respons Groq: {e}")

            elif code == 429:
                raise AIRateLimitError("Groq Rate Limit Reached (429 TPM/RPM).")
            elif code in (401, 403):
                raise AIAuthError(f"Groq Auth Error ({code}): {body[:200]}")
            elif code == 404:
                last_error = f"Model {m} not found (404)"
                continue
            else:
                last_error = f"Groq HTTP {code}: {body[:200]}"
                break

        raise Exception(f"Semua model Groq gagal: {last_error}")

    def test_connection(self) -> Tuple[bool, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        models_to_test = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        for m in models_to_test:
            payload = {
                "model": m,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 10
            }
            try:
                code, body = _http_post_json(self.BASE_URL, payload, headers=headers, timeout=12)
                if code == 200:
                    self.model = m
                    return True, f"✅ Groq OK ({m})"
                elif code == 429:
                    return False, "⏳ Groq Rate Limited (429)"
            except Exception:
                pass
        return False, f"❌ Groq Connection Failed (Periksa API Key)"


def get_ai_client(provider: str, api_key: str, model: Optional[str] = None) -> BaseAIClient:
    provider_lower = (provider or "").strip().lower()
    if "groq" in provider_lower:
        return GroqClient(api_key=api_key, model=model or "qwen/qwen3.8-27b")
    else:
        return GeminiClient(api_key=api_key, model=model or "gemini-3-flash-preview")
