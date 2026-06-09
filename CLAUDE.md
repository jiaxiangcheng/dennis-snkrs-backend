# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Discord bot for Dennis Snkrs that combines a FastAPI REST service with Discord bot functionality. The `/wtb` (Want To Buy) slash command searches products by SKU and variant (case-insensitive), posts WTB messages with product embeds to the current channel, and broadcasts to multiple Discord webhooks. Messages can be deleted by reacting with ✅.

## Architecture

### Concurrent Service Model

`main.py` orchestrates three concurrent async tasks via `asyncio.wait()`:
1. **FastAPI server** (uvicorn) — REST API with health check
2. **Discord bot** (`bot.py`) — Slash command handling and message management
3. **Product cache refresh** (`product_cache.py`) — 1-hour background refresh loop

If any task completes or fails, remaining tasks are cancelled (fail-fast).

### Product Caching (`product_cache.py`)

- Fetches from `https://www.dennis-snkrs.com/products.json` with pagination (250/page)
- SKU extracted from `body_html` via regex `>([A-Z0-9\-]+)<`, fallback to stripped text
- In-memory dict `products_by_sku` for O(1) lookup; persisted to `products_cache.json` as SKU-indexed JSON
- Cache file valid for 1 hour (`cache_duration = timedelta(hours=1)`); background refresh also runs every 1 hour
- **Cache availability**: Commands blocked only when `is_refreshing=True` AND `has_cache=False` (first startup only). During background refresh, existing cache remains usable.
- SKU matching: case-insensitive with partial match fallback (bidirectional substring)
- Variant matching: case-insensitive exact match against variant titles

### `/wtb` Command Flow (`bot.py`)

1. Permission check: user must have one of two hardcoded role IDs (`allowed_role_ids`)
2. Cache availability check
3. Variant parsing: single (`43`), pipe-separated (`40|41|42`), or `all`
4. Product search via `find_product()`, `find_product_with_variants()`, or `find_product_all_sizes()`
5. Post to current channel with role mention, channel mention, WTB link, and product embed
6. Broadcast to 3 hardcoded Discord webhooks (first includes WTB link, others don't)
7. Ephemeral confirmation to user

### Message Deletion

`on_raw_reaction_add` event: ✅ reaction on any bot message containing "want to buy" (case-insensitive) triggers message deletion.

### Hardcoded IDs in `bot.py`

- Allowed role IDs: `1424509842491707392`, `1338230016147980308`
- Role mention: `<@&1344067083465654282>`
- Channel mention: `<#1344381116613660682>`
- WTB link: `https://www.wtbmarketlist.eu/list/355476796801679378`
- 3 webhook URLs in `webhook_configs`

### Other Files

- **config.py**: Loads `DISCORD_BOT_TOKEN` from `.env`, sets `API_HOST="0.0.0.0"` and `API_PORT` (env `PORT` or 8000)
- **logger_config.py**: Colored formatter with timestamps; suppresses noisy `discord`/`aiohttp` loggers
- **discord_service.py**: Legacy, unused — message search/deletion service
- **start_api_only.py** / **start_bot_only.py**: Run individual components without the other

## Development Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run full application (API + bot + cache refresh)
python main.py

# Run API only (no Discord bot)
python start_api_only.py

# Run bot only (no API server)
python start_bot_only.py

# Dev mode with auto-reload (API only, no bot)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Shell script (installs deps + runs main.py)
./start.sh
```

### Environment Setup

`.env` file (required):
```
DISCORD_BOT_TOKEN=your_bot_token_here
PORT=8000  # optional, defaults to 8000
```

### API Endpoints

- `GET /` — Service info
- `GET /health` — Health check with cache status
- `GET /docs` — Swagger UI

### Deployment

Procfile configured for Heroku: `web: python main.py`

## Key Implementation Notes

- **No test framework** — no pytest or test files exist
- **Python 3.13** — project targets Python 3.13 (venv)
- **Global singletons**: `product_cache` and `discord_bot` are module-level instances imported throughout
- **Image priority**: variant `featured_image` > first product image
- **Cache file format**: `{"products": {"SKU": {...}}, "products_without_sku": [...], "last_update": ..., "total_products": ..., "products_with_sku": ...}` — supports legacy array format on load
