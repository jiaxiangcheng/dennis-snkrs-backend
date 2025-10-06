import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# API Configuration
API_HOST = "0.0.0.0"
API_PORT = int(os.getenv("PORT", 8000))
