import asyncio
import json
import os
import random
import sys
import tempfile
from datetime import datetime
import getpass

from telethon import TelegramClient, errors
from telethon.tl.types import Channel, User
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.contacts import BlockRequest

# --- Constants ---
DEFAULT_SESSION = "telegram_cleanup"
CONCURRENCY_LIMIT = 2

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

class AdaptiveRateLimiter:
    """Intelligently manages delays and concurrency to avoid FloodWaitErrors."""
    def __init__(self, base_delay=0.6):
        self.base_delay = base_delay
        self.current_delay = base_delay
        self.multiplier = 1.0
        self.max_concurrency = 5
        self.concurrency = 2 # Start with a safe concurrency

    async def wait(self):
        # Destructive actions need a gap
        delay = (self.current_delay * self.multiplier) + (random.random() * 0.2)
        await asyncio.sleep(delay)

    def backoff(self, seconds):
        """Increases the delay significantly and drops concurrency after a FloodWait."""
        self.multiplier = min(self.multiplier * 2.2, 10.0)
        self.current_delay = max(self.current_delay, seconds / 10.0)
        self.concurrency = 1 # Drop to safety
        print(f"⚠️  Limiter: Backing off. Concurrency set to 1. Base delay: {self.current_delay:.1f}s")

    def cooldown(self):
        """Slowly reduces the multiplier and increases concurrency when things are working well."""
        self.multiplier = max(1.0, self.multiplier * 0.85)
        if self.multiplier < 1.5 and self.concurrency < self.max_concurrency:
            if random.random() < 0.25: # Faster ramp up
                self.concurrency += 1
                print(f"📈 Limiter: Increasing concurrency to {self.concurrency}")

