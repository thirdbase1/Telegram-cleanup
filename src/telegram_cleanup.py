import asyncio
from .config import load_config
from .sdk import TelegramCleaner

def main_cli():
    """Command-line interface for the Telegram Cleanup script."""
    config = load_config()

    cleaner = TelegramCleaner(config)

    async def run():
        await cleaner.connect()

        user_input = input("📝 Enter usernames of bots you created (comma-separated, e.g., @MyBot1,@MyBot2, or none): ")
        user_kept_bots = {b.strip().lower() for b in user_input.split(",") if b.strip()}

        await cleaner.run_cleanup(user_kept_bots)
        await cleaner.disconnect()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("👋 Exiting...")
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
