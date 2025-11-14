# Telegram Cleanup Script

This Python script (`telegram-cleanup`) automates the process of cleaning up a Telegram account by removing unwanted chats, including channels, groups, bots, and private messages, while preserving specified bots.

## Purpose

The script helps you reset your Telegram account to a clean state by:
- Leaving all channels and groups.
- Blocking and deleting all bots, except those you specify (e.g., `@Somnia_testbot`).
- Blocking and deleting all private chats, including "deleted account" chats.
- Ensuring no chats remain, mimicking a fresh Telegram account.

## Prerequisites

- **Python 3.6+**: Install Python on Termux or desktop.
- **Telegram API Credentials**: From [my.telegram.org](https://my.telegram.org).

## Getting Telegram API Credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.
2. Click **API development tools**.
3. Create an application:
   - **App title**: Any name (e.g., "Telegram Cleanup").
   - **Short name**: Any short name.
   - **Platform**: "Other".
   - **Description**: Optional.
4. Click **Create application**.
5. Copy `API_ID` and `API_HASH`.
6. Note your `PHONE` (e.g., `+1234567890`).

## Setup Instructions

1. **Clone the Repository**
   ```bash
   git clone https://github.com/thirdbase1/telegram-cleanup.git
   cd telegram-cleanup
   ```

2. **Create `.env` File**
   ```bash
   cp .ENV.example .env
   nano .env
   ```
   Add your credentials:
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   PHONE=+your_phone_number
   ```

3. **Install the Script**

   **Termux:**
   ```bash
   pkg update && pkg upgrade
   pkg install python git
   pip install .
   ```

   **Desktop:**
   ```bash
   pip install .
   ```

4. **Run the Script**
   ```bash
   telegram-cleanup
   ```
   - Enter the Telegram verification code.
   - Enter 2FA password if enabled.
   - Input bots to keep (e.g., @Somnia_testbot) or "none".

## Sample Output

```
✅ Logged in successfully
📋 Loaded preferences and progress
📝 Enter usernames of bots you created (comma-separated, e.g., @MyBot1,@MyBot2, or none): @Somnia_testbot
📊 Found 150 chats
⏳ Waiting 20 seconds before starting cleanup...
📦 Using batch size: 8
📦 Processing batch 1 (8 chats)
🚪 Left channel: Airdrop Hunter Siêu Tốc💰
🚪 Left group: XM Trading Academy
⏩ Skipping bot: Somnia
⛔ Blocked and deleted bot: sachi_games_bot
🗑️ Deleted private chat (deleted account): ID: 123456
✅ Verification Pass 1: Telegram account is clean, no chats remaining
📊 Cleanup Summary:
Channels left: 50
Groups left: 50
Bots blocked and deleted: 20
Private chats blocked and deleted: 30
Skipped bots: 2
Errors encountered: 0
📝 Log saved to cleanup_log_20250905_224100.json
✅ Final Success: Telegram account is clean, no chats remaining
✅ Preferences saved
```

## Files

- `src/telegram_cleanup.py`: Main cleanup script.
- `src/config.py`: Configuration loader.
- `setup.py`: Installation script.
- `.ENV.example`: Template for `.env`.
- `telegram_prefs.json`: Bot exclusions (generated).
- `cleanup_progress.json`: Progress tracking (generated).
- `cleanup_log_*.json`: Action logs (generated).
- `telegram_cleanup.session`: Session file (generated, do not share).

## Features

- Retries rate limits up to 10 times with backoff.
- Processes chats in batches (5–20).
- Runs 4 verification passes.
- Resumes from interruptions via `cleanup_progress.json`.
- Skips specified bots.
- Logs to `cleanup_log_*.json`.

## Notes

- **Irreversible Actions:** Blocking, leaving, and deleting are permanent. Test on a secondary account.
- **Sensitive Files:** Keep `.env`, `telegram_cleanup.session`, `telegram_prefs.json`, `cleanup_progress.json`, and `cleanup_log_*.json` private.
- **Rate Limits:** Script pauses up to 5 minutes if needed.

## Troubleshooting

- **Authentication Errors:**
  - Verify `.env` credentials.
  - Delete and retry:
    ```bash
    rm telegram_cleanup.session
    telegram-cleanup
    ```
- **Rate Limits:**  
  Rerun to resume from `cleanup_progress.json`.
- **Termux Storage:**  
  Run `termux-setup-storage` if you encounter storage errors.
- **Other Errors:**  
  Check `cleanup_log_*.json` for details.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
