import os
import sys
from dotenv import load_dotenv

def load_config():
    """Load and validate environment variables."""
    # Try to load .env from the current working directory
    env_path = os.path.join(os.getcwd(), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv() # Fallback to default search

    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone = os.getenv("PHONE")
    bot_token = os.getenv("BOT_TOKEN")
    whitelist_env = os.getenv("WHITELIST", "")

    # Check for missing variables first
    missing = []
    if not api_id: missing.append("API_ID")
    if not api_hash: missing.append("API_HASH")

    # PHONE is only mandatory for CLI mode, not for Bot mode
    # But we'll make it optional here and handle it in the respective modules.

    if missing:
        print(f"❌ Error: Missing configuration for: {', '.join(missing)}")
        print("💡 Please ensure your .env file or environment variables contain API_ID and API_HASH.")
        print(f"📂 Current directory: {os.getcwd()}")
        sys.exit(1)

    try:
        # Strip whitespace and convert to int
        api_id_int = int(api_id.strip())
    except ValueError:
        print(f"❌ Error: API_ID must be a pure integer. Received: '{api_id}'")
        sys.exit(1)

    return {
        "api_id": api_id_int,
        "api_hash": api_hash.strip() if api_hash else None,
        "phone": phone.strip() if phone else None,
        "bot_token": bot_token.strip() if bot_token else None,
        "whitelist": [item.strip() for item in whitelist_env.split(",") if item.strip()]
    }