class TelegramCleaner:
    """A class to encapsulate the logic for cleaning a Telegram account."""

    def __init__(self, config, session_name=DEFAULT_SESSION, progress_callback=None):
        """
        Initializes the TelegramCleaner.
        Args:
            config (dict): api_id, api_hash, and phone (optional).
            session_name (str): Unique session name for this user.
            progress_callback (callable): Async function to report progress.
        """
        # Use a sessions/ directory for better security and organization
        os.makedirs("sessions", exist_ok=True)
        session_path = os.path.join("sessions", session_name)

        self.client = TelegramClient(session_path, config["api_id"], config["api_hash"])
        self.phone = config.get("phone")
        self.session_name = session_name
        self.pref_file = os.path.join("sessions", f"{session_name}_prefs.json")
        self.progress_file = os.path.join("sessions", f"{session_name}_progress.json")

        self.progress_callback = progress_callback
        self.logs = self._init_logs()
        self.prefs = {"kept_items": []}
        self.progress = {"processed_ids": []}
        self.whitelist_ids = set()
        self.system_whitelist_ids = set()
        self.whitelist_usernames = set()
        self.whitelist_titles = set()
        self.whitelist_counts = {"channels": 0, "groups": 0, "bots": 0, "users": 0}
        self.semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        self.limiter = AdaptiveRateLimiter()

    async def log_and_report(self, message):
        """Prints a message and optionally reports it via the callback."""
        print(message)
        if self.progress_callback:
            await self.progress_callback(message)

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
            with open(self.pref_file, "r") as f:
                self.prefs = json.load(f)
                # Migration: if old kept_bots exists, move to kept_items
                if "kept_bots" in self.prefs:
                    if "kept_items" not in self.prefs:
                        self.prefs["kept_items"] = self.prefs["kept_bots"]
                    del self.prefs["kept_bots"]
        except FileNotFoundError:
            self.prefs = {"kept_items": []}

        try:
            with open(self.progress_file, "r") as f:
                self.progress = json.load(f)
        except FileNotFoundError:
            self.progress = {"processed_ids": []}

        print(f"📋 Loaded preferences and progress for {self.session_name}")

    def _save_data(self):
        """Saves preferences, progress, and logs to files."""
        _atomic_write(self.pref_file, self.prefs)

        _atomic_write(self.progress_file, self.progress)

        log_file = f"cleanup_{self.session_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        _atomic_write(log_file, self.logs)
        print(f"📝 State saved for {self.session_name}")

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

    async def _process_dialog(self, entity, ignore_processed=False, semaphore=None):
        """Processes a single dialog entity with concurrency control."""
        sem = semaphore or self.semaphore
        async with sem:
            return await self._process_dialog_internal(entity, ignore_processed=ignore_processed)

    async def _process_dialog_internal(self, entity, retry_count=0, ignore_processed=False):
        """Internal logic for processing a single dialog entity."""
        name = entity.title if hasattr(entity, 'title') else (getattr(entity, 'username', None) or f"ID: {entity.id}")

        if not ignore_processed and entity.id in self.progress["processed_ids"]:
            return True

        if self._is_whitelisted(entity):
            if name not in self.logs["skipped_items"]:
                self.logs["skipped_items"].append(name)
                await self.log_and_report(f"💎 [WHITELISTED] {name}")
            self.progress["processed_ids"].append(entity.id)
            return True

        # Adaptive Rate Limiting wait
        await self.limiter.wait()

        try:
            if isinstance(entity, Channel):
                await self.client(LeaveChannelRequest(entity))
                log_key = "channels_left" if getattr(entity, 'broadcast', False) else "groups_left"
                self.logs[log_key] += 1
                await self.log_and_report(f"🚪 Left {'channel' if log_key == 'channels_left' else 'group'}: {name}")
            elif isinstance(entity, User):
                if entity.bot:
                    await self.client(BlockRequest(entity.id))
                    await self.client.delete_dialog(entity, revoke=True)
                    self.logs["bots_blocked_deleted"] += 1
                    await self.log_and_report(f"⛔ Blocked and deleted bot: {name}")
                else:
                    await self.client.delete_dialog(entity, revoke=True)
                    self.logs["private_chats_blocked_deleted"] += 1
                    await self.log_and_report(f"🗑️  Deleted private chat: {name}")
            else:
                print(f"⚠️ Skipping unknown entity: {name}")
                self.logs["errors"].append(f"Unknown entity: {name}")

            self.progress["processed_ids"].append(entity.id)
            self.limiter.cooldown() # Things are working well
            return True
        except errors.FloodWaitError as e:
            self.limiter.backoff(e.seconds)
            wait_time = e.seconds + 5
            if retry_count < 7:
                await self.log_and_report(f"⏳ [RATE LIMIT] Hit for {name}, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                return await self._process_dialog_internal(entity, retry_count + 1, ignore_processed=ignore_processed)
            else:
                await self.log_and_report(f"❌ [FAILED] Max retries reached for {name}")
                return False
        except Exception as e:
            await self.log_and_report(f"⚠️ Error processing {name}: {str(e)}")
            self.logs["errors"].append(f"Error processing {name}: {str(e)}")
            return False

    async def _prepare_whitelist(self, user_kept_items):
        """Resolves whitelisted items to IDs, usernames, and titles."""
        combined_items = set(self.prefs.get("kept_items", [])) | user_kept_items
        await self.log_and_report(f"\n🧠 [INTELLIGENCE] Analyzing {len(combined_items)} whitelist items...")

        for item in combined_items:
            item = str(item).strip()
            if not item:
                continue

            # print(f"📡 Resolving: {item}")
            await asyncio.sleep(0.05)

            # If it's a numeric ID
            if item.replace('-', '').isdigit():
                self.whitelist_ids.add(int(item))
                print(f"  ✅ Added by ID: {item}")
                continue

            # If it looks like a username or link
            if item.startswith("@") or 't.me/' in item:
                clean_item = item
                if 't.me/' in item:
                    username = item.split('t.me/')[-1].split('/')[0].split('?')[0]
                    clean_item = "@" + username

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

    async def _safe_iter_dialogs(self):
        """Iterates through dialogs with rate limit protection."""
        dialogs = []
        try:
            async for dialog in self.client.iter_dialogs(limit=None):
                dialogs.append(dialog)
                # Small jittered sleep during iteration to avoid flooding on large accounts
                if len(dialogs) % 20 == 0:
                    await asyncio.sleep(0.5 + random.random() * 0.5)
            return dialogs
        except errors.FloodWaitError as e:
            print(f"⏳ Rate limit hit fetching chats, waiting {e.seconds + 5} seconds...")
            await asyncio.sleep(e.seconds + 5)
            return await self._safe_iter_dialogs()

    async def run_cleanup(self, user_kept_items):
        """
        Runs the main cleanup process.
        Args:
            user_kept_items (set): A set of usernames, links, or names to keep.
        """
        self._load_data()

        await self.log_and_report("\n🚀 [INITIATING] Starting intelligent cleanup sequence...")

        # CLEAR OLD COUNTS FOR FRESH RUN
        self.whitelist_counts = {"channels": 0, "groups": 0, "bots": 0, "users": 0}

        # Always whitelist self (Saved Messages)
        try:
            me = await self.client.get_me()
            if me:
                self.whitelist_ids.add(me.id)
                self.system_whitelist_ids.add(me.id)
                if me.username:
                    self.whitelist_usernames.add(me.username.lower())
                await self.log_and_report(f"🛡️  [SECURE] Whitelisted your account (Saved Messages)")

            # PROTECT THE BOT ITSELF
            bot_me = await self.client.get_me() # This client's me is the userbot, wait.
            # No, I need the ID of the bot Lisa Kenny is talking to.
            # That's already passed via the bot_interface.py
        except errors.FloodWaitError as e:
            await self.log_and_report(f"⏳ Rate limit hit checking identity, waiting {e.seconds + 5}s...")
            await asyncio.sleep(e.seconds + 5)
            return await self.run_cleanup(user_kept_items)

        # Always whitelist Telegram service notifications
        self.whitelist_ids.add(777000)
        self.system_whitelist_ids.add(777000)

        # PROTECT THE BOT ITSELF IF RUNNING IN BOT MODE
        # (This is a safety double-check)
        await self._prepare_whitelist(user_kept_items)
        self._save_data() # Persist the updated whitelist immediately

        # --- Fetch Dialogs and Update Whitelist Counts ---
        await self.log_and_report("\n📊 [ANALYZING] Scanning your Telegram account...")
        dialogs = await self._safe_iter_dialogs()

        try:
            for dialog in dialogs:
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

            report = (
                f"\n📈 [REPORT] Scan Complete:\n"
                f"  - Total Chats Found: {len(dialogs)}\n"
                f"  - Whitelisted Channels: {self.whitelist_counts['channels']}\n"
                f"  - Whitelisted Groups: {self.whitelist_counts['groups']}\n"
                f"  - Whitelisted Bots: {self.whitelist_counts['bots']}\n"
                f"  - Whitelisted Users: {self.whitelist_counts['users']} (incl. you)"
            )
            await self.log_and_report(report)

        except Exception as e:
            await self.log_and_report(f"❌ Error fetching chats: {str(e)}")
            self.logs["errors"].append(f"Error fetching chats: {str(e)}")
            self._save_data()
            return

        await self.log_and_report("\n⏳ Starting cleanup in 5 seconds...")
        await asyncio.sleep(5)

        # --- Process in Smart Batches ---
        # First, quickly process whitelisted items in parallel (no delay needed)
        whitelisted_in_batch = [d for d in dialogs if self._is_whitelisted(d.entity)]
        non_whitelisted = [d for d in dialogs if not self._is_whitelisted(d.entity)]

        if whitelisted_in_batch:
            await self.log_and_report(f"⚡ Fast-tracking {len(whitelisted_in_batch)} whitelisted items...")
            fast_sem = asyncio.Semaphore(10) # High concurrency for non-destructive whitelist skips
            tasks = [self._process_dialog(d.entity, semaphore=fast_sem) for d in whitelisted_in_batch]
            await asyncio.gather(*tasks)

        # Then, process destructive actions with adaptive concurrency
        await self.log_and_report(f"🧹 Starting destructive cleanup for {len(non_whitelisted)} items...")

        i = 0
        total = len(non_whitelisted)
        while i < total:
            # Use current dynamic concurrency from limiter
            batch_size = self.limiter.concurrency
            batch = non_whitelisted[i : i + batch_size]

            # Report progress every batch
            if self.progress_callback:
                # Use a more compact report for the bot to avoid spam
                percentage = int((i/total)*100) if total > 0 else 100
                await self.progress_callback(f"⏳ **Progress:** {i}/{total} ({percentage}%) | **Speed:** {batch_size}x")
            else:
                print(f"📦 Progress: {i}/{total} (Concurrency: {batch_size})")

            # Create a temporary semaphore for this batch's concurrency
            batch_sem = asyncio.Semaphore(batch_size)
            tasks = [self._process_dialog(d.entity, semaphore=batch_sem) for d in batch]
            await asyncio.gather(*tasks)

            _atomic_write(self.progress_file, self.progress)
            i += batch_size

            # Dynamic gap between batches
            await asyncio.sleep(1 + random.random())

        # --- Verification Passes ---
        for pass_num in range(3):
            # Refresh the internal dialog cache with safety
            try:
                await self.client.get_dialogs(limit=None)
            except errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)

            all_dialogs = await self._safe_iter_dialogs()
            remaining_dialogs = [d for d in all_dialogs if not self._is_whitelisted(d.entity)]

            if not remaining_dialogs:
                await self.log_and_report(f"✅ Verification Pass {pass_num + 1}: Clean!")
                break

            await self.log_and_report(f"⚠️ Verification Pass {pass_num + 1}: {len(remaining_dialogs)} remain.")
            # Only list first few to avoid spamming the bot chat
            for d in remaining_dialogs[:5]:
                name = d.name if d.name else (getattr(d.entity, 'title', None) or getattr(d.entity, 'username', None) or f"ID: {d.id}")
                print(f"  🚩 Remaining: {name}")

            await self.log_and_report(f"🔄 Retrying cleanup...")
            tasks = [self._process_dialog(d.entity, ignore_processed=True) for d in remaining_dialogs if d.entity]
            await asyncio.gather(*tasks)
            _atomic_write(self.progress_file, self.progress)
            await asyncio.sleep(5)

        # --- Final Summary ---
        final_dialogs = await self._safe_iter_dialogs()
        self.logs["remaining_chats"] = len(final_dialogs)

        # Calculate user whitelisted items only for the summary report
        # Filter out system protection names
        system_names = ["Saved Messages", "Telegram", "ID: 777000"]
        user_skipped = [name for name in self.logs["skipped_items"]
                       if name not in system_names and not any(sn in name for sn in system_names)]

        summary = (
            f"\n🏆 [MISSION COMPLETE] Final Summary:\n"
            f"  🚪 Channels Left: {self.logs['channels_left']}\n"
            f"  🚪 Groups Left: {self.logs['groups_left']}\n"
            f"  ⛔ Bots Blocked/Deleted: {self.logs['bots_blocked_deleted']}\n"
            f"  🗑️  Private Chats Deleted: {self.logs['private_chats_blocked_deleted']}\n"
            f"  💎 Whitelist Preserved: {len(user_skipped)}\n"
            f"  🛡️  System Protected: {len(self.logs['skipped_items']) - len(user_skipped)}\n"
            f"  ⚠️ Errors: {len(self.logs['errors'])}\n"
            f"  📊 Remaining Chats: {self.logs['remaining_chats']}"
        )
        await self.log_and_report(summary)

        self._save_data()

async def main():
    """Example usage of the TelegramCleaner SDK."""
    try:
        from .config import load_config
    except ImportError:
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
