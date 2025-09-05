import asyncio
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, errors
from telethon.tl.types import Channel, User
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.contacts import BlockRequest

# Load environment variables
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")

# Validate credentials
if not all([API_ID, API_HASH, PHONE]):
    print("❌ Error: Missing API_ID, API_HASH, or PHONE in .env file")
    exit(1)

# Session and file paths
SESSION_NAME = "telegram_cleanup"
PREF_FILE = "telegram_prefs.json"
LOG_FILE = f"cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
PROGRESS_FILE = "cleanup_progress.json"

# Load preferences (for bot exclusions)
def load_preferences():
    try:
        with open(PREF_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"kept_bots": []}

# Save preferences
def save_preferences(prefs):
    try:
        with open(PREF_FILE, "w") as f:
            json.dump(prefs, f, indent=4)
        print("✅ Preferences saved")
    except Exception as e:
        print(f"⚠️ Error saving preferences: {str(e)}")

# Load progress
def load_progress():
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"processed_ids": []}

# Save progress
def save_progress(progress):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, indent=4)
    except Exception as e:
        print(f"⚠️ Error saving progress: {str(e)}")

# Save log
def save_log(logs):
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=4)
        print(f"📝 Log saved to {LOG_FILE}")
    except Exception as e:
        print(f"⚠️ Error saving log: {str(e)}")

async def process_dialog(client, entity, kept_bots, prefs, logs, progress, max_retries=10):
    name = entity.title if hasattr(entity, 'title') else entity.username or f"ID: {entity.id}"
    if entity.id in progress["processed_ids"]:
        print(f"⏩ Already processed: {name}")
        return True
    retry_count = 0
    while retry_count < max_retries:
        try:
            if isinstance(entity, Channel):
                await client(LeaveChannelRequest(entity))
                if entity.broadcast:
                    logs["channels_left"] += 1
                    print(f"🚪 Left channel: {name}")
                else:
                    logs["groups_left"] += 1
                    print(f"🚪 Left group: {name}")
            elif isinstance(entity, User):
                if entity.bot:
                    if (entity.username or "").lower() in kept_bots or (entity.username or "").lower() in prefs["kept_bots"]:
                        print(f"⏩ Skipping bot: {name}")
                        logs["skipped_bots"].append(name)
                    else:
                        await client(BlockRequest(entity.id))
                        await client.delete_dialog(entity)
                        logs["bots_blocked_deleted"] += 1
                        print(f"⛔ Blocked and deleted bot: {name}")
                else:
                    if entity.is_deleted:
                        await client.delete_dialog(entity)
                        logs["private_chats_blocked_deleted"] += 1
                        print(f"🗑️ Deleted private chat (deleted account): {name}")
                    else:
                        await client(BlockRequest(entity.id))
                        await client.delete_dialog(entity)
                        logs["private_chats_blocked_deleted"] += 1
                        print(f"⛔ Blocked and deleted private chat: {name}")
            else:
                print(f"⚠️ Skipping unknown entity: {name}")
                logs["errors"].append(f"Unknown entity: {name}")
            progress["processed_ids"].append(entity.id)
            save_progress(progress)  # Save progress after each successful action
            await asyncio.sleep(0.5)  # Small delay per action
            return True
        except errors.FloodWaitError as e:
            wait_time = min(e.seconds, 300)  # Cap at 5 minutes
            if e.seconds > 30:
                wait_time = min(30 * (2 ** retry_count), 300)  # Exponential backoff
            print(f"⏳ Rate limit hit for {name}, waiting {wait_time} seconds")
            await asyncio.sleep(wait_time)
            retry_count += 1
        except Exception as e:
            print(f"⚠️ Error processing {name}: {str(e)}")
            logs["errors"].append(f"Error processing {name}: {str(e)}")
            return False
    print(f"⚠️ Skipped {name} after {max_retries} retries due to rate limits")
    logs["errors"].append(f"Skipped {name} after {max_retries} retries due to rate limits")
    return False

