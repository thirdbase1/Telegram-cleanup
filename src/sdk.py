import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
import getpass

from telethon import TelegramClient, errors
from telethon.tl.types import Channel, User
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.contacts import BlockRequest

# --- Constants ---
SESSION_NAME = "telegram_cleanup"
PREF_FILE = "telegram_prefs.json"
PROGRESS_FILE = "cleanup_progress.json"

# --- Utility: Atomic File Writing ---
def _atomic_write(filename, data):
    """Safely write JSON data to a file atomically."""
    try:
        with tempfile.NamedTemporaryFile('w', delete=False, dir='.') as tf:
            json.dump(data, tf, indent=4)
            tempname = tf.name
        os.replace(tempname, filename)
    except Exception as e:
        print(f"⚠️ Atomic write failed for {filename}: {str(e)}")

class TelegramCleaner:
    """A class to encapsulate the logic for cleaning a Telegram account."""

    def __init__(self, config):
        """
        Initializes the TelegramCleaner.
        Args:
            config (dict): A dictionary containing api_id, api_hash, and phone.
        """
        self.client = TelegramClient(SESSION_NAME, config["api_id"], config["api_hash"])
        self.phone = config["phone"]
        self.logs = self._init_logs()
        self.prefs = {"kept_bots": []}
        self.progress = {"processed_ids": []}

    def _init_logs(self):
        """Initializes the log dictionary."""
        return {
            "channels_left": 0,
            "groups_left": 0,
            "bots_blocked_deleted": 0,
            "private_chats_blocked_deleted": 0,
            "errors": [],
            "skipped_bots": [],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "remaining_chats": 0
        }

    async def connect(self):
        """Connects to the Telegram client."""
        try:
            await self.client.start(phone=self.phone)
            print("✅ Logged in successfully")
        except errors.PhoneNumberInvalidError:
            print("❌ Error: Invalid phone number format")
            sys.exit(1)
        except errors.SessionPasswordNeededError:
            password = getpass.getpass("🔑 Enter 2FA password: ")
            try:
                await self.client.sign_in(password=password)
            except Exception as e:
                print(f"❌ 2FA error: {str(e)}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Login error: {str(e)}")
            sys.exit(1)

    async def disconnect(self):
        """Disconnects the Telegram client."""
        await self.client.disconnect()

    def _load_data(self):
        """Loads preferences and progress from files."""
        try:
            with open(PREF_FILE, "r") as f:
                self.prefs = json.load(f)
        except FileNotFoundError:
            self.prefs = {"kept_bots": []}

        try:
            with open(PROGRESS_FILE, "r") as f:
                self.progress = json.load(f)
        except FileNotFoundError:
            self.progress = {"processed_ids": []}

        print("📋 Loaded preferences and progress")

    def _save_data(self):
        """Saves preferences, progress, and logs to files."""
        _atomic_write(PREF_FILE, self.prefs)
        print("✅ Preferences saved")

        _atomic_write(PROGRESS_FILE, self.progress)

        log_file = f"cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        _atomic_write(log_file, self.logs)
        print(f"📝 Log saved to {log_file}")

    async def _process_dialog(self, entity):
        """Processes a single dialog entity."""
        name = entity.title if hasattr(entity, 'title') else entity.username or f"ID: {entity.id}"
        if entity.id in self.progress["processed_ids"]:
            print(f"⏩ Already processed: {name}")
            return True

        try:
            if isinstance(entity, Channel):
                await self.client(LeaveChannelRequest(entity))
                log_key = "channels_left" if getattr(entity, 'broadcast', False) else "groups_left"
                self.logs[log_key] += 1
                print(f"🚪 Left {'channel' if log_key == 'channels_left' else 'group'}: {name}")
            elif isinstance(entity, User):
                if entity.bot:
                    username = (entity.username or "").lower()
                    if username in self.prefs["kept_bots"]:
                        print(f"⏩ Skipping bot: {name}")
                        if name not in self.logs["skipped_bots"]:
                            self.logs["skipped_bots"].append(name)
                    else:
                        await self.client(BlockRequest(entity.id))
                        await self.client.delete_dialog(entity)
                        self.logs["bots_blocked_deleted"] += 1
                        print(f"⛔ Blocked and deleted bot: {name}")
                else:
                    await self.client(BlockRequest(entity.id))
                    await self.client.delete_dialog(entity)
                    self.logs["private_chats_blocked_deleted"] += 1
                    print(f"⛔ Blocked and deleted private chat: {name}")
            else:
                print(f"⚠️ Skipping unknown entity: {name}")
                self.logs["errors"].append(f"Unknown entity: {name}")

            self.progress["processed_ids"].append(entity.id)
            await asyncio.sleep(0.5)
            return True
        except errors.FloodWaitError as e:
            wait_time = min(e.seconds, 300)
            print(f"⏳ Rate limit hit for {name}, waiting {wait_time} seconds")
            await asyncio.sleep(wait_time)
            return await self._process_dialog(entity) # Retry
        except Exception as e:
            print(f"⚠️ Error processing {name}: {str(e)}")
            self.logs["errors"].append(f"Error processing {name}: {str(e)}")
            return False

    async def run_cleanup(self, user_kept_bots):
        """
        Runs the main cleanup process.
        Args:
            user_kept_bots (set): A set of bot usernames to keep, provided by the user.
        """
        self._load_data()
        self.prefs["kept_bots"] = sorted(list(set(self.prefs.get("kept_bots", [])) | user_kept_bots))

        # --- Fetch Dialogs ---
        dialogs = []
        try:
            async for dialog in self.client.iter_dialogs(limit=None):
                dialogs.append(dialog)
            print(f"📊 Found {len(dialogs)} chats")
        except Exception as e:
            print(f"❌ Error fetching chats: {str(e)}")
            self.logs["errors"].append(f"Error fetching chats: {str(e)}")
            self._save_data()
            return

        print("⏳ Waiting 20 seconds before starting cleanup...")
        await asyncio.sleep(20)

        # --- Process in Batches ---
        batch_size = max(5, min(20, len(dialogs) // 20 + 1))
        for i in range(0, len(dialogs), batch_size):
            batch = dialogs[i:i + batch_size]
            tasks = [self._process_dialog(d.entity) for d in batch if d.entity]
            await asyncio.gather(*tasks)
            _atomic_write(PROGRESS_FILE, self.progress) # Save progress between batches
            await asyncio.sleep(10)

        # --- Verification Passes ---
        for pass_num in range(4):
            dialogs = [d async for d in self.client.iter_dialogs(limit=None)]
            if not dialogs:
                print(f"✅ Verification Pass {pass_num + 1}: Telegram account is clean.")
                break

            print(f"⚠️ Verification Pass {pass_num + 1}: {len(dialogs)} chats remain, retrying...")
            tasks = [self._process_dialog(d.entity) for d in dialogs if d.entity]
            await asyncio.gather(*tasks)
            _atomic_write(PROGRESS_FILE, self.progress)
            await asyncio.sleep(10)

        # --- Final Summary ---
        final_dialogs = [d async for d in self.client.iter_dialogs(limit=None)]
        self.logs["remaining_chats"] = len(final_dialogs)
        print("\n📊 Cleanup Summary:")
        for key, value in self.logs.items():
            if isinstance(value, list):
                print(f"{key.replace('_', ' ').title()}: {len(value)}")
            else:
                print(f"{key.replace('_', ' ').title()}: {value}")

        self._save_data()

async def main():
    """Example usage of the TelegramCleaner SDK."""
    from config import load_config
    config = load_config()

    cleaner = TelegramCleaner(config)
    await cleaner.connect()

    user_input = input("📝 Enter bots to keep (comma-separated): ")
    kept_bots = {b.strip().lower() for b in user_input.split(",") if b.strip()}

    await cleaner.run_cleanup(kept_bots)
    await cleaner.disconnect()

if __name__ == "__main__":
    # This allows the SDK to be tested independently.
    asyncio.run(main())
