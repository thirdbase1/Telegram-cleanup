import threading
import os
import asyncio
import time
import fcntl
from flask import Flask
from telegram_cleanup.bot_interface import start_bot

app = Flask(__name__)

# Global status for diagnostics
bot_status = {
    "initialized": False,
    "last_error": None,
    "start_time": None,
    "thread_alive": False
}

@app.route('/')
def health_check():
    status_str = "🟢 Bot is Running" if bot_status["initialized"] else "🔴 Bot is Starting..."
    if bot_status["last_error"]:
        status_str = f"⚠️ Bot Error: {bot_status['last_error']}"

    return f"""
    <html>
        <head><title>Telegram Cleanup Bot Status</title></head>
        <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h1>🚀 Telegram Cleanup Bot</h1>
            <p style="font-size: 1.5em;">Status: <strong>{status_str}</strong></p>
            <p>Start Time: {bot_status['start_time'] or 'N/A'}</p>
            <hr>
            <p>To test, send <code>/ping</code> to your bot on Telegram.</p>
        </body>
    </html>
    """, 200

def run_bot_in_thread():
    """Starts the Telethon bot in a separate asyncio event loop with retry logic."""
    global bot_status
    bot_status["thread_alive"] = True
    bot_status["start_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

    print("🧵 [Thread] Starting asyncio loop...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    retry_delay = 5
    while True:
        try:
            print(f"🤖 [Thread] Attempting to start_bot()...")
            bot_status["initialized"] = False

            def on_start_callback():
                print("📝 [Thread] Bot signaled 'started' via callback.")
                bot_status["initialized"] = True
                bot_status["last_error"] = None

            # This will block until the bot is disconnected
            loop.run_until_complete(start_bot(on_start=on_start_callback))

            print("🤖 [Thread] Bot disconnected normally.")
            bot_status["last_error"] = "Disconnected"
        except Exception as e:
            error_msg = str(e)
            print(f"❌ [Thread] Fatal Bot Error: {error_msg}")
            bot_status["last_error"] = error_msg

        print(f"🔄 [Thread] Retrying in {retry_delay}s...")
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60) # Exponential backoff

# Start the bot thread immediately when the module is loaded (for Gunicorn)
# We use a robust file lock to ensure only ONE Gunicorn worker process runs the bot.
def try_start_bot():
    lock_file = os.path.join("sessions", "bot.lock")
    try:
        # Create sessions dir if not exists
        os.makedirs("sessions", exist_ok=True)

        # Open lock file
        f = open(lock_file, "w")
        # Try to acquire an exclusive lock (non-blocking)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # If we got here, we have the lock!
        if os.environ.get("BOT_STARTED") != "true":
            os.environ["BOT_STARTED"] = "true"
            t = threading.Thread(target=run_bot_in_thread, daemon=True)
            t.start()
            print(f"🛰️  [Main] Bot thread dispatched in this process (Lock acquired).")
            # We keep 'f' open to maintain the lock
            return f
    except (IOError, BlockingIOError):
        print(f"🛰️  [Main] Bot already running in another process (Lock busy).")
    except Exception as e:
        print(f"⚠️  [Main] Lock error: {e}")
    return None

# Global lock object to prevent garbage collection
bot_process_lock = try_start_bot()

if __name__ == "__main__":
    # For local testing
    port = int(os.environ.get("PORT", 8000))
    print(f"🌐 [Main] Starting web server on port {port}...")
    app.run(host='0.0.0.0', port=port)
