"""Telegram notifications (optional). Failures are logged, never raised."""

from __future__ import annotations

import logging

import requests

from .config import TelegramConfig

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: TelegramConfig) -> None:
        self.enabled = cfg.enabled and bool(cfg.token and cfg.chat_id)
        self.cfg = cfg
        if cfg.enabled and not self.enabled:
            log.warning("Telegram enabled but TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing; notifications off")

    def send(self, text: str) -> None:
        log.info("NOTIFY: %s", text.replace("\n", " | "))
        if not self.enabled:
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.cfg.token}/sendMessage",
                json={"chat_id": self.cfg.chat_id, "text": text},
                timeout=10,
            )
            if resp.status_code != 200:
                log.warning("Telegram error %s: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.warning("Telegram send failed: %s", exc)
