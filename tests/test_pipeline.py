from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pipeline.gumroad import zip_daily_artifacts
from pipeline.main import load_dotenv, run
from pipeline.report import build_markdown, build_telegram_text, flatten_market_rows
from pipeline.store import Store


SAMPLE_BUNDLE = {
    "date": "2026-08-19",
    "generated_at": "2026-08-19T00:00:00Z",
    "status": "ok",
    "ok_collectors": ["coingecko", "fear_greed", "fx"],
    "failed_collectors": [],
    "payloads": {
        "coingecko": {
            "source": "coingecko",
            "items": [
                {
                    "id": "bitcoin",
                    "symbol": "BTC",
                    "name": "Bitcoin",
                    "rank": 1,
                    "price_usd": 65000.12,
                    "market_cap_usd": 1_200_000_000_000,
                    "volume_24h_usd": 30_000_000_000,
                    "change_24h_pct": 2.5,
                    "change_7d_pct": -1.2,
                }
            ],
        },
        "fear_greed": {
            "items": [{"value": 55, "classification": "Greed", "timestamp": "1"}],
        },
        "fx": {"date": "2026-08-19", "rates": {"EUR": 0.92, "ILS": 3.7}},
    },
}


class DotenvTests(unittest.TestCase):
    def test_load_dotenv_does_not_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("GUMROAD_PRODUCT_ID=from-file\nGUMROAD_ACCESS_TOKEN=file-token\n")
            os.environ.pop("GUMROAD_PRODUCT_ID", None)
            os.environ["GUMROAD_ACCESS_TOKEN"] = "already-set"
            load_dotenv(root)
            self.assertEqual(os.environ.get("GUMROAD_PRODUCT_ID"), "from-file")
            self.assertEqual(os.environ.get("GUMROAD_ACCESS_TOKEN"), "already-set")
            os.environ.pop("GUMROAD_PRODUCT_ID", None)
            os.environ.pop("GUMROAD_ACCESS_TOKEN", None)


class ReportTests(unittest.TestCase):
    def test_markdown_contains_core_sections(self) -> None:
        md = build_markdown(SAMPLE_BUNDLE)
        self.assertIn("Daily Market & Tech Intelligence", md)
        self.assertIn("BTC", md)
        self.assertIn("Greed", md)
        self.assertIn("ILS=3.7", md)

    def test_telegram_summary_mentions_date_and_mover(self) -> None:
        text = build_telegram_text(SAMPLE_BUNDLE)
        self.assertIn("2026-08-19", text)
        self.assertIn("BTC", text)
        self.assertIn("Fear & Greed", text)

    def test_flatten_market_rows(self) -> None:
        rows = flatten_market_rows(SAMPLE_BUNDLE["payloads"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "BTC")


class StoreTests(unittest.TestCase):
    def test_sqlite_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root)
            run_id = store.record_run(
                "2026-08-19T00:00:00Z",
                "ok",
                ["coingecko"],
                [],
                {"coingecko": SAMPLE_BUNDLE["payloads"]["coingecko"]},
            )
            self.assertGreaterEqual(run_id, 1)
            day_dir = store.write_daily_bundle(
                "2026-08-19",
                SAMPLE_BUNDLE,
                "# report\n",
                "<html></html>",
                flatten_market_rows(SAMPLE_BUNDLE["payloads"]),
            )
            self.assertTrue((day_dir / "bundle.json").exists())
            self.assertTrue((day_dir / "crypto_markets.csv").read_text().startswith("id,symbol"))
            latest = json.loads((root / "datasets" / "latest.json").read_text())
            self.assertEqual(latest["date"], "2026-08-19")
            self.assertTrue((root / "docs" / "index.html").exists())


class GumroadZipTests(unittest.TestCase):
    def test_zip_includes_csv_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = Path(tmp)
            (day_dir / "bundle.json").write_text("{}\n")
            (day_dir / "crypto_markets.csv").write_text("symbol,price_usd\nBTC,1\n")
            (day_dir / "report.md").write_text("# hi\n")
            zip_path = zip_daily_artifacts(day_dir, "2026-08-19")
            self.assertTrue(zip_path.exists())
            self.assertGreater(zip_path.stat().st_size, 32)
            with zipfile.ZipFile(zip_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"bundle.json", "crypto_markets.csv", "report.md"},
                )


class GumroadSafetyTests(unittest.TestCase):
    def test_refuses_unrelated_product(self) -> None:
        from pipeline.gumroad import _assert_safe_target
        from pipeline.http import HttpError

        with self.assertRaises(HttpError):
            _assert_safe_target({"id": "x", "name": "Indie Stack Toolkit"})
        _assert_safe_target({"id": "x", "name": "Daily Market & Tech Dataset"})


class PipelineOfflineTests(unittest.TestCase):
    def test_run_with_mocked_collectors(self) -> None:
        fake_payloads = SAMPLE_BUNDLE["payloads"]
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "pipeline.main.run_all_collectors",
                return_value=(fake_payloads, ["coingecko", "fear_greed", "fx"], []),
            ):
                result = run(Path(tmp), deliver=False)
            self.assertEqual(result["status"], "ok")
            self.assertTrue((Path(tmp) / result["output_dir"] / "bundle.json").exists())


if __name__ == "__main__":
    unittest.main()
