"""
Start only the FastAPI server without the Discord bot
"""
import uvicorn
import logging
from main import app
from config import API_HOST, API_PORT

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info(f"Starting Discord Message Deletion API only on {API_HOST}:{API_PORT}")
    uvicorn.run(app, host=API_HOST, port=API_PORT)