# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Discord bot for Dennis Snkrs that combines a FastAPI REST service with Discord bot functionality. The system provides a `/wtb` (Want To Buy) slash command that searches products by SKU and variant, then sends product details to a Discord webhook.

## Architecture

### Core Components

- **main.py**: FastAPI application entry point that runs both the web API and Discord bot concurrently using asyncio
- **bot.py**: Contains `DiscordBot` class that manages Discord bot functionality and slash commands (`/wtb`)
- **product_cache.py**: Manages product data caching from dennis-snkrs.com with automatic 24h refresh
- **config.py**: Configuration settings including Discord bot token and API host/port settings

### Key Design Patterns

- **Dual Service Architecture**: The application runs both a FastAPI server and Discord bot simultaneously in separate async tasks
- **Product Caching**: Products are fetched from dennis-snkrs.com/products.json and cached locally, refreshed every 24 hours
- **SKU-based Indexing**: Products are indexed by SKU extracted from body_html for fast lookup

## Development Commands

### Starting the Application

```bash
# Full application (API + Discord bot)
python main.py

# Alternative with uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Using the shell script
./start.sh

# API only
python start_api_only.py

# Bot only
python start_bot_only.py
```

### Dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# Activate virtual environment
source venv/bin/activate
```

### Environment Setup

The application requires a Discord bot token to be set as an environment variable:

1. Create a `.env` file in the project root
2. Add your Discord bot token:
   ```
   DISCORD_BOT_TOKEN=your_bot_token_here
   ```

The `.env` file is automatically loaded by the application and excluded from git commits.

## API Endpoints

- `GET /`: API information
- `GET /health`: Health check
- `GET /docs`: Swagger documentation

## Discord Bot Commands

- `/wtb <sku> <variant>`: Search for product by SKU and variant, send to Discord webhook
  - Example: `/wtb FZ8117-100 43`
  - SKU is extracted from product's body_html field
  - Variant must exactly match the variant title (e.g., size)
  - Sends rich embed with product info to configured webhook URL

## Important Notes

- Discord bot token is loaded from environment variables via `.env` file
- No testing framework or linting tools are configured in this project