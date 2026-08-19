"""Daily public-API dataset pipeline. No paid LLM. No site scraping."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.collectors import run_all_collectors, utc_now
from pipeline.notify import deliver_all
from pipeline.report import build_html, build_markdown, build_telegram_text, flatten_market_rows
from pipeline.store import Store

log = logging.getLogger("pipeline")


def load_dotenv(root: Path) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing environment variables."""
    path = root / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(stream)
    root.addHandler(file_handler)


def run(root: Path, *, deliver: bool = True) -> dict:
    load_dotenv(root)
    store = Store(root)
    setup_logging(store.logs / "pipeline.log")
    day = datetime.now(timezone.utc).date().isoformat()
    log.info("starting pipeline for %s", day)
    payloads, ok, failures = run_all_collectors()
    status = "ok" if ok and not failures else ("partial" if ok else "failed")
    bundle = {
        "date": day,
        "generated_at": utc_now(),
        "status": status,
        "ok_collectors": ok,
        "failed_collectors": failures,
        "payloads": payloads,
    }
    markdown = build_markdown(bundle)
    html = build_html(bundle, markdown)
    market_rows = flatten_market_rows(payloads)
    store.record_run(bundle["generated_at"], status, ok, failures, payloads)
    day_dir = store.write_daily_bundle(day, bundle, markdown, html, market_rows)
    log.info("wrote artifacts to %s", day_dir)

    delivery = {}
    if deliver:
        delivery = deliver_all(bundle, build_telegram_text(bundle), day_dir)
        log.info("delivery results: %s", delivery)
    else:
        log.info("delivery skipped")

    try:
        output_rel = str(day_dir.relative_to(root))
    except ValueError:
        output_rel = str(day_dir)
    result = {
        "status": status,
        "date": day,
        "ok_collectors": ok,
        "failed_collectors": failures,
        "delivery": delivery,
        "output_dir": output_rel,
    }
    (store.logs / "last_run.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if status == "failed":
        raise SystemExit(2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily public-API dataset pipeline")
    parser.add_argument("--root", default=".", help="project root")
    parser.add_argument("--no-deliver", action="store_true", help="skip Telegram/Gumroad/webhooks")
    args = parser.parse_args()
    result = run(Path(args.root).resolve(), deliver=not args.no_deliver)
    print(json.dumps({k: result[k] for k in ("status", "date", "ok_collectors")}, indent=2))


if __name__ == "__main__":
    main()
