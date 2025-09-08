"""Default hard-coded settings for NewsBot.

These values act as fallbacks when environment variables are missing.
Replace the placeholders with your actual credentials if you prefer
configuration in code.

!!! WARNING !!!
Storing credentials in source code is insecure and not recommended for
production deployments.
"""

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHANNEL_ID = "@your_main_channel"
ENABLE_MODERATION = True
REVIEW_CHAT_ID = "@your_review_channel"
MODERATOR_IDS = {123456789}
FALLBACK_IMAGE_URL = "https://example.com/placeholder.png"
