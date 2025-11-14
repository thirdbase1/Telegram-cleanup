import os
import sys
from dotenv import load_dotenv

def load_config():
    """Load and validate environment variables."""
    load_dotenv()
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone = os.getenv("PHONE")

    try:
        api_id_int = int(api_id)
    except (TypeError, ValueError):
        print("❌ Error: API_ID in .env must be an integer")
        sys.exit(1)

    if not all([api_id, api_hash, phone]):
        print("❌ Error: Missing API_ID, API_HASH, or PHONE in .env file")
        sys.exit(1)

    return {
        "api_id": api_id_int,
        "api_hash": api_hash,
        "phone": phone
    }
