# Dennis Snkrs Discord Bot

This is a Python-based Discord bot for Dennis Snkrs with slash commands and API endpoints.

## Features

- 💬 Discord bot with `/wtb` command for product lookup
- 🔍 Product search by SKU and variant (size)
- 📦 Automatic product cache with 24h refresh
- 🚀 FastAPI REST interface
- 🏥 Health check endpoints
- 🎯 Discord webhook integration with rich embeds

## Installation Steps

### 1. Clone project and set up virtual environment

```bash
cd /path/to/your/project
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# Or on Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Discord Bot Token

Ensure your Discord bot has the following permissions:

- Read Messages
- Read Message History
- Manage Messages

Bot token is already configured in `config.py`.

## Starting the API Service

```bash
python main.py
```

The API will start at `http://localhost:8000`.

You can also start using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Discord Bot Commands

Once the bot is running, these slash commands are available in Discord:

- `/wtb <sku> <variant>` - Want to buy - Search for a product and send to webhook
  - Example: `/wtb FZ8117-100 43`
  - Searches for product with SKU "FZ8117-100" and size "43"
  - Sends product details to Discord webhook with embed

## API Endpoints

- **GET** `/` - API information
- **GET** `/health` - Health check
- **GET** `/docs` - Swagger documentation interface

## Important Notes

- Ensure Discord bot is in the target server and has necessary permissions
- Channel ID can be obtained by right-clicking Discord channel and selecting "Copy ID" (requires developer mode enabled)

## Development

To view API documentation, after starting the service visit:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
