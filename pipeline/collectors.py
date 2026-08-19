"""Fail-soft collectors for public APIs only (no site scraping)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable

from pipeline.http import fetch_json, fetch_text

log = logging.getLogger("pipeline.collectors")
ATOM = "{http://www.w3.org/2005/Atom}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect_coingecko_markets() -> dict[str, Any]:
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
        "&sparkline=false&price_change_percentage=24h,7d"
    )
    rows = fetch_json(url)
    if not isinstance(rows, list):
        raise RuntimeError("CoinGecko returned a non-list payload")
    coins = []
    for row in rows:
        coins.append(
            {
                "id": row.get("id"),
                "symbol": (row.get("symbol") or "").upper(),
                "name": row.get("name"),
                "rank": row.get("market_cap_rank"),
                "price_usd": row.get("current_price"),
                "market_cap_usd": row.get("market_cap"),
                "volume_24h_usd": row.get("total_volume"),
                "change_24h_pct": row.get("price_change_percentage_24h"),
                "change_7d_pct": row.get("price_change_percentage_7d_in_currency"),
                "ath": row.get("ath"),
                "atl": row.get("atl"),
                "last_updated": row.get("last_updated"),
            }
        )
    return {"source": "coingecko", "fetched_at": utc_now(), "count": len(coins), "items": coins}


def collect_fear_greed() -> dict[str, Any]:
    data = fetch_json("https://api.alternative.me/fng/?limit=7")
    items = data.get("data") if isinstance(data, dict) else None
    if not items:
        raise RuntimeError("Fear & Greed payload missing data")
    parsed = [
        {
            "value": int(item["value"]),
            "classification": item.get("value_classification"),
            "timestamp": item.get("timestamp"),
        }
        for item in items
    ]
    return {"source": "alternative_me_fng", "fetched_at": utc_now(), "count": len(parsed), "items": parsed}


def collect_fx_rates() -> dict[str, Any]:
    data = fetch_json("https://api.frankfurter.app/latest?from=USD&to=EUR,GBP,JPY,ILS,CHF")
    if not isinstance(data, dict) or "rates" not in data:
        raise RuntimeError("Frankfurter payload missing rates")
    return {
        "source": "frankfurter_ecb",
        "fetched_at": utc_now(),
        "base": data.get("base", "USD"),
        "date": data.get("date"),
        "rates": data.get("rates"),
    }


def collect_defillama_chains() -> dict[str, Any]:
    rows = fetch_json("https://api.llama.fi/v2/chains")
    if not isinstance(rows, list):
        raise RuntimeError("DefiLlama returned a non-list payload")
    ranked = sorted(rows, key=lambda r: float(r.get("tvl") or 0), reverse=True)[:25]
    items = [
        {
            "name": row.get("name"),
            "tvl_usd": row.get("tvl"),
            "token_symbol": row.get("tokenSymbol"),
            "gecko_id": row.get("gecko_id"),
        }
        for row in ranked
    ]
    return {"source": "defillama_chains", "fetched_at": utc_now(), "count": len(items), "items": items}


def collect_hackernews() -> dict[str, Any]:
    ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(ids, list):
        raise RuntimeError("HN topstories was not a list")
    items = []
    for story_id in ids[:12]:
        story = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not isinstance(story, dict):
            continue
        items.append(
            {
                "id": story.get("id"),
                "title": story.get("title"),
                "url": story.get("url"),
                "score": story.get("score"),
                "by": story.get("by"),
                "descendants": story.get("descendants"),
                "time": story.get("time"),
            }
        )
    return {"source": "hackernews", "fetched_at": utc_now(), "count": len(items), "items": items}


def collect_arxiv_ai() -> dict[str, Any]:
    url = (
        "https://export.arxiv.org/api/query"
        "?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:q-fin.TR"
        "&start=0&max_results=12&sortBy=submittedDate&sortOrder=descending"
    )
    xml_text = fetch_text(url)
    root = ET.fromstring(xml_text)
    items = []
    for entry in root.findall(f"{ATOM}entry"):
        title_el = entry.find(f"{ATOM}title")
        id_el = entry.find(f"{ATOM}id")
        published_el = entry.find(f"{ATOM}published")
        summary_el = entry.find(f"{ATOM}summary")
        authors = [
            (author.find(f"{ATOM}name").text or "").strip()
            for author in entry.findall(f"{ATOM}author")
            if author.find(f"{ATOM}name") is not None and author.find(f"{ATOM}name").text
        ]
        items.append(
            {
                "id": (id_el.text or "").strip() if id_el is not None else None,
                "title": " ".join((title_el.text or "").split()) if title_el is not None else None,
                "published": (published_el.text or "").strip() if published_el is not None else None,
                "authors": authors,
                "summary": " ".join((summary_el.text or "").split())[:500] if summary_el is not None else None,
            }
        )
    return {"source": "arxiv", "fetched_at": utc_now(), "count": len(items), "items": items}


COLLECTORS: list[tuple[str, Callable[[], dict[str, Any]]]] = [
    ("coingecko", collect_coingecko_markets),
    ("fear_greed", collect_fear_greed),
    ("fx", collect_fx_rates),
    ("defillama", collect_defillama_chains),
    ("hackernews", collect_hackernews),
    ("arxiv", collect_arxiv_ai),
]


def run_all_collectors() -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    """Return (payloads_by_name, ok_names, failures). Never raises for a single source."""
    payloads: dict[str, Any] = {}
    ok: list[str] = []
    failures: list[dict[str, str]] = []
    for name, fn in COLLECTORS:
        try:
            payloads[name] = fn()
            ok.append(name)
            log.info("collector ok: %s", name)
        except Exception as exc:  # noqa: BLE001 - fail-soft by design
            log.exception("collector failed: %s", name)
            failures.append({"collector": name, "error": str(exc)})
    return payloads, ok, failures
