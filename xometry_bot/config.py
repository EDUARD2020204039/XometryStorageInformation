import os
from dotenv import load_dotenv

# App Version
BOT_VERSION = "1.53"

load_dotenv(override=True)

# Debug
tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
print(f"DEBUG: Loaded Token: {tok[:10]}...{tok[-5:] if len(tok)>5 else ''} from {os.getcwd()}")


# Xometry Credentials
XOMETRY_EMAIL = os.getenv("XOMETRY_EMAIL", "ofertare@helpan.ro")
XOMETRY_PASSWORD = os.getenv("XOMETRY_PASSWORD", "Helpan1")
XOMETRY_LOGIN_URL = "https://partner.xometry.eu/profile/sign_in?locale=en"

# Telegram Notification Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")
TELEGRAM_CHAT_IDS = [x.strip() for x in TELEGRAM_CHAT_ID.split(",") if x.strip()]

# Filter Configuration
INTERESTING_MATERIAL_KEYWORDS = ["sheet", "tablă", "tabla"]
MIN_PRICE_CURRENCY = "EUR" 
MIN_PRICE_VALUE = 250.0
CHECK_INTERVAL = 120  # Check every 2 minutes

# Browser Config
HEADLESS = True  # Set to True for production/background run
BROWSER_USER_AGENT = os.getenv(
    "BROWSER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
PLAYWRIGHT_BROWSER_CHANNEL = os.getenv("PLAYWRIGHT_BROWSER_CHANNEL", "chromium")
PLAYWRIGHT_LAUNCH_RETRIES = int(os.getenv("PLAYWRIGHT_LAUNCH_RETRIES", "2"))
PLAYWRIGHT_LAUNCH_RETRY_DELAY = float(os.getenv("PLAYWRIGHT_LAUNCH_RETRY_DELAY", "3"))

# Backend (data sink)
BACKEND_URL = os.getenv("BACKEND_URL", "http://86.123.232.23:10000")
BACKEND_ENABLED = os.getenv("BACKEND_ENABLED", "true").lower() in ("1", "true", "yes")
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY", "")
BACKEND_RESEND_EXISTING = os.getenv("BACKEND_RESEND_EXISTING", "false").lower() in ("1", "true", "yes")
BACKEND_MAX_OFFERS_PER_RUN = int(os.getenv("BACKEND_MAX_OFFERS_PER_RUN", "10"))

# Orders deep sync
ORDERS_SYNC_ENABLED = os.getenv("ORDERS_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")
ORDERS_SYNC_INTERVAL = int(os.getenv("ORDERS_SYNC_INTERVAL", "600"))  # 10 minutes
ORDERS_SYNC_MAX_ORDERS = int(os.getenv("ORDERS_SYNC_MAX_ORDERS", "0"))  # 0 = no cap
ORDERS_SCROLL_ROUNDS = int(os.getenv("ORDERS_SCROLL_ROUNDS", "200"))
ORDERS_URL = os.getenv("ORDERS_URL", "https://partner.xometry.eu/orders?locale=en")
ORDERS_PAGINATION_MAX_PAGES = int(os.getenv("ORDERS_PAGINATION_MAX_PAGES", "0"))  # 0 = auto
ORDERS_STOP_AFTER_EMPTY_PAGES = int(os.getenv("ORDERS_STOP_AFTER_EMPTY_PAGES", "3"))
ORDERS_PROCESS_ONLY_NEW = os.getenv("ORDERS_PROCESS_ONLY_NEW", "true").lower() in ("1", "true", "yes")
ORDERS_SYNC_LOCK_MAX_AGE = int(os.getenv("ORDERS_SYNC_LOCK_MAX_AGE", "21600"))  # 6 hours
BACKEND_ORDERS_BATCH_SIZE = int(os.getenv("BACKEND_ORDERS_BATCH_SIZE", "200"))
BACKEND_ORDERS_TIMEOUT = int(os.getenv("BACKEND_ORDERS_TIMEOUT", "180"))
BACKEND_ORDERS_RETRY = int(os.getenv("BACKEND_ORDERS_RETRY", "2"))
