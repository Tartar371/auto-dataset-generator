"""Optional delivery: Telegram, Discord, generic webhook, Gumroad file upload."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pipeline.gumroad import publish_daily_zip
from pipeline.http import post_json

log = logging.getLogger("pipeline.notify")


def _env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return value or None


def notify_telegram(text: str) -> bool:
    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram skipped (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    post_json(url, payload)
    log.info("Telegram message sent")
    return True


def notify_discord(text: str) -> bool:
    url = _env("DISCORD_WEBHOOK_URL")
    if not url:
        log.info("Discord skipped (DISCORD_WEBHOOK_URL not set)")
        return False
    post_json(url, {"content": text[:1900]})
    log.info("Discord webhook sent")
    return True


def notify_generic_webhook(bundle: dict[str, Any]) -> bool:
    url = _env("GENERIC_WEBHOOK_URL")
    if not url:
        log.info("Generic webhook skipped (GENERIC_WEBHOOK_URL not set)")
        return False
    post_json(
        url,
        {
            "event": "daily_dataset",
            "date": bundle.get("date"),
            "status": bundle.get("status"),
            "ok_collectors": bundle.get("ok_collectors"),
            "failed_collectors": bundle.get("failed_collectors"),
        },
    )
    log.info("Generic webhook sent")
    return True


def notify_gumroad(bundle: dict[str, Any], summary: str, day_dir: Path | None) -> bool:
    token = _env("GUMROAD_ACCESS_TOKEN")
    product_id = _env("GUMROAD_PRODUCT_ID")
    if not token or not product_id:
        log.info("Gumroad skipped (GUMROAD_ACCESS_TOKEN / GUMROAD_PRODUCT_ID not set)")
        return False
    if day_dir is None:
        log.info("Gumroad skipped (no daily folder to zip)")
        return False
    publish_daily_zip(token, product_id, day_dir, bundle, summary, env_path=day_dir.parents[1] / ".env")
    return True


def deliver_all(
    bundle: dict[str, Any],
    telegram_text: str,
    day_dir: Path | None = None,
) -> dict[str, bool]:
    results = {
        "telegram": False,
        "discord": False,
        "generic_webhook": False,
        "gumroad": False,
    }
    try:
        results["telegram"] = notify_telegram(telegram_text)
    except Exception as exc:  # noqa: BLE001
        log.exception("Telegram delivery failed: %s", exc)
    try:
        results["discord"] = notify_discord(telegram_text)
    except Exception as exc:  # noqa: BLE001
        log.exception("Discord delivery failed: %s", exc)
    try:
        results["generic_webhook"] = notify_generic_webhook(bundle)
    except Exception as exc:  # noqa: BLE001
        log.exception("Generic webhook delivery failed: %s", exc)
    try:
        results["gumroad"] = notify_gumroad(bundle, telegram_text, day_dir)
    except Exception as exc:  # noqa: BLE001
        log.exception("Gumroad delivery failed: %s", exc)
    return results
