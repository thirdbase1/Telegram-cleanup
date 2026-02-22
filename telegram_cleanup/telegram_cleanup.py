import asyncio
from .config import load_config
from .sdk import TelegramCleaner

def main_cli():
    """Command-line interface for the Telegram Cleanup script."""
    config = load_config()

    cleaner = TelegramCleaner(config)

    async def run():
        await cleaner.connect()

        user_kept_items = set(config.get("whitelist", []))

        if not user_kept_items:
            print("\n🔒 WHITELIST: These items will NEVER be deleted.")
            print("💡 You can enter usernames (@name), full links (t.me/name), or exact names of channels/groups.")
            print("📝 Example: James bot, Michael, @SomeBot, https://t.me/MyChannel")
            user_input = input("👉 Enter items to keep (comma-separated, or press Enter to skip): ")
            user_kept_items = {b.strip() for b in user_input.split(",") if b.strip()}
        else:
            print(f"\n✅ Loaded {len(user_kept_items)} items from WHITELIST environment variable.")

        await cleaner.run_cleanup(user_kept_items)
        await cleaner.disconnect()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("👋 Exiting...")
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
