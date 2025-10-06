from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import logging
import signal
from bot import discord_bot
from product_cache import product_cache
from config import API_HOST, API_PORT

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Dennis Snkrs Discord Bot API",
    description="Discord bot API for Dennis Snkrs",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint"""
    try:
        return {
            "message": "App is running",
            "status": "healthy",
            "service": "Dennis Snkrs Discord Bot API",
            "version": "1.0.0",
            "endpoints": {
                "GET /health": "Health check endpoint"
            }
        }
    except Exception as e:
        logger.error(f"Error in root endpoint: {e}")
        return {
            "message": "App is running with warnings",
            "status": "degraded",
            "service": "Dennis Snkrs Discord Bot API",
            "version": "1.0.0",
            "error": str(e)
        }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    import time

    products_count = len(product_cache.products_by_sku)
    cache_status = "initialized" if products_count > 0 else "loading"

    return {
        "status": "healthy",
        "message": "Service fully operational",
        "service": "dennis-snkrs-discord-bot",
        "product_cache_status": cache_status,
        "products_cached": products_count,
        "last_cache_update": product_cache.last_update.isoformat() if product_cache.last_update else None,
        "timestamp": int(time.time())
    }

async def run_servers():
    """Run both FastAPI server and Discord bot concurrently"""
    import uvicorn

    # Create uvicorn server
    config = uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info")
    server = uvicorn.Server(config)

    logger.info("Starting Discord bot with slash commands...")
    logger.info(f"Starting Dennis Snkrs Discord Bot API on {API_HOST}:{API_PORT}")

    try:
        # Start background tasks
        bot_task = asyncio.create_task(discord_bot.start())
        cache_refresh_task = asyncio.create_task(product_cache.start_background_refresh())

        # Wait a moment for bot to initialize
        await asyncio.sleep(3)

        logger.info("Discord bot initialized! Starting API server...")

        # Start API server
        api_task = asyncio.create_task(server.serve())

        # Wait for any task to complete or fail
        done, pending = await asyncio.wait(
            [api_task, bot_task, cache_refresh_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # If one task completes, cancel the other
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Check if any task failed
        for task in done:
            if task.exception():
                logger.error(f"Task failed with exception: {task.exception()}")
                raise task.exception()

    except Exception as e:
        logger.error(f"Error in run_servers: {e}")
        # Graceful shutdown will be handled by signal handlers
        raise

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, _):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        # Create a new event loop for cleanup if needed
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(shutdown_handler())
        except RuntimeError:
            pass

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

async def shutdown_handler():
    """Handle graceful shutdown"""
    logger.info("Starting graceful shutdown...")

    try:
        await discord_bot.stop()
    except Exception as e:
        logger.error(f"Error stopping Discord bot: {e}")

    logger.info("Shutdown complete")

if __name__ == "__main__":
    setup_signal_handlers()

    try:
        asyncio.run(run_servers())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error running servers: {e}")
        raise
    finally:
        logger.info("Application stopped")
