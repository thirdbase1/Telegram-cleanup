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
CONCURRENCY_LIMIT = 5

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
        self.prefs = {"kept_items": []}
        self.progress = {"processed_ids": []}
        self.whitelist_ids = set()
        self.whitelist_usernames = set()
        self.whitelist_titles = set()
        self.whitelist_counts = {"channels": 0, "groups": 0, "bots": 0, "users": 0}
        self.semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    def _init_logs(self):
        """Initializes the log dictionary."""
        return {
            "channels_left": 0,
            "groups_left": 0,
            "bots_blocked_deleted": 0,
            "private_chats_blocked_deleted": 0,
            "errors": [],
            "skipped_items": [],
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
                # Migration: if old kept_bots exists, move to kept_items
                if "kept_bots" in self.prefs:
                    if "kept_items" not in self.prefs:
                        self.prefs["kept_items"] = self.prefs["kept_bots"]
                    del self.prefs["kept_bots"]
        except FileNotFoundError:
            self.prefs = {"kept_items": []}

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

    def _is_whitelisted(self, entity):
        """Checks if an entity is in the whitelist and updates counts if it's the first time."""
        is_kept = False
        # Check by ID
        if entity.id in self.whitelist_ids:
            is_kept = True

        # Check by username
        if not is_kept and hasattr(entity, 'username') and entity.username:
            if entity.username.lower() in self.whitelist_usernames:
                is_kept = True

        # Check by title (for channels/groups) or first_name/last_name (for users)
        if not is_kept:
            name = ""
            if hasattr(entity, 'title'):
                name = entity.title
            elif hasattr(entity, 'first_name'):
                name = entity.first_name
                if getattr(entity, 'last_name', None):
                    name += f" {entity.last_name}"

            if name and name in self.whitelist_titles:
                is_kept = True

        return is_kept

    async def _process_dialog(self, entity):
        """Processes a single dialog entity with concurrency control."""
        async with self.semaphore:
            return await self._process_dialog_internal(entity)

    async def _process_dialog_internal(self, entity, retry_count=0):
        """Internal logic for processing a single dialog entity."""
        name = entity.title if hasattr(entity, 'title') else (getattr(entity, 'username', None) or f"ID: {entity.id}")

        if entity.id in self.progress["processed_ids"]:
            return True

        if self._is_whitelisted(entity):
            print(f"💎 [WHITELISTED] {name}")
            if name not in self.logs["skipped_items"]:
                self.logs["skipped_items"].append(name)
            self.progress["processed_ids"].append(entity.id)
            return True

        print(f"🔍 [SCANNING] {name}...")
        await asyncio.sleep(0.4) # Slightly more delay for better observation

        try:
            if isinstance(entity, Channel):
                await self.client(LeaveChannelRequest(entity))
                log_key = "channels_left" if getattr(entity, 'broadcast', False) else "groups_left"
                self.logs[log_key] += 1
                print(f"🚪 Left {'channel' if log_key == 'channels_left' else 'group'}: {name}")
            elif isinstance(entity, User):
                if entity.bot:
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
            await asyncio.sleep(0.1) # Reduced delay due to semaphore
            return True
        except errors.FloodWaitError as e:
            wait_time = min(e.seconds, 300)
            if retry_count < 5:
                print(f"⏳ Rate limit hit for {name}, waiting {wait_time} seconds (Retry {retry_count+1})")
                await asyncio.sleep(wait_time)
                return await self._process_dialog_internal(entity, retry_count + 1)
            else:
                print(f"❌ Max retries reached for {name} due to rate limits.")
                return False
        except Exception as e:
            print(f"⚠️ Error processing {name}: {str(e)}")
            self.logs["errors"].append(f"Error processing {name}: {str(e)}")
            return False

    async def _prepare_whitelist(self, user_kept_items):
        """Resolves whitelisted items to IDs, usernames, and titles."""
        combined_items = set(self.prefs.get("kept_items", [])) | user_kept_items
        print(f"\n🧠 [INTELLIGENCE] Analyzing {len(combined_items)} whitelist items...")

        for item in combined_items:
            item = str(item).strip()
            if not item:
                continue

            print(f"📡 Resolving: {item}")
            await asyncio.sleep(0.1)

            # If it's a numeric ID
            if item.replace('-', '').isdigit():
                self.whitelist_ids.add(int(item))
                print(f"  ✅ Added by ID: {item}")
                continue

            # If it looks like a username or link
            if item.startswith("@") or item.startswith("https://t.me/") or item.startswith("t.me/"):
                clean_item = item
                if item.startswith("https://t.me/"):
                    clean_item = "@" + item[13:]
                elif item.startswith("t.me/"):
                    clean_item = "@" + item[5:]

                try:
                    entity = await self.client.get_entity(clean_item)
                    self.whitelist_ids.add(entity.id)
                    if hasattr(entity, 'username') and entity.username:
                        self.whitelist_usernames.add(entity.username.lower())
                    print(f"  ✅ Added by Entity: {item} (ID: {entity.id})")
                except Exception as e:
                    print(f"  ⚠️ Resolution failed for {item}, will use string match.")
                    self.whitelist_usernames.add(clean_item.lstrip("@").lower())
            else:
                # Treat as title or plain username
                self.whitelist_titles.add(item)
                self.whitelist_usernames.add(item.lower())
                print(f"  ✅ Added by Name/Title: {item}")

        self.prefs["kept_items"] = sorted(list(combined_items))

    async def run_cleanup(self, user_kept_items):
        """
        Runs the main cleanup process.
        Args:
            user_kept_items (set): A set of usernames, links, or names to keep.
        """
        self._load_data()

        print("\n🚀 [INITIATING] Starting intelligent cleanup sequence...")
        # Always whitelist self (Saved Messages)
        me = await self.client.get_me()
        if me:
            self.whitelist_ids.add(me.id)
            if me.username:
                self.whitelist_usernames.add(me.username.lower())
            print(f"🛡️  [SECURE] Automatically whitelisted your account (Saved Messages)")

        # Always whitelist Telegram service notifications
        self.whitelist_ids.add(777000)

        await self._prepare_whitelist(user_kept_items)
        self._save_data() # Persist the updated whitelist immediately

        # --- Fetch Dialogs and Update Whitelist Counts ---
        print("\n📊 [ANALYZING] Scanning your Telegram account to categorize items...")
        dialogs = []
        try:
            async for dialog in self.client.iter_dialogs(limit=None):
                entity = dialog.entity
                if self._is_whitelisted(entity):
                    if isinstance(entity, Channel):
                        if getattr(entity, 'broadcast', False):
                            self.whitelist_counts["channels"] += 1
                        else:
                            self.whitelist_counts["groups"] += 1
                    elif isinstance(entity, User):
                        if entity.bot:
                            self.whitelist_counts["bots"] += 1
                        else:
                            self.whitelist_counts["users"] += 1
                dialogs.append(dialog)

            print(f"\n📈 [REPORT] Scan Complete:")
            print(f"  - Total Chats Found: {len(dialogs)}")
            print(f"  - Whitelisted Channels: {self.whitelist_counts['channels']}")
            print(f"  - Whitelisted Groups: {self.whitelist_counts['groups']}")
            print(f"  - Whitelisted Bots: {self.whitelist_counts['bots']}")
            print(f"  - Whitelisted Private Users: {self.whitelist_counts['users']}")

        except Exception as e:
            print(f"❌ Error fetching chats: {str(e)}")
            self.logs["errors"].append(f"Error fetching chats: {str(e)}")
            self._save_data()
            return

        print("⏳ Waiting 20 seconds before starting cleanup...")
        await asyncio.sleep(20)

        # --- Process in Batches ---
        batch_size = 50 # Increased batch size since we have a semaphore and better rate limit handling
        for i in range(0, len(dialogs), batch_size):
            batch = dialogs[i:i + batch_size]
            print(f"📦 Processing batch {i//batch_size + 1}/{ (len(dialogs)-1)//batch_size + 1}")
            tasks = [self._process_dialog(d.entity) for d in batch if d.entity]
            await asyncio.gather(*tasks)
            _atomic_write(PROGRESS_FILE, self.progress) # Save progress between batches
            await asyncio.sleep(2) # Small break between batches

        # --- Verification Passes ---
        for pass_num in range(3):
            remaining_dialogs = []
            async for d in self.client.iter_dialogs(limit=None):
                if not self._is_whitelisted(d.entity):
                    remaining_dialogs.append(d)

            if not remaining_dialogs:
                print(f"✅ Verification Pass {pass_num + 1}: Telegram account is clean (excluding whitelisted).")
                break

            print(f"⚠️ Verification Pass {pass_num + 1}: {len(remaining_dialogs)} non-whitelisted chats remain, retrying...")
            tasks = [self._process_dialog(d.entity) for d in remaining_dialogs if d.entity]
            await asyncio.gather(*tasks)
            _atomic_write(PROGRESS_FILE, self.progress)
            await asyncio.sleep(5)

        # --- Final Summary ---
        final_dialogs = [d async for d in self.client.iter_dialogs(limit=None)]
        self.logs["remaining_chats"] = len(final_dialogs)
        print("\n🏆 [MISSION COMPLETE] Final Cleanup Summary:")
        print(f"  🚪 Channels Left: {self.logs['channels_left']}")
        print(f"  🚪 Groups Left: {self.logs['groups_left']}")
        print(f"  ⛔ Bots Blocked/Deleted: {self.logs['bots_blocked_deleted']}")
        print(f"  ⛔ Private Chats Blocked/Deleted: {self.logs['private_chats_blocked_deleted']}")
        print(f"  💎 Items Preserved (Whitelisted): {len(self.logs['skipped_items'])}")
        print(f"  ⚠️ Errors: {len(self.logs['errors'])}")
        print(f"  📊 Remaining Chats: {self.logs['remaining_chats']}")

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
