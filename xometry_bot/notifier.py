import requests
import config
import os
import json

NOTIFIED_FILE = "data/notified_jobs.txt"
MESSAGE_INDEX_FILE = "data/telegram_messages.json"
MESSAGE_STATE_FILE = "data/telegram_message_states.json"

def is_already_notified(job_id):
    """Checks if the job ID is in the data/notified_jobs.txt file."""
    filepath = NOTIFIED_FILE
    if not os.path.exists(filepath):
        return False
    with open(filepath, "r") as f:
        notified = f.read().splitlines()
        return job_id in notified

def mark_as_notified(job_id):
    """Adds the job ID to data/notified_jobs.txt."""
    os.makedirs("data", exist_ok=True)
    with open(NOTIFIED_FILE, "a") as f:
        f.write(f"{job_id}\n")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _store_message_records(job_id, records):
    if not job_id or not records:
        return
    data = _load_json(MESSAGE_INDEX_FILE, {})
    data[str(job_id)] = records
    _save_json(MESSAGE_INDEX_FILE, data)


def _message_records(job_id):
    data = _load_json(MESSAGE_INDEX_FILE, {})
    return data.get(str(job_id)) or []


def _set_message_state(job_id, state_key):
    if not job_id or not state_key:
        return
    data = _load_json(MESSAGE_STATE_FILE, {})
    data[str(job_id)] = state_key
    _save_json(MESSAGE_STATE_FILE, data)


def _message_state(job_id):
    data = _load_json(MESSAGE_STATE_FILE, {})
    return data.get(str(job_id))


def send_telegram(message: str, job_id=None, reply_markup=None, state_key=None):
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
            _set_message_state(job_id, state_key)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Send to all configured chat IDs
    success_any = False
    message_records = []
    for chat_id in config.TELEGRAM_CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
    
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                success_any = True
                data = response.json()
                result = data.get("result") or {}
                if result.get("message_id"):
                    message_records.append({
                        "chat_id": str(chat_id),
                        "message_id": result["message_id"],
                    })
            else:
                print(f"Failed to send Telegram message to {chat_id}: {response.text}")
        except Exception as e:
            print(f"Error sending Telegram message to {chat_id}: {e}")

    if success_any and job_id:
        mark_as_notified(job_id)
        _store_message_records(job_id, message_records)
        _set_message_state(job_id, state_key)


def edit_telegram_if_changed(job_id, message: str, reply_markup=None, state_key=None):
    if not job_id or not state_key:
        return False
    if _message_state(job_id) == state_key:
        return False

    records = _message_records(job_id)
    if not records:
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
    success_any = False
    for record in records:
        payload = {
            "chat_id": record["chat_id"],
            "message_id": record["message_id"],
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                success_any = True
            else:
                print(f"Failed to edit Telegram message for {record['chat_id']}: {response.text}")
        except Exception as e:
            print(f"Error editing Telegram message for {record['chat_id']}: {e}")

    if success_any:
        _set_message_state(job_id, state_key)
    return success_any
