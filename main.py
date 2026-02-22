import threading
import os
import asyncio
from flask import Flask
from telegram_cleanup.bot_interface import start_bot

# Minimal Flask app to satisfy deployment platforms that require a web port
app = Flask(__name__)

@app.route('/')
def health_check():
    return "🚀 Telegram Cleanup Bot is active and running!", 200

def run_bot_in_thread():
    """Starts the Telethon bot in a separate asyncio event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_bot())
    except Exception as e:
        print(f"❌ Bot Thread Error: {e}")

# Start the bot thread immediately when the module is loaded (for Gunicorn)
# We use a lock-file or environment check to ensure only one instance runs
# if the server uses multiple workers (though 1 worker is recommended).
if os.environ.get("BOT_STARTED") != "true":
    os.environ["BOT_STARTED"] = "true"
    threading.Thread(target=run_bot_in_thread, daemon=True).start()
    print("🤖 Bot thread started.")

if __name__ == "__main__":
    # For local testing or simple python execution
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
