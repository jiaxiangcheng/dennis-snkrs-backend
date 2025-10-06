"""
Start only the Discord bot without the API server
"""
import asyncio
import logging
from bot import discord_bot

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        logger.info("Starting Discord bot only...")
        asyncio.run(discord_bot.start())
    except KeyboardInterrupt:
        logger.info("Shutting down Discord bot...")
    except Exception as e:
        logger.error(f"Error running Discord bot: {e}")
        raise