#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Install dependencies if not already installed
pip install -r requirements.txt

# Start the API server and Discord bot
echo "Starting Discord Message Deletion API and Bot..."
python main.py
