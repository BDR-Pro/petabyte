"""
Petabyte Agent - Main Entry Point
Runs both the task fetcher and UI
"""
import threading
import logging
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set environment variables if not already set
if not os.getenv("FASTAPI_SERVER_URL"):
    os.environ["FASTAPI_SERVER_URL"] = "https://Api.petabyte.market"

from task_fetcher import run_agent
from ui import run_ui
import time

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("petabyte_agent.log")
    ]
)

def run_agent_loop():
    """Run the agent (heartbeat thread + job poll loop)."""
    logging.info("Starting Petabyte Agent...")
    try:
        run_agent()
    except KeyboardInterrupt:
        logging.info("Agent stopped by user")

def main():
    """Main entry point."""
    # Start UI in a separate thread
    ui_thread = threading.Thread(
        target=run_ui,
        args=('127.0.0.1', 5000, False),
        daemon=True
    )
    ui_thread.start()
    logging.info("UI started on http://127.0.0.1:5000")
    
    # Run agent in main thread
    try:
        run_agent_loop()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()

