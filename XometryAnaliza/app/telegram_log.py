import requests

from . import settings


def send_log(message: str) -> None:
    if not settings.TELEGRAM_ENABLED or not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    chat_ids = [item.strip() for item in settings.TELEGRAM_CHAT_ID.split(",") if item.strip()]
    for chat_id in chat_ids:
        try:
            requests.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=10,
            )
        except Exception:
            pass
