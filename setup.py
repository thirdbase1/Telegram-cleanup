from setuptools import setup, find_packages

setup(
    name="telegram-cleanup",
    version="1.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "python-dotenv",
        "telethon",
    ],
    entry_points={
        "console_scripts": [
            "telegram-cleanup = telegram_cleanup.telegram_cleanup:main_cli",
        ],
    },
)
