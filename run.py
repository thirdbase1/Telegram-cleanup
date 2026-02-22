#!/usr/bin/env python3
import sys
import os

# Add the current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def print_banner():
    print("🚀 **The Ultimate Telegram Cleanup Bot**")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

def main():
    print_banner()
    print("Choose your mode:")
    print("1. Terminal Mode (Standard Cleanup)")
    print("2. Telegram Bot Mode (Public Interface)")
    print("Q. Quit")

    choice = input("\n👉 Enter your choice (1/2/Q): ").strip().lower()

    if choice == '1':
        print("\n🚀 Starting Terminal Cleanup...")
        from telegram_cleanup.telegram_cleanup import main_cli
        main_cli()
    elif choice == '2':
        print("\n🤖 Starting Telegram Bot Mode...")
        from telegram_cleanup.bot_interface import main as main_bot
        main_bot()
    elif choice == 'q':
        print("👋 Goodbye!")
        sys.exit(0)
    else:
        print("❌ Invalid choice. Please run again.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Exiting safely...")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ A fatal error occurred: {e}")
        sys.exit(1)
