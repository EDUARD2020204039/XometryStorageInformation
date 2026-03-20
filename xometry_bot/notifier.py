import requests
import config
import os

def is_already_notified(job_id):
    """Checks if the job ID is in the data/notified_jobs.txt file."""
    filepath = "data/notified_jobs.txt"
    if not os.path.exists(filepath):
        return False
    with open(filepath, "r") as f:
        notified = f.read().splitlines()
        return job_id in notified

def mark_as_notified(job_id):
    """Adds the job ID to data/notified_jobs.txt."""
    os.makedirs("data", exist_ok=True)
    with open("data/notified_jobs.txt", "a") as f:
        f.write(f"{job_id}\n")

def send_telegram(message: str, job_id=None, reply_markup=None):
    """
    Sends a message to the configured Telegram chat.
    If job_id is provided, it checks if it was already notified.
    """
    if job_id and is_already_notified(job_id):
        return

    if not config.TELEGRAM_BOT_TOKEN or "YOUR_BOT" in config.TELEGRAM_BOT_TOKEN:
        print("[MOCK TELEGRAM] " + message)
        if job_id:
            mark_as_notified(job_id)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Send to all configured chat IDs
    success_any = False
    for chat_id in config.TELEGRAM_CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
    
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                success_any = True
            else:
                print(f"Failed to send Telegram message to {chat_id}: {response.text}")
        except Exception as e:
            print(f"Error sending Telegram message to {chat_id}: {e}")

    if success_any and job_id:
        mark_as_notified(job_id)
