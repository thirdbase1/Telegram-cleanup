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

def main():
    """Entry point for the bot."""
    asyncio.run(start_bot())

async def start_bot():
    config = load_config()
    token = config.get('bot_token')
    if not token:
        print("❌ Error: BOT_TOKEN not found in .env file.")
        return

    bot = TelegramClient('bot_session', config['api_id'], config['api_hash'])
    await bot.start(bot_token=token)
    print("🤖 Bot is up and running!")

    @bot.on(events.NewMessage(pattern='/start'))
    async def handle_start(event):
        sender_id = event.sender_id
        user_states[sender_id] = 'IDLE'
        welcome_text = (
            "👋 **Welcome to Telegram Cleanup Bot!**\n\n"
            "I can help you reset your account by removing unwanted channels, groups, and bots while keeping what's important.\n\n"
            "💡 **How it works:**\n"
            "1. Login to your account via this bot.\n"
            "2. Set your whitelist (items to keep).\n"
            "3. Start the cleanup.\n\n"
            "🔒 **Security:** Your session is processed in memory and terminated after cleanup."
        )
        await event.respond(welcome_text, buttons=[
            [Button.inline("🔑 Login to Telegram", b"login")],
            [Button.inline("📜 Set Whitelist", b"set_whitelist")]
        ])

    @bot.on(events.CallbackQuery(data=b"login"))
    async def handle_login_click(event):
        sender_id = event.sender_id
        user_states[sender_id] = 'WAITING_PHONE'
        await event.edit("📱 Please enter your phone number in international format (e.g., `+1234567890`):")

    @bot.on(events.CallbackQuery(data=b"set_whitelist"))
    async def handle_whitelist_click(event):
        sender_id = event.sender_id
        current = ", ".join(user_whitelists.get(sender_id, [])) or "None"
        await event.edit(
            f"📝 **Current Whitelist:** {current}\n\n"
            "Send me a comma-separated list of usernames (@name), links (t.me/name), or IDs to keep.",
            buttons=[Button.inline("🔙 Back", b"back_to_start")]
        )
        user_states[sender_id] = 'SETTING_WHITELIST'

    @bot.on(events.CallbackQuery(data=b"back_to_start"))
    async def handle_back(event):
        await handle_start(event)

    @bot.on(events.NewMessage())
    async def handle_all_messages(event):
        sender_id = event.sender_id
        state = user_states.get(sender_id, 'IDLE')
        text = event.text.strip()

        if text.startswith('/'): return # Ignore other commands

        if state == 'WAITING_PHONE':
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
            user_clients[sender_id] = cleaner

            try:
                await cleaner.client.connect()
                send_code_result = await cleaner.client.send_code_request(text)
                cleaner.phone = text
                cleaner.phone_code_hash = send_code_result.phone_code_hash
                user_states[sender_id] = 'WAITING_CODE'
                await event.respond("📩 Code sent! Please enter the code you received from Telegram:")
            except Exception as e:
                await event.respond(f"❌ Error: {str(e)}\nTry /start again.")
                user_states[sender_id] = 'IDLE'

        elif state == 'WAITING_CODE':
            cleaner = user_clients.get(sender_id)
            try:
                await cleaner.client.sign_in(cleaner.phone, text, phone_code_hash=cleaner.phone_code_hash)
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
        sender_id = event.sender_id
        if user_states.get(sender_id) != 'READY':
            await event.answer("⚠️ You must be logged in first!")
            return

        cleaner = user_clients.get(sender_id)
        user_states[sender_id] = 'CLEANING'
        await event.edit("⚡ **Cleanup in progress...**\nCheck messages below for live updates.")

        whitelist = set(user_whitelists.get(sender_id, []))

        try:
            # We run this in the background so it doesn't block the bot's event loop
            asyncio.create_task(run_cleanup_task(sender_id, cleaner, whitelist))
        except Exception as e:
            await event.respond(f"❌ Cleanup failed: {str(e)}")

    async def run_cleanup_task(sender_id, cleaner, whitelist):
        try:
            await cleaner.run_cleanup(whitelist)
            await bot.send_message(sender_id, "🏁 **Cleanup Finished!**", buttons=[
                [Button.inline("🔙 Menu", b"back_to_start")]
            ])
        except Exception as e:
            await bot.send_message(sender_id, f"⚠️ Cleanup interrupted: {str(e)}")
        finally:
            user_states[sender_id] = 'READY'

    @bot.on(events.CallbackQuery(data=b"logout"))
    async def handle_logout(event):
        sender_id = event.sender_id
        cleaner = user_clients.pop(sender_id, None)
        if cleaner:
            await cleaner.client.log_out()
            await cleaner.disconnect()
        user_states[sender_id] = 'IDLE'
        await event.edit("👋 Logged out successfully.", buttons=[Button.inline("🔙 Menu", b"back_to_start")])

    await bot.run_until_disconnected()

if __name__ == "__main__":
    main()
