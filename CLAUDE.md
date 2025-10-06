# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Discord bot for Dennis Snkrs that combines a FastAPI REST service with Discord bot functionality. The system provides a `/wtb` (Want To Buy) slash command that searches products by SKU and variant (case-insensitive), then posts WTB messages with product details directly to the channel where the command was used. Messages can be deleted by reacting with ✅.

## Architecture

### Core Components

- **main.py**: Entry point that orchestrates three concurrent async tasks: FastAPI server, Discord bot, and product cache refresh loop
- **bot.py**: Discord bot with slash command registration and message sending
- **product_cache.py**: Product data manager that fetches from dennis-snkrs.com/products.json, caches locally, and auto-refreshes every 24h
- **logger_config.py**: Custom logger configuration with colored output and timestamps
- **config.py**: Environment-based configuration (Discord token, API host/port)
- **discord_service.py**: Legacy service (currently unused)

### Key Architecture Patterns

**Concurrent Service Model**: Three async tasks run in parallel via `asyncio.wait()`:
- FastAPI server (uvicorn)
- Discord bot client
- Product cache background refresh (24h loop)

**Product Caching Strategy**:
- Products fetched from `https://www.dennis-snkrs.com/products.json` with pagination (250 items per page)
- SKU extracted from `body_html` field via regex (`>([A-Z0-9\-]+)<`)
- Cached to `products_cache.json` in SKU-indexed format (not array)
- In-memory SKU index (`products_by_sku` dict) for O(1) lookup
- **Case-insensitive matching**: Both SKU and variant matching ignore case
- **Cache Status Tracking**:
  - `is_refreshing`: True when fetching products from API
  - `has_cache`: True when products are loaded in memory
  - Commands blocked only if refreshing AND no cache exists
  - Commands work during refresh if existing cache is available

**Message Flow**:
1. User executes `/wtb SKU VARIANT` in Discord (requires Admin or allowed role)
2. Bot checks role permissions (2 allowed role IDs)
3. Bot checks cache status:
   - If `is_refreshing=True` AND `has_cache=False`: Return "Product data is being refreshed" message
   - If cache available: Proceed with search
4. Bot searches `product_cache.products_by_sku[SKU.upper()]`
5. Matches variant case-insensitively from product's variants array
6. Bot posts message to the **same channel** where command was used (not webhook)
7. Message includes: role mention, channel mention, WTB link, and product embed
8. Users can delete message by adding ✅ reaction

## Development Commands

### Starting the Application

```bash
# Full application (API + Discord bot + cache refresh)
python main.py

# API only (no bot)
python start_api_only.py

# Bot only (no API server)
python start_bot_only.py

# With auto-reload (development)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Using shell script (installs deps + runs main.py)
./start.sh
```

### Dependencies

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

Required environment variable in `.env` file:
```
DISCORD_BOT_TOKEN=your_bot_token_here
```

Optional:
```
PORT=8000  # Defaults to 8000 if not set
```

## Discord Bot Commands

- `/wtb <sku> <variant>`: Search product and send to webhook
  - Example: `/wtb FZ8117-100 43`
  - SKU must match extracted value from product's `body_html`
  - Variant must exactly match variant `title` field (case-sensitive)
  - Sends to webhook: `https://discord.com/api/webhooks/1032909099970613278/...`

## API Endpoints

- `GET /`: Service info and available endpoints
- `GET /health`: Health check with product cache status
- `GET /docs`: Swagger UI

## Important Implementation Details

- **Product Variant Matching**: Uses exact string comparison, not fuzzy matching. Variant "43" ≠ "43.0"
- **Cache Behavior**:
  - First startup without cache: Fetches all products (~528), blocks commands until complete
  - Subsequent startups: Loads from `products_cache.json` if < 24h old
  - 24h background refresh: Fetches new data but doesn't block commands (uses existing cache)
  - Cache file persists between restarts
- **Command Availability**:
  - Blocked: When `is_refreshing=True` AND `has_cache=False` (initial fetch only)
  - Available: When cache exists, even during background refresh
- **Pagination**: Fetches products in pages of 250 until empty response
- **Webhook URL**: Hardcoded in `bot.py:64`. Change requires code modification.
- **Image Priority**: Uses variant `featured_image` if set, otherwise first product image
- **No Testing**: No test framework configured