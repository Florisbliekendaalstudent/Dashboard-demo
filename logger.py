import logging
from pathlib import Path
from datetime import datetime
import os

LOG_FILE = Path(__file__).resolve().parent.parent / "audit_log.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log_action(user: str, action: str, details: str = ""):
    """Logt een actie voor audit doeleinden."""
    # Aangezien we lokaal draaien is 'user' nu vaak 'local_admin'
    message = f"User: {user} | Action: {action} | Details: {details}"
    logging.info(message)
    # Print ook naar console voor debugging
    if os.getenv("DEBUG"):
        print(f"AUDIT LOG: {message}")