from setuptools import setup, find_packages

setup(
    name="telegram-cleanup",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "python-dotenv",
        "telethon",
    ],
    entry_points={
        "console_scripts": [
            "telegram-cleanup = src.telegram_cleanup:main_cli",
        ],
    },
)
