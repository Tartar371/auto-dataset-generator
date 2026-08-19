# Auto Dataset Generator

Daily **public-API** market & tech intelligence pipeline. It runs on GitHub Actions every day at **00:00 UTC**, writes JSON/CSV/SQLite artifacts into this repo, publishes a GitHub Pages report, and can optionally ping Telegram / Discord / Gumroad.

This is research data, not financial advice. It does **not** scrape private sites, send unsolicited outreach, or depend on Cursor staying open.

## What it collects

| Source | Data | Auth |
| --- | --- | --- |
| [CoinGecko](https://www.coingecko.com/en/api) | Top 50 coins: price, cap, volume, 24h/7d change | None |
| [Alternative.me](https://api.alternative.me/fng/) | Crypto Fear & Greed (7 days) | None |
| [Frankfurter](https://www.frankfurter.app/) | USD→EUR/GBP/JPY/ILS/CHF (ECB) | None |
| [DefiLlama](https://defillama.com/docs/api) | Top 25 chain TVL | None |
| [Hacker News](https://github.com/HackerNews/API) | Top 12 stories | None |
| [arXiv](https://arxiv.org/help/api) | Latest cs.AI / cs.LG / q-fin.TR papers | None |

Each source is fail-soft: one API outage does not kill the run.

## Outputs (the assets)

After each run:

- `datasets/YYYY-MM-DD/bundle.json` — full snapshot
- `datasets/YYYY-MM-DD/crypto_markets.csv` — spreadsheet-ready
- `datasets/YYYY-MM-DD/report.md` — human-readable briefing
- `datasets/history.sqlite` — append-only history
- `datasets/latest.json` — pointer to the newest drop
- `docs/index.html` + `docs/latest.json` — GitHub Pages site

## Run locally

```bash
python3 test.py
python3 -m pipeline.main --root . --no-deliver
```

Omit `--no-deliver` to attempt Telegram/Gumroad/webhooks using env vars from `.env.example`.

## Deploy (one-time)

1. Push this repo to GitHub (Actions must be enabled).
2. In the GitHub repo: **Settings → Pages → Deploy from branch → `main` / `docs`**.
3. Add optional Actions secrets (see below).
4. **Actions → Daily dataset → Run workflow** once to verify. After that the midnight UTC cron is enough. Your laptop can stay off.

GitHub's `GITHUB_TOKEN` is injected automatically. No OpenAI key is required.

## Optional secrets

| Secret | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your user/channel id (message the bot, then call `getUpdates`) |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook |
| `GENERIC_WEBHOOK_URL` | Make.com / Zapier / n8n |
| `GUMROAD_ACCESS_TOKEN` | From **Generate access token** after creating the app |
| `GUMROAD_PRODUCT_ID` | The product’s `id` from Gumroad (product URL or API) |

### Gumroad app form (own account)

Open [app.gumroad.com/settings/advanced](https://app.gumroad.com/settings/advanced) and create an application:

| Field | Value |
| --- | --- |
| Application name | `auto-dataset-generator` |
| Redirect URI | `http://127.0.0.1` |

`http://127.0.0.1` is the official dummy redirect for a personal access token. This job does not run a website, so there is no public callback URL.

Then click **Generate access token**. Create one digital product (any price). Add both values as GitHub Actions secrets. Each midnight run zips `bundle.json` + `crypto_markets.csv` + `report.md` and replaces the product file.

## Attribution

Redistribute with credit to CoinGecko, Alternative.me, the ECB (via Frankfurter), DefiLlama, Hacker News, and arXiv. Respect each API's rate limits and terms.
