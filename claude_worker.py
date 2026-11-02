import os
import re
import time
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext


class ClaudeRateLimitError(Exception):
    def __init__(self, message: str, reset_seconds: Optional[int] = None):
        super().__init__(message)
        self.reset_seconds = reset_seconds


class ClaudeAuthError(Exception):
    pass


class ClaudeWorker:
    def __init__(self, account_config: dict, base_dir: str, headless: bool = False):
        self.account_id = account_config["id"]
        self.name = account_config.get("name", f"Account #{self.account_id}")
        self.profile_dir = os.path.join(base_dir, account_config["profile_dir"])
        self.chat_url = account_config.get("tapir_chat_url")
        self.headless = headless

    def _detect_rate_limit(self, page: Page) -> Tuple[bool, Optional[int]]:
        """
        Detects if Claude displayed a rate-limit or quota-exceeded message
        in the rendered UI (not in script tags).
        Returns (is_rate_limited, reset_seconds).
        """
        try:
            visible_text = page.inner_text("body").lower()
        except Exception:
            return False, None

        # Precise rate limit patterns in visible UI
        rate_limit_patterns = [
            r"you(?:'ve| have) reached your (?:free )?(?:message )?limit",
            r"out of free messages until",
            r"your limit will reset",
            r"free message limit",
            r"resets at \d+:\d+",
            r"resets in \d+ (?:hour|minute)",
            r"you are out of free messages",
        ]

        for pattern in rate_limit_patterns:
            if re.search(pattern, visible_text):
                reset_seconds = 5 * 3600  # Default 5 jam

                hour_match = re.search(r"in\s+(\d+)\s+hour", visible_text)
                min_match = re.search(r"in\s+(\d+)\s+min", visible_text)

                if hour_match or min_match:
                    h = int(hour_match.group(1)) if hour_match else 0
                    m = int(min_match.group(1)) if min_match else 0
                    parsed_secs = (h * 3600) + (m * 60)
                    if parsed_secs > 0:
                        reset_seconds = parsed_secs

                return True, reset_seconds

        return False, None

    def _dismiss_popups(self, page: Page):
        """Dismiss common modals or onboarding dialogs if present."""
        popup_selectors = [
            "button:has-text('Acknowledge')",
            "button:has-text('Got it')",
            "button:has-text('Accept')",
            "button:has-text('Continue')",
            "button[aria-label='Close']",
        ]
        for sel in popup_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    time.sleep(0.5)
            except Exception:
                pass

    def send_prompt(self, prompt: str, timeout_seconds: int = 300) -> str:
        """
        Opens the existing 'TAPIR' conversation for this account,
        sends the prompt, and extracts Claude's response.
        Raises ClaudeRateLimitError if 5-hour quota is reached.
        """
        target_url = self.chat_url or "https://claude.ai/chats"
        print(f"[{self.name}] Membuka percakapan 'TAPIR' di: {target_url}...")

        with sync_playwright() as p:
            context: BrowserContext = p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                channel="chrome",
                headless=self.headless,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                ],
                ignore_default_args=["--enable-automation"],
            )

            try:
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                try:
                    cdp = context.new_cdp_session(page)
                    cdp.send("Debugger.enable")
                    cdp.send("Debugger.setBreakpointsActive", {"active": False})
                except Exception:
                    pass

                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(4)

                # Check if redirected to login
                if "login" in page.url:
                    raise ClaudeAuthError(
                        f"[{self.name}] Sesi belum login. Buka shortcut Login Akun #{self.account_id} di Desktop terlebih dahulu."
                    )

                self._dismiss_popups(page)

                # If on /chats, click TAPIR link
                if "/chat/" not in page.url:
                    tapir_link = page.locator("a:has-text('TAPIR'), [data-testid*='chat']:has-text('TAPIR')").first
                    if tapir_link.is_visible(timeout=5000):
                        tapir_link.click()
                        time.sleep(3)

                # Check if already rate-limited
                is_limited, reset_secs = self._detect_rate_limit(page)
                if is_limited:
                    raise ClaudeRateLimitError(
                        f"[{self.name}] Akun sedang mencapai batas kuota 5 jam.",
                        reset_seconds=reset_secs,
                    )

                # Record current assistant message count
                msg_selector = '[data-message-author-role="assistant"], .font-claude-message, .standard-markdown'
                messages = page.locator(msg_selector)
                initial_msg_count = messages.count()
                print(f"[{self.name}] Jumlah riwayat pesan asisten: {initial_msg_count}")

                # Locate input box
                input_selector = 'div.ProseMirror[contenteditable="true"], div[contenteditable="true"], div[role="textbox"]'
                page.wait_for_selector(input_selector, timeout=20000)
                input_box = page.locator(input_selector).first

                print(f"[{self.name}] Mengirim perintah: '{prompt}' ke 'TAPIR'...")
                input_box.click()

                try:
                    page.evaluate(
                        """([selector, text]) => {
                            const el = document.querySelector(selector);
                            if (el) {
                                el.focus();
                                document.execCommand('insertText', false, text);
                            }
                        }""",
                        [input_selector, prompt],
                    )
                except Exception:
                    input_box.fill(prompt)

                time.sleep(1)

                # Click send
                send_button = page.locator('button[aria-label="Send Message"], button[aria-label="Send message"], button:has(svg[viewBox*="24"])').first
                if send_button.is_visible(timeout=2000):
                    send_button.click()
                else:
                    page.keyboard.press("Enter")

                print(f"[{self.name}] Perintah '{prompt}' terkirim! Menunggu Claude merespons...")
                time.sleep(5)

                # Check if rate limit triggered upon sending
                is_limited, reset_secs = self._detect_rate_limit(page)
                if is_limited:
                    raise ClaudeRateLimitError(
                        f"[{self.name}] Kuota 5 jam habis setelah mengirim pesan.",
                        reset_seconds=reset_secs,
                    )

                # Wait for response completion
                start_time = time.time()
                last_text_length = 0
                stagnant_count = 0

                while time.time() - start_time < timeout_seconds:
                    time.sleep(3)

                    is_limited, reset_secs = self._detect_rate_limit(page)
                    if is_limited:
                        raise ClaudeRateLimitError(
                            f"[{self.name}] Terkena batas kuota 5 jam saat proses menjawab.",
                            reset_seconds=reset_secs,
                        )

                    # Check stop button
                    stop_btn = page.locator('button[aria-label="Stop Response"], button[aria-label="Stop generating"]').first
                    generating = stop_btn.is_visible(timeout=500) if stop_btn else False

                    current_count = messages.count()
                    if current_count > initial_msg_count:
                        latest_msg = messages.nth(current_count - 1)
                        current_text = latest_msg.inner_text().strip()
                        current_len = len(current_text)

                        if not generating and current_len > 0:
                            if current_len == last_text_length:
                                stagnant_count += 1
                                if stagnant_count >= 2:
                                    print(f"[{self.name}] Respons selesai diterima ({current_len} karakter).")
                                    return current_text
                            else:
                                stagnant_count = 0
                                last_text_length = current_len

                current_count = messages.count()
                if current_count > initial_msg_count:
                    return messages.nth(current_count - 1).inner_text().strip()

                raise TimeoutError(f"[{self.name}] Waktu tunggu respons Claude melebihi {timeout_seconds} detik.")

            finally:
                context.close()
