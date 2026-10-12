"""
Algo Lab — Zero-Intervention Webhook Telemetry & Alerting Dispatcher.
Supports Discord, Telegram, and Slack incoming webhooks for fully autonomous trading.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("WebhookDispatcher")


class WebhookDispatcher:
    """Dispatches asynchronous alerts to Discord, Slack, or Telegram."""

    def __init__(
        self,
        discord_webhook_url: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        self.discord_url = discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
        self.slack_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.tg_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    def notify(self, title: str, message: str, level: str = "INFO", fields: Optional[Dict[str, Any]] = None) -> bool:
        """Sends an autonomous notification to configured channels."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text = f"**[{level}] {title}**\n{message}\n_Timestamp: {timestamp}_"
        
        if fields:
            field_lines = "\n".join([f"• **{k}**: {v}" for k, v in fields.items()])
            text += f"\n\n{field_lines}"

        sent = False
        # 1. Discord Webhook
        if self.discord_url:
            try:
                payload = {
                    "content": text[:1900],
                    "username": "AlgoLab Sentinel",
                }
                resp = requests.post(self.discord_url, json=payload, timeout=5)
                if resp.status_code in (200, 204):
                    sent = True
            except Exception as e:
                logger.warning(f"Discord webhook failed: {e}")

        # 2. Slack Webhook
        if self.slack_url:
            try:
                payload = {"text": text}
                resp = requests.post(self.slack_url, json=payload, timeout=5)
                if resp.status_code == 200:
                    sent = True
            except Exception as e:
                logger.warning(f"Slack webhook failed: {e}")

        # 3. Telegram Bot API
        if self.tg_token and self.tg_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
                payload = {
                    "chat_id": self.tg_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                }
                resp = requests.post(url, json=payload, timeout=5)
                if resp.status_code == 200:
                    sent = True
            except Exception as e:
                logger.warning(f"Telegram alert failed: {e}")

        # Fallback to local structured log
        logger.info(f"[TELEMETRY {level}] {title} - {message}")
        return sent


if __name__ == "__main__":
    dispatcher = WebhookDispatcher()
    dispatcher.notify("Test Ping", "Algo Lab Telemetry Dispatcher Online", level="INFO")
    print("WebhookDispatcher initialized successfully.")
