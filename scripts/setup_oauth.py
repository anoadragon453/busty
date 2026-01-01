#!/usr/bin/env env python3
"""OAuth 2.0 Setup Script for Busty Bot.

This script performs the one-time OAuth flow to authenticate the bot account
and generate a token file for use with the Google Forms and Drive APIs.

Prerequisites:
1. Create OAuth 2.0 credentials in Google Cloud Console
2. Download credentials.json to the auth/ directory
3. Run this script and follow the prompts

Usage:
    python scripts/setup_oauth.py
    # Or with uv:
    uv run python scripts/setup_oauth.py
"""

import logging
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Scopes required for Forms and Drive APIs
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.body",
]

# File paths
PROJECT_ROOT = Path(__file__).parent.parent
AUTH_DIR = PROJECT_ROOT / "auth"
CREDENTIALS_FILE = AUTH_DIR / "oauth_credentials.json"
TOKEN_FILE = AUTH_DIR / "oauth_token.json"


def ensure_auth_dir():
    """Create auth directory if it doesn't exist."""
    AUTH_DIR.mkdir(exist_ok=True)
    logger.info(f"Using auth directory: {AUTH_DIR}")


def check_credentials_file():
    """Check if OAuth credentials file exists."""
    if not CREDENTIALS_FILE.exists():
        logger.error(f"OAuth credentials file not found: {CREDENTIALS_FILE}")
        logger.error("")
        logger.error("Please follow these steps:")
        logger.error("1. Go to Google Cloud Console: https://console.cloud.google.com")
        logger.error("2. Select your project (or create one)")
        logger.error("3. Enable Google Forms API and Google Drive API")
        logger.error("4. Go to APIs & Services > Credentials")
        logger.error('5. Click "Create Credentials" > "OAuth 2.0 Client ID"')
        logger.error('6. Choose "Desktop app" as the application type')
        logger.error("7. Download the credentials JSON file")
        logger.error(f"8. Save it as: {CREDENTIALS_FILE}")
        logger.error("")
        return False
    return True


def run_oauth_flow():
    """Run the OAuth 2.0 flow to get user credentials."""
    logger.info("Starting OAuth 2.0 authentication flow...")
    logger.info("")
    logger.info("A browser window will open for you to:")
    logger.info("1. Sign in to the Google account you want to use for the bot")
    logger.info("2. Grant permissions for Forms and Drive access")
    logger.info("")
    logger.info("IMPORTANT: Sign in with your bot account, not your personal account!")
    logger.info("")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

        # Save the credentials
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

        logger.info("")
        logger.info(f"✓ Success! Token saved to: {TOKEN_FILE}")
        logger.info("")
        logger.info("Next steps:")
        logger.info(
            '1. Set environment variable: BUSTY_GOOGLE_AUTH_TYPE="oauth" (or leave unset, oauth is default)'
        )
        logger.info(
            f"2. Ensure BUSTY_GOOGLE_OAUTH_TOKEN points to: {TOKEN_FILE} (default location)"
        )
        logger.info("3. Run the bot normally - it will use OAuth authentication")
        logger.info("")

        return True

    except Exception as e:
        logger.error(f"✗ OAuth flow failed: {e}")
        return False


def verify_token():
    """Verify that the token file exists and is valid."""
    if not TOKEN_FILE.exists():
        return False

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        # Check if token is valid
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                logger.info("Token expired, refreshing...")
                creds.refresh(Request())

                # Save refreshed token
                with open(TOKEN_FILE, "w") as token:
                    token.write(creds.to_json())

                logger.info("✓ Token refreshed successfully")
            else:
                logger.error("✗ Token is invalid and cannot be refreshed")
                return False

        logger.info("✓ Token is valid")
        return True

    except Exception as e:
        logger.error(f"✗ Error verifying token: {e}")
        return False


def main():
    """Main entry point."""
    logger.info("=== Busty Bot OAuth 2.0 Setup ===")
    logger.info("")

    ensure_auth_dir()

    # Check for existing token
    if TOKEN_FILE.exists():
        logger.info(f"Found existing token file: {TOKEN_FILE}")
        logger.info("Verifying token...")

        if verify_token():
            logger.info("")
            logger.info("Token is already set up and working!")
            logger.info(
                "If you want to re-authenticate, delete the token file and run again."
            )
            return 0
        else:
            logger.warning("Existing token is invalid, will create new one...")
            logger.info("")

    # Check for credentials file
    if not check_credentials_file():
        return 1

    # Run OAuth flow
    if not run_oauth_flow():
        return 1

    # Verify the new token
    logger.info("Verifying newly created token...")
    if verify_token():
        logger.info("✓ Setup complete!")
        return 0
    else:
        logger.error("✗ Setup failed - token verification failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
