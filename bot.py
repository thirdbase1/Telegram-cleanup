#!/usr/bin/env python3
import sys
import os

# Add the current directory to sys.path to ensure telegram_cleanup is findable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from telegram_cleanup.bot_interface import main
except ImportError as e:
    print(f"❌ Error: Could not import telegram_cleanup. {e}")
    print("💡 Try running: pip install -r requirements.txt")
    sys.exit(1)

if __name__ == "__main__":
    main()
