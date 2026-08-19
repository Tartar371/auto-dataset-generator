"""SQLite history + daily JSON/CSV/MD exports."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    ok_collectors TEXT NOT NULL,
    failed_collectors TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.datasets = root / "datasets"
        self.docs = root / "docs"
        self.logs = root / "logs"
        self.db_path = self.datasets / "history.sqlite"
        for path in (self.datasets, self.docs, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def record_run(
        self,
        run_at: str,
        status: str,
        ok: list[str],
        failures: list[dict[str, str]],
        payloads: dict[str, Any],
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO runs (run_at, status, ok_collectors, failed_collectors) VALUES (?, ?, ?, ?)",
                (run_at, status, ",".join(ok), json.dumps(failures)),
            )
            run_id = int(cur.lastrowid)
            for source, payload in payloads.items():
                conn.execute(
                    "INSERT INTO snapshots (run_id, source, payload_json) VALUES (?, ?, ?)",
                    (run_id, source, json.dumps(payload, ensure_ascii=False)),
                )
            conn.commit()
        return run_id

    def write_daily_bundle(
        self,
        day: str,
        bundle: dict[str, Any],
        report_md: str,
        report_html: str,
        market_rows: list[dict[str, Any]],
    ) -> Path:
        day_dir = self.datasets / day
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "bundle.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (day_dir / "report.md").write_text(report_md, encoding="utf-8")
        self._write_csv(day_dir / "crypto_markets.csv", market_rows)
        latest = {
            "date": day,
            "status": bundle.get("status"),
            "ok_collectors": bundle.get("ok_collectors"),
            "failed_collectors": bundle.get("failed_collectors"),
            "artifact": f"datasets/{day}/bundle.json",
        }
        (self.datasets / "latest.json").write_text(
            json.dumps(latest, indent=2) + "\n", encoding="utf-8"
        )
        (self.docs / "index.html").write_text(report_html, encoding="utf-8")
        (self.docs / "latest.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return day_dir

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("symbol,name,rank,price_usd,market_cap_usd,volume_24h_usd,change_24h_pct\n")
            return
        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
