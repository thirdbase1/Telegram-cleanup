import asyncio
import os
import re
from telethon import TelegramClient, events, Button, errors
from .sdk import TelegramCleaner
from .config import load_config

# --- Bot State Management ---
# states: 'IDLE', 'WAITING_PHONE', 'WAITING_CODE', 'WAITING_2FA', 'READY', 'CLEANING'
user_states = {}
user_clients = {} # Store TelegramCleaner instances per user
user_whitelists = {}
active_tasks = {}

def main():
    """Entry point for the bot."""
    asyncio.run(start_bot())

async def start_bot():
    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return

    token = config.get('bot_token')
    if not token:
        print("❌ Error: BOT_TOKEN not found in .env file.")
        return

    print("🛰️ Connecting to Telegram...")
    bot = TelegramClient('bot_session', config['api_id'], config['api_hash'])

    try:
        await bot.start(bot_token=token)
        bot_me = await bot.get_me()
        bot_username = bot_me.username
        bot_id = bot_me.id
        print(f"🤖 Bot is up and running as @{bot_username} (ID: {bot_id})!")
    except errors.rpcerrorlist.ApiIdInvalidError:
        print("❌ FATAL ERROR: Your API_ID or API_HASH is invalid.")
        print("💡 Please check your credentials at https://my.telegram.org")
        return
    except Exception as e:
        print(f"❌ Login error: {e}")
        return

    @bot.on(events.NewMessage(pattern='/start'))
    async def handle_start(event):
        sender_id = event.sender_id
        user_states[sender_id] = 'IDLE'
        await send_main_menu(event)

    async def send_main_menu(event):
        sender_id = event.sender_id
        welcome_text = (
            "🚀 **The Ultimate Telegram Cleanup Bot**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "I will reset your account to a clean state by removing unwanted chats, "
            "blocking bots, and leaving channels/groups.\n\n"
            "💡 **Whitelist Examples (Keep these!):**\n"
            "• `James bot, @Michael, t.me/MyChannel` (Names/Links)\n"
            "• `1685547486` (Numeric IDs)\n\n"
            "🛡️ **Safe & Secure:** We auto-keep your 'Saved Messages' and this bot.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

        # Check if user is already logged in
        cleaner = user_clients.get(sender_id)
        is_logged_in = False
        if cleaner:
            try:
                is_logged_in = await cleaner.client.is_user_authorized()
            except:
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
                await event.edit(welcome_text, buttons=buttons)
            except Exception:
                await event.respond(welcome_text, buttons=buttons)
        else:
            await event.respond(welcome_text, buttons=buttons)

    @bot.on(events.CallbackQuery(data=b"already_logged_in"))
    async def handle_already_logged_in(event):
        await event.answer("✅ You are already logged in!", alert=True)

    @bot.on(events.CallbackQuery(data=b"login"))
    async def handle_login_click(event):
        await event.answer()
        sender_id = event.sender_id
        user_states[sender_id] = 'WAITING_PHONE'
        text = "📱 Please enter your phone number in international format (e.g., `+1234567890`):"
        buttons = [[Button.inline("🔙 Back", b"back_to_start")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    @bot.on(events.CallbackQuery(data=b"set_whitelist"))
    async def handle_whitelist_click(event):
        await event.answer()
        sender_id = event.sender_id
        current = ", ".join(user_whitelists.get(sender_id, [])) or "None"
        text = (
            f"📝 **Current Whitelist:** {current}\n\n"
            "Send me a comma-separated list of usernames (@name), links (t.me/name), or IDs to keep."
        )
        buttons = [[Button.inline("🔙 Back", b"back_to_start")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)
        user_states[sender_id] = 'SETTING_WHITELIST'

    @bot.on(events.CallbackQuery(data=b"back_to_start"))
    async def handle_back(event):
        await event.answer()
        await send_main_menu(event)

    @bot.on(events.NewMessage())
    async def handle_all_messages(event):
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

            await event.respond("⏳ Sending login code...")
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
                    "📩 **Code sent!**\n\n"
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
                    await event.respond("❌ Invalid format. Please send like: `code: 1 2 3 4 5`")
                    return

                await cleaner.client.sign_in(cleaner.phone, clean_code, phone_code_hash=cleaner.phone_code_hash)
                await finish_login(event, sender_id)
            except errors.SessionPasswordNeededError:
                user_states[sender_id] = 'WAITING_2FA'
                await event.respond("🔑 2FA detected. Please enter your Cloud Password:")
            except Exception as e:
                await event.respond(f"❌ Error: {str(e)}")

        elif state == 'WAITING_2FA':
            cleaner = user_clients.get(sender_id)
            try:
                await cleaner.client.sign_in(password=text)
                await finish_login(event, sender_id)
            except Exception as e:
                await event.respond(f"❌ Incorrect password: {str(e)}")

        elif state == 'SETTING_WHITELIST':
            items = [i.strip() for i in text.split(',') if i.strip()]
            user_whitelists[sender_id] = items
            user_states[sender_id] = 'IDLE'
            await event.respond(f"✅ Whitelist updated with {len(items)} items!", buttons=[
                [Button.inline("🔙 Back to Menu", b"back_to_start")]
            ])

    async def finish_login(event, sender_id):
        user_states[sender_id] = 'READY'
        await event.respond(
            "✅ **Successfully logged in!**\n\nReady to clean up your account?",
            buttons=[
                [Button.inline("🚀 Start Cleanup", b"run_cleanup")],
                [Button.inline("🚪 Logout", b"logout")]
            ]
        )

    @bot.on(events.CallbackQuery(data=b"run_cleanup"))
    async def handle_run_cleanup(event):
        await event.answer("🚀 Cleanup initializing...")
        sender_id = event.sender_id
        if user_states.get(sender_id) != 'READY' and user_states.get(sender_id) != 'IDLE':
             # Try to recover if they are actually logged in
             cleaner = user_clients.get(sender_id)
             if not (cleaner and await cleaner.client.is_user_authorized()):
                await event.respond("⚠️ You must be logged in first!", buttons=[Button.inline("🔙 Menu", b"back_to_start")])
                return

        cleaner = user_clients.get(sender_id)
        user_states[sender_id] = 'CLEANING'
        text = "⚡ **Intelligent Cleanup Initiated!**\n\nI am now analyzing your account. Please watch the dashboard below for live updates."
        buttons = [[Button.inline("🔙 Stop / Menu", b"back_to_start")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

        whitelist = set(user_whitelists.get(sender_id, []))

        # Cancel old task if exists
        if sender_id in active_tasks:
            active_tasks[sender_id].cancel()

        task = asyncio.create_task(run_cleanup_task(sender_id, cleaner, whitelist))
        active_tasks[sender_id] = task

    async def run_cleanup_task(sender_id, cleaner, whitelist):
        try:
            # Dashboard message
            dashboard = await bot.send_message(sender_id, "⚙️ **Preparing Intelligent Cleanup...**")

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
            await cleaner.run_cleanup(whitelist)

            await bot.send_message(sender_id, "🏁 **Cleanup Mission Complete!**\n\nYour account is now clean.", buttons=[
                [Button.inline("🔙 Return to Menu", b"back_to_start")]
            ])
        except Exception as e:
            await bot.send_message(sender_id, f"⚠️ **Cleanup Interrupted:**\n`{str(e)}`", buttons=[
                [Button.inline("🔙 Back", b"back_to_start")]
            ])
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
                # Disconnect instead of log_out to keep the session file if they want to re-login,
                # BUT the user said "Wipe Data", so we log_out.
                await cleaner.client.log_out()
                await cleaner.client.disconnect()
            except Exception:
                try: await cleaner.client.disconnect()
                except: pass

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
        text = "👋 **Logged out successfully.**\n\nAll your session files and data have been permanently deleted from our server."
        buttons = [[Button.inline("🔙 Start Over", b"back_to_start")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await event.respond(text, buttons=buttons)

    await bot.run_until_disconnected()

if __name__ == "__main__":
    main()