async def main():
    # Initialize client
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    
    try:
        await client.start(phone=PHONE)
        print("✅ Logged in successfully")
    except errors.PhoneNumberInvalidError:
        print("❌ Error: Invalid phone number format")
        exit(1)
    except errors.SessionPasswordNeededError:
        password = input("🔑 Enter 2FA password: ")
        try:
            await client.sign_in(password=password)
        except Exception as e:
            print(f"❌ 2FA error: {str(e)}")
            exit(1)
    except Exception as e:
        print(f"❌ Login error: {str(e)}")
        exit(1)

    # Initialize logs
    logs = {
        "channels_left": 0,
        "groups_left": 0,
        "bots_blocked_deleted": 0,
        "private_chats_blocked_deleted": 0,
        "errors": [],
        "skipped_bots": [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "remaining_chats": 0
    }

    # Load preferences and progress
    prefs = load_preferences()
    progress = load_progress()
    print("📋 Loaded preferences and progress")

    # Prompt for bots to keep
    kept_bots = input("📝 Enter usernames of bots you created (comma-separated, e.g., @MyBot1,@MyBot2, or none): ").split(",")
    kept_bots = [b.strip().lower() for b in kept_bots if b.strip()]
    prefs["kept_bots"].extend([b for b in kept_bots if b not in prefs["kept_bots"]])

    # Fetch dialogs with retries
    max_retries = 10
    dialogs = []
    for attempt in range(max_retries):
        try:
            async for dialog in client.iter_dialogs(limit=None):  # Force fetch all dialogs
                dialogs.append(dialog)
            print(f"📊 Found {len(dialogs)} chats")
            break
        except errors.FloodWaitError as e:
            wait_time = min(e.seconds, 300)
            print(f"⏳ Rate limit hit fetching chats, waiting {wait_time} seconds (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"❌ Error fetching chats: {str(e)}")
            logs["errors"].append(f"Error fetching chats: {str(e)}")
            if attempt == max_retries - 1:
                print("❌ Max retries reached, exiting")
                save_log(logs)
                save_progress(progress)
                exit(1)
            await asyncio.sleep(10)

    # Wait 20 seconds after detecting chats
    print(f"⏳ Waiting 20 seconds before starting cleanup...")
    await asyncio.sleep(20)

    # Dynamic batch size
    chat_count = len(dialogs)
    batch_size = max(5, min(20, chat_count // 20 + 1))  # 5-20 based on chat count
    print(f"📦 Using batch size: {batch_size}")

    # Process dialogs in batches
    for i in range(0, len(dialogs), batch_size):
        batch = dialogs[i:i + batch_size]
        print(f"📦 Processing batch {i//batch_size + 1} ({len(batch)} chats)")
        tasks = [process_dialog(client, dialog.entity, kept_bots, prefs, logs, progress)
                 for dialog in batch if dialog.entity and dialog.entity.id not in progress["processed_ids"]]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(10)  # Increased delay to avoid rate limits
        save_progress(progress)

    # Four verification passes
    for pass_num in range(4):
        try:
            dialogs = []
            async for dialog in client.iter_dialogs(limit=None):
                dialogs.append(dialog)
            logs["remaining_chats"] = len(dialogs)
            if len(dialogs) == 0:
                print(f"✅ Verification Pass {pass_num + 1}: Telegram account is clean, no chats remaining")
                break
            print(f"⚠️ Verification Pass {pass_num + 1}: {len(dialogs)} chats remain, retrying...")
            for i in range(0, len(dialogs), batch_size):
                batch = dialogs[i:i + batch_size]
                print(f"📦 Verification Pass {pass_num + 1}, batch {i//batch_size + 1} ({len(batch)} chats)")
                tasks = [process_dialog(client, dialog.entity, kept_bots, prefs, logs, progress)
                         for dialog in batch if dialog.entity]
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(10)
            save_progress(progress)
        except errors.FloodWaitError as e:
            wait_time = min(e.seconds, 300)
            print(f"⏳ Rate limit hit during verification pass {pass_num + 1}, waiting {wait_time} seconds")
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"⚠️ Error in verification pass {pass_num + 1}: {str(e)}")
            logs["errors"].append(f"Error in verification pass {pass_num + 1}: {str(e)}")

    # Final verification
    try:
        dialogs = []
        async for dialog in client.iter_dialogs(limit=None):
            dialogs.append(dialog)
        logs["remaining_chats"] = len(dialogs)
        if len(dialogs) == 0:
            print("✅ Final Success: Telegram account is clean, no chats remaining")
        else:
            print(f"⚠️ Final Warning: {len(dialogs)} chats remain after all passes")
    except Exception as e:
        print(f"⚠️ Error in final verification: {str(e)}")
        logs["errors"].append(f"Error in final verification: {str(e)}")

    # Print summary
    print("\n📊 Cleanup Summary:")
    print(f"Channels left: {logs['channels_left']}")
    print(f"Groups left: {logs['groups_left']}")
    print(f"Bots blocked and deleted: {logs['bots_blocked_deleted']}")
    print(f"Private chats blocked and deleted: {logs['private_chats_blocked_deleted']}")
    print(f"Skipped bots: {len(logs['skipped_bots'])}")
    print(f"Errors encountered: {len(logs['errors'])}")

    # Save logs and preferences
    save_log(logs)
    save_preferences(prefs)
    save_progress(progress)
    await client.disconnect()

# Run the script
if __name__ == "__main__":
    logs = {}  # Define logs globally to avoid NameError
    progress = load_progress()  # Load progress early
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Exiting...")
        if logs:
            save_log(logs)
        save_progress(progress)
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
        if logs:
            save_log(logs)
        save_progress(progress)
