import asyncio
import os
import re
from telethon import TelegramClient, events, Button, errors
from telethon.sessions import StringSession
from .sdk import TelegramCleaner
from .config import load_config

# --- Bot State Management ---
# states: 'IDLE', 'WAITING_PHONE', 'WAITING_CODE', 'WAITING_2FA', 'READY', 'PREVIEWING', 'CLEANING'
user_states = {}
user_clients = {} # Store TelegramCleaner instances per user
user_whitelists = {}
user_dialogs = {} # Store dialogs for preview
user_filters = {} # Store user filters
active_tasks = {}
last_messages = {} # Track last bot message to keep chat clean

def main():
    """Entry point for the bot."""
    asyncio.run(start_bot())

async def start_bot(on_start=None):
    print("🚀 [Bot] Initialization started.")
    try:
        config = load_config()
        print(f"📦 [Bot] Config loaded: API_ID={config['api_id']}, API_HASH={config['api_hash'][:5]}***")
    except Exception as e:
        print(f"❌ [Bot] Configuration error: {e}")
        return

    token = config.get('bot_token')
    if not token:
        print("❌ [Bot] Error: BOT_TOKEN not found in environment variables.")
        return
    else:
        print(f"🔑 [Bot] BOT_TOKEN found (starts with: {token[:10]}...)")

    print("🛰️ [Bot] Connecting to Telegram...")
    try:
        os.makedirs("sessions", exist_ok=True)
        print("📁 [Bot] 'sessions' directory ready.")
    except Exception as e:
        print(f"⚠️ [Bot] Warning: Could not create 'sessions' directory: {e}")

    # Use StringSession for the bot to avoid SQLite locking issues in multi-worker environments
    # We try to load it from a file first for persistence
    bot_session_str = ""
    bot_session_file = os.path.join("sessions", "bot_session_string.txt")
    if os.path.exists(bot_session_file):
        with open(bot_session_file, "r") as f:
            bot_session_str = f.read().strip()

    print(f"📄 [Bot] Using StringSession (Persistent: {bool(bot_session_str)})")

    # Optimize Telethon for speed and stability
    bot = TelegramClient(
        StringSession(bot_session_str),
        config['api_id'],
        config['api_hash'],
        connection_retries=10,
        retry_delay=2,
        auto_reconnect=True,
        use_ipv6=True
    )

    try:
        print("⚡ [Bot] Calling bot.start()...")
        await bot.start(bot_token=token)
        print("✅ [Bot] bot.start() success!")

        bot_me = await bot.get_me()
        bot_username = bot_me.username
        bot_id = bot_me.id

        # Save session string for next restart
        with open(bot_session_file, "w") as f:
            f.write(bot.session.save())

        print(f"🤖 Bot is up and running as @{bot_username} (ID: {bot_id})!")
        if on_start:
            if asyncio.iscoroutinefunction(on_start):
                await on_start()
            else:
                on_start()
    except errors.rpcerrorlist.ApiIdInvalidError:
        print("❌ FATAL ERROR: Your API_ID or API_HASH is invalid.")
        print("💡 Please check your credentials at https://my.telegram.org")
        return
    except Exception as e:
        print(f"❌ Login error: {e}")
        return

    async def cleanup_old_message(sender_id):
        """Deletes the last bot message to prevent clutter."""
        if sender_id in last_messages:
            try: await bot.delete_messages(sender_id, last_messages[sender_id])
            except: pass

    @bot.on(events.NewMessage(pattern='/start'))
    async def handle_start(event):
        print(f"📥 Received /start from {event.sender_id}")
        sender_id = event.sender_id
        user_states[sender_id] = 'IDLE'
        # Run in background to avoid blocking the event loop
        asyncio.create_task(send_main_menu(event))

    @bot.on(events.NewMessage(pattern='/ping'))
    async def handle_ping(event):
        await event.respond("🏓 Pong! The bot is active and listening.")

    async def send_main_menu(event):
        sender_id = event.sender_id
        welcome_text = (
            "🚀 **Telegram Cleanup Bot — Privacy-First Account Reset**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Reset your Telegram account by removing unwanted chats, leaving inactive groups, and blocking spam bots — safely and efficiently.\n\n"
            "⚡ **Optimized Processing**\n"
            "• Intelligent batching system\n"
            "• Automatic flood-wait handling\n"
            "• Safe parallel execution\n"
            "• Designed to handle 1,000+ memberships reliably\n\n"
            "🔒 **Privacy by Design**\n"
            "• Uses Telegram’s official MTProto login (no password access)\n"
            "• Session stored temporarily and encrypted\n"
            "• One-click “Logout & Wipe” permanently deletes:\n"
            "  - Session files\n"
            "  - Cached data\n"
            "  - Active connections\n"
            "  - Database records\n"
            "• Fully open-source & auditable\n\n"
            "💡 **Flexible Whitelist**\n"
            "Keep important chats by:\n"
            "• Username (@Michael)\n"
            "• Public link (t.me/MyChannel)\n"
            "• Numeric ID (1685547486)"
        )

        # Fast Login Check: Don't call network if we already know they are active
        cleaner = user_clients.get(sender_id)
        is_logged_in = False
        if cleaner:
            if cleaner.client.is_connected():
                # If connected, use the faster local check
                is_logged_in = await cleaner.client.is_user_authorized()
            else:
                # If disconnected, it's safer to assume not logged in for the UI
                is_logged_in = False

        buttons = []
        if not is_logged_in:
            buttons.append([Button.inline("🔑 Step 1: Login", b"login")])
        else:
            buttons.append([Button.inline("✅ Logged In", b"already_logged_in")])

        buttons.append([Button.inline("📜 Step 2: Set Whitelist", b"set_whitelist")])

        if is_logged_in:
            buttons.append([Button.inline("🚀 Step 3: Start Cleanup", b"run_cleanup")])
            buttons.append([Button.inline("🚪 Logout & Wipe Data", b"logout")])

        if isinstance(event, events.CallbackQuery.Event):
            try:
                msg = await event.edit(welcome_text, buttons=buttons)
                last_messages[sender_id] = msg.id
            except:
                await cleanup_old_message(sender_id)
                msg = await event.respond(welcome_text, buttons=buttons)
                last_messages[sender_id] = msg.id
        else:
            await cleanup_old_message(sender_id)
            msg = await event.respond(welcome_text, buttons=buttons)
            last_messages[sender_id] = msg.id

    @bot.on(events.CallbackQuery(data=b"already_logged_in"))
    async def handle_already_logged_in(event):
        try: await event.answer("✅ You are already logged in!", alert=True)
        except: pass

    @bot.on(events.CallbackQuery(data=b"login"))
    async def handle_login_click(event):
        # Answer instantly
        try: await event.answer()
        except: pass

        sender_id = event.sender_id
        user_states[sender_id] = 'WAITING_PHONE'
        text = (
            "📱 **Step 1: Secure Login**\n\n"
            "Please enter your phone number in international format (e.g., `+1234567890`).\n\n"
            "🛡️ **Trust & Privacy:**\n"
            "• This creates a temporary session on our server to perform the cleanup.\n"
            "• You can terminate this session at any time from your Telegram app settings.\n"
            "• Use 'Logout & Wipe' later to delete all your data here."
        )
        buttons = [[Button.inline("🔙 Back", b"back_to_start")]]
        try:
            msg = await event.edit(text, buttons=buttons)
            last_messages[sender_id] = msg.id
        except:
            await cleanup_old_message(sender_id)
            msg = await event.respond(text, buttons=buttons)
            last_messages[sender_id] = msg.id

    @bot.on(events.CallbackQuery(data=b"set_whitelist"))
    async def handle_whitelist_click(event):
        await event.answer()
        sender_id = event.sender_id

        if user_states.get(sender_id) == 'CLEANING':
            await event.respond("⚠️ Cannot update whitelist while cleanup is running!", buttons=[Button.inline("🔙 Back", b"back_to_start")])
            return

        # Sync with persistent data
        cleaner = user_clients.get(sender_id)
        if cleaner:
            cleaner._load_data()
            items = cleaner.prefs.get("kept_items", [])
            user_whitelists[sender_id] = list(set(user_whitelists.get(sender_id, []) + items))

        current = ", ".join(user_whitelists.get(sender_id, [])) or "None"
        text = (
            f"📝 **Current Whitelist:** `{current}`\n\n"
            "Send me usernames (@name), links, or IDs to keep.\n"
            "💡 Items you send will be ADDED to the current list."
        )
        buttons = [[Button.inline("🔙 Back", b"back_to_start")]]
        try:
            msg = await event.edit(text, buttons=buttons)
            last_messages[sender_id] = msg.id
        except:
            await cleanup_old_message(sender_id)
            msg = await event.respond(text, buttons=buttons)
            last_messages[sender_id] = msg.id
        user_states[sender_id] = 'SETTING_WHITELIST'

    @bot.on(events.CallbackQuery(data=b"back_to_start"))
    async def handle_back(event):
        # Answer instantly
        try: await event.answer()
        except: pass

        asyncio.create_task(send_main_menu(event))

    @bot.on(events.NewMessage())
    async def handle_all_messages(event):
        # Only handle private messages
        if not event.is_private: return
        sender_id = event.sender_id
        state = user_states.get(sender_id, 'IDLE')
        text = event.text.strip()

        if text.startswith('/'): return # Ignore other commands

        if state == 'WAITING_PHONE':
            # Clean up old client if exists
            old_cleaner = user_clients.get(sender_id)
            if old_cleaner:
                try: await old_cleaner.client.disconnect()
                except: pass

            await cleanup_old_message(sender_id)
            msg = await event.respond("⏳ Sending login code...")
            last_messages[sender_id] = msg.id
            session_name = f"user_{sender_id}"

            # Use bot's own API credentials for the user client
            config = load_config()

            async def progress_report(msg):
                try:
                    await bot.send_message(sender_id, msg)
                except Exception as e:
                    print(f"Error sending progress: {e}")

            cleaner = TelegramCleaner(config, session_name=session_name, progress_callback=progress_report)

            # PROTECT THE BOT ITSELF FROM BEING DELETED
            if bot_username:
                cleaner.whitelist_usernames.add(bot_username.lower())
            if bot_id:
                cleaner.whitelist_ids.add(bot_id)
                cleaner.system_whitelist_ids.add(bot_id)

            print(f"🛡️  Added bot protection (ID: {bot_id}) to whitelist for {session_name}")

            user_clients[sender_id] = cleaner

            try:
                await cleaner.client.connect()
                send_code_result = await cleaner.client.send_code_request(text)
                cleaner.phone = text
                cleaner.phone_code_hash = send_code_result.phone_code_hash
                user_states[sender_id] = 'WAITING_CODE'

                msg = (
                    "📩 **Login Code Sent!**\n\n"
                    "🔒 **Security Note:** This code is sent directly to Telegram to authorize this session. "
                    "We do not store your credentials. Once you finish, you can 'Logout' to wipe everything.\n\n"
                    "⚠️ **IMPORTANT:** To prevent Telegram from cancelling the code, do NOT send it as a plain number.\n\n"
                    "Please send it in this format: `code: 1 2 3 4 5` (add 'code:' and spaces between digits)."
                )
                await event.respond(msg, parse_mode='markdown')
            except Exception as e:
                await event.respond(f"❌ Error: {str(e)}\nTry /start again.")
                user_states[sender_id] = 'IDLE'

        elif state == 'WAITING_CODE':
            cleaner = user_clients.get(sender_id)
            try:
                # Clean the code: remove 'code:', spaces, and other non-digit chars
                clean_code = re.sub(r'\D', '', text)
                if not clean_code or len(clean_code) < 5:
                    await cleanup_old_message(sender_id)
                    msg = await event.respond("❌ Invalid format. Please send like: `code: 1 2 3 4 5`")
                    last_messages[sender_id] = msg.id
                    return

                await cleaner.client.sign_in(cleaner.phone, clean_code, phone_code_hash=cleaner.phone_code_hash)
                await finish_login(event, sender_id)
            except errors.SessionPasswordNeededError:
                user_states[sender_id] = 'WAITING_2FA'
                await cleanup_old_message(sender_id)
                msg = await event.respond("🔑 2FA detected. Please enter your Cloud Password:")
                last_messages[sender_id] = msg.id
            except Exception as e:
                await cleanup_old_message(sender_id)
                msg = await event.respond(f"❌ Error: {str(e)}")
                last_messages[sender_id] = msg.id

        elif state == 'WAITING_2FA':
            cleaner = user_clients.get(sender_id)
            try:
                await cleaner.client.sign_in(password=text)
                await finish_login(event, sender_id)
            except Exception as e:
                await cleanup_old_message(sender_id)
                msg = await event.respond(f"❌ Incorrect password: {str(e)}")
                last_messages[sender_id] = msg.id

        elif state == 'SETTING_WHITELIST':
            # Clean user input: remove parentheses etc
            raw_items = text.replace('(', '').replace(')', '').split(',')
            new_items = [i.strip() for i in raw_items if i.strip()]

            existing = user_whitelists.get(sender_id, [])
            updated = list(set(existing + new_items))
            user_whitelists[sender_id] = updated

            # Persist if logged in
            cleaner = user_clients.get(sender_id)
            if cleaner:
                cleaner.prefs["kept_items"] = updated
                cleaner._save_data()

            user_states[sender_id] = 'IDLE'
            await cleanup_old_message(sender_id)
            msg = await event.respond(f"✅ Whitelist updated! Total items: {len(updated)}", buttons=[
                [Button.inline("🔙 Back to Menu", b"back_to_start")]
            ])
            last_messages[sender_id] = msg.id

    async def finish_login(event, sender_id):
        user_states[sender_id] = 'READY'
        await cleanup_old_message(sender_id)
        text = (
            "✅ **Successfully logged in!**\n\n"
            "Your temporary session is now active. You are in full control.\n\n"
            "⚡ **Ready to Clean?** I will analyze your chats and tell you exactly how "
            "long it will take before I start.\n\n"
            "🔒 **Reminder:** You can click 'Logout & Wipe' at any time to purge your "
            "data from our server."
        )
        msg = await bot.send_message(
            sender_id,
            text,
            buttons=[
                [Button.inline("🚀 Step 3: Start Cleanup", b"run_cleanup")],
                [Button.inline("📜 Step 2: Set Whitelist", b"set_whitelist")],
                [Button.inline("🚪 Logout & Wipe Data", b"logout")]
            ]
        )
        last_messages[sender_id] = msg.id

    @bot.on(events.CallbackQuery(data=b"run_cleanup"))
    async def handle_run_cleanup(event):
        await event.answer("🔍 Analyzing Account...")
        sender_id = event.sender_id
        cleaner = user_clients.get(sender_id)
        if not cleaner or not await cleaner.client.is_user_authorized():
            await event.respond("⚠️ Session expired. Please login again.", buttons=[Button.inline("🔙 Menu", b"back_to_start")])
            return

        text = "🔍 **Step 1: Analyzing Account...**\n\nI am scanning your chats, detecting spam, and checking activity levels. This will only take a moment."
        msg = await event.edit(text, buttons=[[Button.inline("🔙 Cancel", b"back_to_start")]])
        last_messages[sender_id] = msg.id

        try:
            # Refresh whitelist first
            whitelist = set(user_whitelists.get(sender_id, []))
            await cleaner._prepare_whitelist(whitelist)

            # Fetch and Analyze
            dialogs = await cleaner._safe_iter_dialogs()
            user_dialogs[sender_id] = dialogs

            activity = await cleaner.analyze_activity(dialogs)

            # Count to-be-deleted items
            to_remove = []
            spam_bots = 0
            for d in dialogs:
                if not cleaner._is_whitelisted(d.entity):
                    to_remove.append(d)
                    if getattr(d.entity, 'bot', False):
                        if cleaner.calculate_spam_score(d.entity) > 50:
                            spam_bots += 1

            # Apply selected filters to counts
            filters = user_filters.get(sender_id, {"inactivity_days": 0, "spam_threshold": 0})

            filtered_remove = []
            for d in to_remove:
                if filters["inactivity_days"] > 0:
                    last_date = d.date
                    if last_date:
                        delta = (datetime.now(last_date.tzinfo) - last_date).days if last_date.tzinfo else (datetime.now() - last_date).days
                        if delta < filters["inactivity_days"]:
                            continue

                if filters["spam_threshold"] > 0 and getattr(d.entity, 'bot', False):
                    score = cleaner.calculate_spam_score(d.entity)
                    if score < filters["spam_threshold"]:
                        continue

                filtered_remove.append(d)

            total_whitelisted = len(dialogs) - len(filtered_remove)
            est_time = cleaner.estimate_duration(len(dialogs), total_whitelisted)

            preview_text = (
                "📊 **Step 2: Preview & Analysis Complete**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📂 **Total Chats:** {len(dialogs)}\n"
                f"💎 **Whitelisted:** {total_whitelisted}\n"
                f"🗑️  **Items to Remove:** {len(filtered_remove)}\n\n"
                "⚡ **Advanced Intelligence:**\n"
                f"• 🧟 **Inactive (30d+):** {activity['inactive_30d'] + activity['inactive_90d']}\n"
                f"• 🤖 **Suspected Spam Bots:** {spam_bots}\n"
                f"⏳ **Estimated Time:** {est_time}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "⚙️ **Cleanup Filters:**\n"
                f"• Inactivity: {'All' if filters['inactivity_days'] == 0 else f'>{filters[ 'inactivity_days']} days'}\n"
                f"• Spam Score: {'All' if filters['spam_threshold'] == 0 else f'>{filters['spam_threshold']}'}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )

            buttons = [
                [Button.inline("🚀 Start Cleanup Now", b"confirm_cleanup")],
                [
                    Button.inline("⏳ Inact: All", b"set_filter_inact_0"),
                    Button.inline("7d", b"set_filter_inact_7"),
                    Button.inline("30d", b"set_filter_inact_30")
                ],
                [
                    Button.inline("🤖 Spam: All", b"set_filter_spam_0"),
                    Button.inline("Med", b"set_filter_spam_50"),
                    Button.inline("High", b"set_filter_spam_80")
                ],
                [Button.inline("📦 Export List (JSON)", b"export_cleanup")],
                [Button.inline("🔙 Back / Change Whitelist", b"back_to_start")]
            ]

            user_states[sender_id] = 'PREVIEWING'
            msg = await event.edit(preview_text, buttons=buttons)
            last_messages[sender_id] = msg.id

        except Exception as e:
            await event.respond(f"❌ Analysis failed: {str(e)}", buttons=[[Button.inline("🔙 Back", b"back_to_start")]])

    @bot.on(events.CallbackQuery(data=b"export_cleanup"))
    async def handle_export(event):
        sender_id = event.sender_id
        cleaner = user_clients.get(sender_id)
        dialogs = user_dialogs.get(sender_id)

        if not cleaner or not dialogs:
            await event.answer("⚠️ Data missing, please restart analysis.")
            return

        await event.answer("📦 Generating export...")
        try:
            export_file = await cleaner.export_data(dialogs)
            await bot.send_file(sender_id, export_file, caption="📄 Here is your account backup (JSON).")
            # Remove local file after sending
            if os.path.exists(export_file):
                os.remove(export_file)
        except Exception as e:
            await event.respond(f"❌ Export failed: {str(e)}")

    @bot.on(events.CallbackQuery(data=re.compile(b"set_filter_.*")))
    async def handle_set_filter(event):
        sender_id = event.sender_id
        data = event.data.decode()

        if sender_id not in user_filters:
            user_filters[sender_id] = {"inactivity_days": 0, "spam_threshold": 0}

        if data == "set_filter_inact_0": user_filters[sender_id]["inactivity_days"] = 0
        elif data == "set_filter_inact_7": user_filters[sender_id]["inactivity_days"] = 7
        elif data == "set_filter_inact_30": user_filters[sender_id]["inactivity_days"] = 30
        elif data == "set_filter_spam_0": user_filters[sender_id]["spam_threshold"] = 0
        elif data == "set_filter_spam_50": user_filters[sender_id]["spam_threshold"] = 50
        elif data == "set_filter_spam_80": user_filters[sender_id]["spam_threshold"] = 80

        await event.answer("✅ Filter Updated")
        # Refresh the preview menu
        await handle_run_cleanup(event)

    @bot.on(events.CallbackQuery(data=b"confirm_cleanup"))
    async def handle_confirm_cleanup(event):
        sender_id = event.sender_id
        cleaner = user_clients.get(sender_id)
        if not cleaner: return

        user_states[sender_id] = 'CLEANING'
        text = "⚡ **Step 3: Intelligent Cleanup Initiated!**\n\nPlease watch the dashboard below for live updates."
        buttons = [[Button.inline("🔙 Stop / Menu", b"back_to_start")]]
        await event.edit(text, buttons=buttons)

        whitelist = set(user_whitelists.get(sender_id, []))
        filters = user_filters.get(sender_id, {})

        if sender_id in active_tasks:
            active_tasks[sender_id].cancel()

        task = asyncio.create_task(run_cleanup_task(sender_id, cleaner, whitelist, filters))
        active_tasks[sender_id] = task

    async def run_cleanup_task(sender_id, cleaner, whitelist, filters):
        try:
            # Dashboard message
            try:
                dashboard = await bot.send_message(sender_id, "⚙️ **Preparing Intelligent Cleanup...**")
            except:
                return # User blocked the bot

            log_buffer = []
            last_update = 0
            lock = asyncio.Lock()

            async def bot_progress_callback(msg):
                nonlocal last_update
                async with lock:
                    log_buffer.append(msg)
                    if len(log_buffer) > 10:
                        log_buffer.pop(0)

                now = asyncio.get_event_loop().time()
                if now - last_update > 1.5: # Respect Telegram edit limits (1.5s to be safe)
                    last_update = now
                    try:
                        logs = "\n".join(log_buffer)
                        await dashboard.edit(f"🛰️ **Cleanup Dashboard**\n━━━━━━━━━━━━━━━━━━━━\n{logs}")
                    except Exception:
                        pass

            cleaner.progress_callback = bot_progress_callback
            await cleaner.run_cleanup(whitelist, filters=filters)

            try:
                await bot.send_message(sender_id, "🏁 **Cleanup Mission Complete!**\n\nYour account is now clean.", buttons=[
                    [Button.inline("🔙 Return to Menu", b"back_to_start")]
                ])
            except: pass
        except Exception as e:
            try:
                await bot.send_message(sender_id, f"⚠️ **Cleanup Interrupted:**\n`{str(e)}`", buttons=[
                    [Button.inline("🔙 Back", b"back_to_start")]
                ])
            except: pass
        finally:
            user_states[sender_id] = 'READY'

    @bot.on(events.CallbackQuery(data=b"logout"))
    async def handle_logout(event):
        await event.answer("👋 Wiping session data...")
        sender_id = event.sender_id

        if sender_id in active_tasks:
            active_tasks[sender_id].cancel()
            try: del active_tasks[sender_id]
            except: pass

        cleaner = user_clients.pop(sender_id, None)
        if cleaner:
            try:
                # Log out from Telegram servers (invalidates the session string)
                if await cleaner.client.is_user_authorized():
                    await cleaner.client.log_out()
                await cleaner.client.disconnect()
            except Exception:
                try: await cleaner.client.disconnect()
                except: pass

        # Clear in-memory data
        if sender_id in user_states: del user_states[sender_id]
        if sender_id in user_whitelists: del user_whitelists[sender_id]
        if sender_id in user_dialogs: del user_dialogs[sender_id]
        if sender_id in user_filters: del user_filters[sender_id]

        # Thoroughly clean up all user-related files
        session_prefix = f"user_{sender_id}"
        files_to_remove = [
            f"sessions/{session_prefix}.session",
            f"sessions/{session_prefix}.session-journal",
            f"sessions/{session_prefix}_prefs.json",
            f"sessions/{session_prefix}_progress.json"
        ]
        for f in files_to_remove:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass

        user_states[sender_id] = 'IDLE'
        text = (
            "👋 **Logged out successfully.**\n\n"
            "🔒 **Privacy Guaranteed:** All your session files, preferences, and progress "
            "data have been permanently deleted from our server. We no longer have "
            "access to your account."
        )
        buttons = [[Button.inline("🔙 Start Over", b"back_to_start")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    await bot.run_until_disconnected()

if __name__ == "__main__":
    main()
