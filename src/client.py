"""
AI Client Engine — Google Gemini & Groq REST APIs
Mendukung multi-turn conversation memory, auto-model fallback (503/404 handling),
dan deteksi Rate Limit (429) untuk auto-failover antar akun/key.
"""

import json
import time
from typing import List, Dict, Tuple, Optional
import requests


class AIRateLimitError(Exception):
    """Kena 429 Resource Exhausted / TPM / RPM limit"""
    pass


class AIAuthError(Exception):
    """API Key invalid / unauthorized (401 / 403)"""
    pass


class BaseAIClient:
    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        raise NotImplementedError

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError


# ────────────────────────────────────────────────────────────────
# Google Gemini Client (Official v1beta REST)
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
        # Jika model lama (misal 2.0 atau 1.5) yang sudah deprecated, map ke model aktif
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
                resp = requests.post(url, json=payload, timeout=60)
            except Exception as e:
                raise AIAuthError(f"Koneksi gagal ke Gemini: {e}")

            if resp.status_code == 200:
                self.model = m
                data = resp.json()
                try:
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in parts)
                    fb = data.get("promptFeedback", {})
                    return f"[Feedback: {fb}]"
                except Exception as e:
                    raise Exception(f"Gagal parse JSON Gemini: {e}")

            elif resp.status_code == 429:
                raise AIRateLimitError("Gemini Quota Exceeded (429).")
            elif resp.status_code in (401, 403):
                raise AIAuthError(f"Gemini Auth Gagal ({resp.status_code}): {resp.text[:200]}")
            elif resp.status_code in (404, 503):
                last_error = f"Model {m} status {resp.status_code}"
                continue
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                break

        raise Exception(f"Semua model Gemini gagal: {last_error}")

    def test_connection(self) -> Tuple[bool, str]:
        models_to_test = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        for m in models_to_test:
            url = f"{self.BASE_URL}/{m}:generateContent?key={self.api_key}"
            payload = {"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}
            try:
                resp = requests.post(url, json=payload, timeout=12)
                if resp.status_code == 200:
                    self.model = m
                    return True, f"✅ Gemini OK ({m})"
                elif resp.status_code == 429:
                    return False, "⏳ Gemini Rate Limited (429)"
            except Exception:
                pass
        return False, f"❌ Gemini Connection Failed (Periksa API Key)"


# ────────────────────────────────────────────────────────────────
# Groq Client (Official OpenAI-Compatible REST)
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
        # Jika model lama/tidak tersedia, fallback ke model aktif
        if not model or "llama" in model.lower():
            self.model = "qwen/qwen3.8-27b"
        else:
            self.model = model

    def send_chat(self, history: List[Dict[str, str]], prompt: str) -> str:
        messages = list(history)
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
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
                resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=90)
            except Exception as e:
                raise AIAuthError(f"Gagal koneksi ke Groq: {e}")

            if resp.status_code == 200:
                self.model = m
                data = resp.json()
                try:
                    choice = data["choices"][0]
                    content = choice.get("message", {}).get("content", "")
                    if content:
                        return content
                    # Jika model reasoning dan content kosong di limit
                    reasoning = choice.get("message", {}).get("reasoning", "")
                    return reasoning if reasoning else "[Empty response]"
                except Exception as e:
                    raise Exception(f"Gagal parse respons Groq: {e}")

            elif resp.status_code == 429:
                raise AIRateLimitError("Groq Rate Limit Reached (429 TPM/RPM).")
            elif resp.status_code in (401, 403):
                raise AIAuthError(f"Groq Auth Error ({resp.status_code}): {resp.text[:200]}")
            elif resp.status_code == 404:
                last_error = f"Model {m} not found (404)"
                continue
            else:
                last_error = f"Groq HTTP {resp.status_code}: {resp.text[:200]}"
                break

        raise Exception(f"Semua model Groq gagal: {last_error}")

    def test_connection(self) -> Tuple[bool, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        models_to_test = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        for m in models_to_test:
            payload = {
                "model": m,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 10
            }
            try:
                resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=12)
                if resp.status_code == 200:
                    self.model = m
                    return True, f"✅ Groq OK ({m})"
                elif resp.status_code == 429:
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
