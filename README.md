# Telegram Cleanup Script

This Python script (`telegram-cleanup`) automates the process of cleaning up a Telegram account by removing unwanted chats, including channels, groups, bots, and private messages, while preserving specified bots.

For detailed installation instructions, see [INSTALL.md](INSTALL.md).

## Purpose

The script helps you reset your Telegram account to a clean state by:
- Leaving all channels and groups.
- Blocking and deleting all bots, except those you specify (e.g., `@Somnia_testbot`).
- Blocking and deleting all private chats, including "deleted account" chats.
- Ensuring no chats remain, mimicking a fresh Telegram account.

## Running the Script

You can run the cleanup process in two modes:

### 1. Terminal Mode (CLI)
Run the script directly in your terminal:
```bash
telegram-cleanup
```

### 2. Public Bot Mode
If you have a `BOT_TOKEN`, you can start the bot interface:
```bash
telegram-cleanup-bot
```
This allows you and others to perform cleanup via a Telegram chat with inline buttons.

## SDK Usage

This project also includes an SDK for programmatic use. You can import the `TelegramCleaner` class from `telegram_cleanup.sdk` to integrate the cleanup functionality into your own scripts.

### Example:

```python
import asyncio
from telegram_cleanup.config import load_config
from telegram_cleanup.sdk import TelegramCleaner

async def main():
    config = load_config()
    cleaner = TelegramCleaner(config)
    await cleaner.connect()

    user_input = input("📝 Enter items to keep (comma-separated): ")
    kept_items = {b.strip() for b in user_input.split(",") if b.strip()}

    await cleaner.run_cleanup(kept_items)
    await cleaner.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## Files

- `telegram_cleanup/telegram_cleanup.py`: The command-line entry point.
- `telegram_cleanup/bot_interface.py`: The Telegram Bot interface.
- `telegram_cleanup/sdk.py`: The core SDK with the `TelegramCleaner` class.
- `telegram_cleanup/config.py`: Configuration loader.
- `setup.py`: Installation script.
- `INSTALL.md`: Detailed installation guide.
- `.ENV.example`: Template for `.env`.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
