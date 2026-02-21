# Installation and Setup Guide for Telegram Cleanup

This guide provides detailed, step-by-step instructions to get the Telegram Cleanup script up and running on your system, with specific notes for Termux users.

## Step 1: Prerequisites

Before you begin, ensure you have the following installed:

- **Python (3.6 or newer)**: The script is written in Python.
- **Git**: Required for cloning the repository.

### On Termux:

If you are using Termux on Android, you can install these with the following command:

```bash
pkg update && pkg upgrade
pkg install python git
```

### On Desktop (Linux/macOS/Windows):

- Download and install Python from the [official website](https://www.python.org/downloads/).
- Download and install Git from the [official website](https://git-scm.com/downloads/).

---

## Step 2: Get Your Telegram API Credentials

The script needs your personal Telegram API credentials to log in to your account.

1.  **Log in to my.telegram.org**: Open a web browser and go to [my.telegram.org](https://my.telegram.org). Enter your phone number and the confirmation code you receive in Telegram.
2.  **Go to API Development Tools**: After logging in, click on the "API development tools" link.
3.  **Create a New Application**:
    -   **App title**: Give your app a name, like `Telegram-Cleanup-Bot`.
    -   **Short name**: Provide a shorter name, like `cleanup_bot`.
    -   **URL**: You can leave this blank.
    -   **Platform**: Select "Other".
    -   **Description**: Optional.
4.  **Save Your Credentials**: After creating the application, you will see your `api_id` and `api_hash`. **Copy these down and keep them safe.** You will also need your `phone` number in international format (e.g., `+15551234567`).

---

## Step 3: Clone and Set Up the Repository

Now, you'll download the script and configure it with your credentials.

1.  **Clone the Repository**: Open your terminal or command prompt and run:
    ```bash
    git clone https://github.com/thirdbase1/telegram-cleanup.git
    cd telegram-cleanup
    ```

2.  **Create the Environment File**: The script uses a `.env` file to store your credentials securely. Copy the example file to create your own:
    ```bash
    cp .ENV.example .env
    ```

3.  **Edit the `.env` File**: Open the newly created `.env` file with a text editor (like `nano` in Termux or any editor on desktop):
    ```bash
    nano .env
    ```
    Paste your credentials into the file, replacing the placeholder text:
    ```ini
    API_ID=1234567
    API_HASH=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
    PHONE=+15551234567
    ```
    Save the file and exit the editor (in `nano`, press `Ctrl+X`, then `Y`, then `Enter`).

---

## Step 4: Install the Script

With the setup complete, you can now install the script as a command-line tool.

### On Termux:

```bash
pip install .
```
This command reads the `setup.py` file and installs the script and its dependencies (`telethon` and `python-dotenv`).

### On Desktop:

The command is the same. It's recommended to do this within a virtual environment.

```bash
# Optional: Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install the script
pip install .
```

---

## Step 5: Run the Script

Once installed, you can run the cleanup process with a single command:

```bash
telegram-cleanup
```

The first time you run it, you will be prompted for:
1.  **A login code**: Sent to your Telegram account.
2.  **Your 2FA password**: If you have Two-Factor Authentication enabled.
3.  **Items to keep**: You can enter a comma-separated list of usernames (`@name`), links (`t.me/name`), or exact names of channels/groups that you do not want to delete. If you want to delete everything else, just press `Enter`.

The script will then begin the cleanup process. It will keep you updated on its progress in the terminal.

---

## Troubleshooting

-   **`command not found: telegram-cleanup`**: This can happen on Termux if the `pip` installation directory is not in your `PATH`. You can fix this by adding it to your shell configuration file (`.bashrc` or `.zshrc`).
    ```bash
    echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.bashrc
    source ~/.bashrc
    ```
-   **Authentication Errors**: Double-check that your `API_ID`, `API_HASH`, and `PHONE` in the `.env` file are correct. If you're still having issues, you can delete the `telegram_cleanup.session` file and try again.

You are now all set up!
