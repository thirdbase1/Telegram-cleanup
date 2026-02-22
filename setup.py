from setuptools import setup, find_packages

setup(
    name="telegram-cleanup",
    version="1.2.0",
    packages=["telegram_cleanup"],
    include_package_data=True,
    install_requires=[
        "python-dotenv",
        "telethon",
    ],
    entry_points={
        "console_scripts": [
            "telegram-cleanup = telegram_cleanup.telegram_cleanup:main_cli",
            "telegram-cleanup-bot = telegram_cleanup.bot_interface:main",
        ],
    },
)
