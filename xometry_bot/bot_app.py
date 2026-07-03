import telebot
from telebot import types
import json
import os
import config
import threading
from datetime import datetime
import time
import socket
import requests
import requests.packages.urllib3.util.connection as urllib3_cn
from playwright.sync_api import sync_playwright
import auth
import scraper
import backend
import browser_utils
import agent_client

def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family


# Initialize bot
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

DATA_FILE = "data/all_jobs.json"
TELEGRAM_MSG_LIMIT = 3800
FORCE_SCRAPE_FLAG = "data/force_scrape.flag"
TELEGRAM_POLL_LOCK = "data/telegram_polling.lock"
TELEGRAM_POLL_LOCK_TTL = 90
TELEGRAM_POLL_HEARTBEAT = 15
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"

JOB_OFFERS_REFUSE_MUTATION = """mutation jobOffersRefuse($id: ID!, $responseRefusalReason: String) {
  jobOffersRefuse(input: {id: $id, responseRefusalReason: $responseRefusalReason}) {
    jobOffer {
      id
      responseState
      decisionState
    }
  }
}
"""

def _get_auth_token():
    try:
        with sync_playwright() as p:
            browser = browser_utils.launch_browser(p.chromium)
            context = browser_utils.new_context(browser)
            page = context.new_page()
            auth.login(page)
            page.wait_for_selector("text=Job Board", timeout=20000)
            token = page.evaluate("() => localStorage.getItem('authToken')")
            browser.close()
            return token
    except Exception as e:
        print(f"Failed to get auth token: {e}")
        return None

def _graphql_request(token, operation_name, query, variables):
    url = f"https://api.xometry.eu/partners/graphql?{operation_name}"
    payload = {
        "operationName": operation_name,
        "query": query,
        "variables": variables,
    }
    try:
        resp = requests.post(
            url,
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "authorization": f"Bearer {token}",
            },
            data=json.dumps(payload),
            timeout=30,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        data = resp.json()
        if data.get("errors"):
            return None, f"GraphQL errors: {data.get('errors')}"
        return data.get("data"), None
    except Exception as e:
        return None, str(e)

def decline_job_offer(offer_id, reason="Declined via Telegram"):
    token = _get_auth_token()
    if not token:
        return False, "Missing auth token"
    data, err = _graphql_request(
        token,
        "jobOffersRefuse",
        JOB_OFFERS_REFUSE_MUTATION,
        {"id": str(offer_id), "responseRefusalReason": reason},
    )
    if err:
        return False, err
    if not data or not data.get("jobOffersRefuse"):
        return False, "No response from API"
    return True, None

def load_jobs():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r") as f:
            raw_jobs = json.load(f)
            # Deduplicate by ID
            unique_jobs = {}
            for j in raw_jobs:
                jid = j.get('id')
                if jid and jid != "Unknown":
                    # Keep the one with more info or just the first one
                    if jid not in unique_jobs:
                        unique_jobs[jid] = j
            return list(unique_jobs.values()), os.path.getmtime(DATA_FILE)
    except Exception as e:
        print(f"Error loading jobs: {e}")
        return [], 0

def find_job_by_offer_id(offer_id):
    jobs, _ = load_jobs()
    for j in jobs:
        if str(j.get("offer_id")) == str(offer_id):
            return j
    return None


def get_status_report():
    jobs, timestamp = load_jobs()
    if not jobs:
        return "❌ Nu am găsit date despre joburi. Te rog să aștepți ca scraper-ul să ruleze prima dată.", []
    
    # Format time
    last_update = datetime.fromtimestamp(timestamp).strftime('%d.%m %H:%M') if timestamp > 0 else "N/A"


    total_jobs = len(jobs)
    
    # Separation: RFQs vs Standard Jobs
    # RFQs usually have ID starting with 'RFQ-'
    rfqs = [j for j in jobs if "RFQ-" in j['id']]
    standard_jobs = [j for j in jobs if "RFQ-" not in j['id']]
    
    # 1. Sheet RFQs
    sheet_rfqs = [j for j in rfqs if any(kw in (j.get('material', '') + j.get('process', '')).lower() for kw in config.INTERESTING_MATERIAL_KEYWORDS)]
    
    # 2. Stats
    # Count sheet jobs (all types)
    all_sheet_jobs = [j for j in jobs if any(kw in (j.get('material', '') + j.get('process', '')).lower() for kw in config.INTERESTING_MATERIAL_KEYWORDS)]
    count_sheet = len(all_sheet_jobs)
    value_sheet = sum(j.get('price', 0.0) for j in all_sheet_jobs)

    # 3. Top 10 (by value)
    sorted_jobs = sorted(jobs, key=lambda x: x.get('price', 0.0), reverse=True)
    top_10 = sorted_jobs[:10]

    report = f"📊 *STATUS PLATFORMĂ v{config.BOT_VERSION}*\n━━━━━━━━━━━━━━━\n\n"
    
    # SECTION 1: Sheet RFQs
    if sheet_rfqs:
        report += f"📑 *SHEET RFQs ({len(sheet_rfqs)})*\n"
        for i, job in enumerate(sheet_rfqs, 1):
             price = job.get('price', 0.0)
             report += f"{i}. 🔗 [{job['id']}]({job.get('link', '')}) - *€{price:,.2f}* ({job['material']})\n"
        report += "\n"
    else:
        report += "📑 *SHEET RFQs:* 0 găsite.\n\n"

    # SECTION 2: General Stats
    report += (
        f"📈 *STATISTICI GENERALE*\n"
        f"📦 Total Joburi: `{total_jobs}`\n"
        f"📄 Total Sheet (Jobs+RFQs): `{count_sheet}`\n"
        f"💰 Valoare Totală Sheet: `€{value_sheet:,.2f}`\n\n"
    )

    # SECTION 3: Top 10 (list is sent separately with inline buttons)
    report += "🔝 *TOP 10 VALOROASE*\n"
    report += "_Vezi mai jos fiecare job cu buton de Decline._\n"

    report += f"\n🕒 _Ultima actualizare scraper: {last_update}_"

    return report, top_10

def get_top_rfqs_report():
    jobs, timestamp = load_jobs()
    if not jobs:
        return "❌ Nu sunt date."
        
    last_update = datetime.fromtimestamp(timestamp).strftime('%d.%m %H:%M') if timestamp > 0 else "N/A"
    
    # Filter RFQs
    rfqs = [j for j in jobs if "RFQ-" in j['id']]
    # Sort by quantity desc
    sorted_rfqs = sorted(rfqs, key=lambda x: x.get('quantity', 0), reverse=True)
    top_10 = sorted_rfqs[:10]
    
    report = f"📊 *TOP RFQ (Cantitate)*\n━━━━━━━━━━━━━━━\n\n"
    for i, job in enumerate(top_10, 1):
        price = job.get('price', 0.0)
        qty = job.get('quantity', 0)
        link = job.get('link', '')
        
        report += f"{i}. 🔗 [{job['id']}]({link}) - *{qty} buc* - €{price:,.2f}\n"

    report += f"\n🕒 _Ultima actualizare scraper: {last_update}_"
    return report

def get_sheet_report():
    jobs, timestamp = load_jobs()
    if not jobs:
        return "❌ Nu sunt date."
        
    last_update = datetime.fromtimestamp(timestamp).strftime('%d.%m %H:%M') if timestamp > 0 else "N/A"
    
    # Filter Sheet jobs (Material OR Process)
    sheet_jobs = [j for j in jobs if any(kw in (j.get('material', '') + j.get('process', '')).lower() for kw in config.INTERESTING_MATERIAL_KEYWORDS)]
    
    # Sort by price desc
    sorted_jobs = sorted(sheet_jobs, key=lambda x: x.get('price', 0.0), reverse=True)
    top_10 = sorted_jobs[:10]
    
    report = f"📊 *TOP SHEET JOBS (Price)*\n━━━━━━━━━━━━━━━\n\n"
    for i, job in enumerate(top_10, 1):
        price = job.get('price', 0.0)
        link = job.get('link', '')
        
        type_str = job['type']
        if type_str == "Urgent":
            type_str = "🔥 Urgent"
        
        report += f"{i}. 🔗 [{job['id']}]({link}) - *€{price:,.2f}* ({type_str})\n"

    report += f"\n📦 Total Sheet Jobs Găsite: {len(sheet_jobs)}"
    report += f"\n🕒 _Ultima actualizare scraper: {last_update}_"
    return report

def _split_text_for_telegram(text, max_len=TELEGRAM_MSG_LIMIT):
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= max_len:
            current += line
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > max_len:
            chunks.append(line[:max_len])
            line = line[max_len:]
        current = line
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]


def send_markdown_message(chat_id, text, reply_markup=None):
    chunks = _split_text_for_telegram(text)
    first = True
    for chunk in chunks:
        bot.send_message(
            chat_id,
            chunk,
            parse_mode="Markdown",
            reply_markup=reply_markup if first else None,
        )
        first = False

def _ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def _write_force_scrape_flag():
    _ensure_data_dir()
    payload = {
        "requested_at": time.time(),
        "requested_by": INSTANCE_ID,
    }
    with open(FORCE_SCRAPE_FLAG, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _read_poll_lock():
    if not os.path.exists(TELEGRAM_POLL_LOCK):
        return None
    try:
        with open(TELEGRAM_POLL_LOCK, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_poll_lock():
    _ensure_data_dir()
    payload = {
        "instance_id": INSTANCE_ID,
        "timestamp": time.time(),
    }
    with open(TELEGRAM_POLL_LOCK, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _acquire_polling_lock():
    lock_data = _read_poll_lock()
    if lock_data:
        last_seen = float(lock_data.get("timestamp", 0) or 0)
        other_instance = str(lock_data.get("instance_id", "") or "")
        if other_instance and other_instance != INSTANCE_ID and (time.time() - last_seen) < TELEGRAM_POLL_LOCK_TTL:
            return False, other_instance, max(0, TELEGRAM_POLL_LOCK_TTL - (time.time() - last_seen))
    _write_poll_lock()
    return True, None, 0


def _poll_lock_heartbeat():
    while True:
        try:
            lock_data = _read_poll_lock()
            if lock_data and lock_data.get("instance_id") not in (None, "", INSTANCE_ID):
                return
            _write_poll_lock()
        except Exception as e:
            print(f"Polling lock heartbeat failed: {e}")
        time.sleep(TELEGRAM_POLL_HEARTBEAT)


def _release_polling_lock():
    try:
        lock_data = _read_poll_lock()
        if lock_data and lock_data.get("instance_id") == INSTANCE_ID and os.path.exists(TELEGRAM_POLL_LOCK):
            os.remove(TELEGRAM_POLL_LOCK)
    except Exception as e:
        print(f"Polling lock release failed: {e}")

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    item_status = types.KeyboardButton("📊 Platform Status")
    item_rfq = types.KeyboardButton("📦 Top RFQ (Qty)")
    item_sheet = types.KeyboardButton("📑 Top Sheet")
    item_scrape = types.KeyboardButton("🔄 Force Scrape")
    item_sync_orders = types.KeyboardButton("🧾 Sync Orders")
    markup.add(item_status, item_rfq)
    markup.add(item_sheet, item_scrape)
    markup.add(item_sync_orders)
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "Salut! Sunt bot-ul tău Xometry. Folosește /status pentru a vedea situația actuală a joburilor, /scrape pentru a forța o actualizare, /syncorders pentru sync comenzi, sau /myid pentru a afla ID-ul tău.",
        reply_markup=main_menu_keyboard()
    )

@bot.message_handler(commands=['menu'])
def send_menu(message):
    bot.reply_to(message, "✅ Meniu afișat.", reply_markup=main_menu_keyboard())

@bot.message_handler(commands=['myid'])
def send_my_id(message):
    bot.reply_to(message, f"🆔 ID-ul tău este: `{message.chat.id}`\nCopiază acest ID și adaugă-l în configurare pentru a primi notificări.", parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def send_status(message):
    report, top_10 = get_status_report()
    send_markdown_message(message.chat.id, report, reply_markup=main_menu_keyboard())

    for i, job in enumerate(top_10, 1):
        jid = job.get('id')
        link = job.get('link', '')
        price = job.get('price', 0.0)
        type_str = job.get('type', '')
        if type_str == "Urgent":
            type_str = "🔥 Urgent"

        if link:
            line = f"{i}. 🔗 [{jid}]({link}) - *€{price:,.2f}* ({type_str})"
        else:
            line = f"{i}. `{jid}` - *€{price:,.2f}* ({type_str})"

        offer_id = job.get("offer_id")
        reply_markup = None
        if offer_id and not (jid and jid.startswith("RFQ-")):
            reply_markup = types.InlineKeyboardMarkup()
            reply_markup.add(
                types.InlineKeyboardButton("❌ Decline", callback_data=f"decline:{offer_id}")
            )

        bot.send_message(message.chat.id, line, parse_mode="Markdown", reply_markup=reply_markup)

@bot.message_handler(commands=['scrape'])
def trigger_scrape_command(message):
    trigger_scrape(message)


@bot.message_handler(commands=['agentlogs'])
def send_agent_logs(message):
    ok, err, logs = agent_client.fetch_logs(limit=12)
    if not ok:
        bot.send_message(message.chat.id, f"Eroare agent logs: {err}", reply_markup=main_menu_keyboard())
        return
    if not logs:
        bot.send_message(message.chat.id, "Nu exista loguri XometryAnaliza inca.", reply_markup=main_menu_keyboard())
        return

    lines = ["XometryAnaliza logs"]
    for item in logs:
        ts = item.get("ts")
        if ts:
            try:
                stamp = datetime.fromtimestamp(float(ts)).strftime("%d.%m %H:%M:%S")
            except Exception:
                stamp = "?"
        else:
            stamp = "?"
        message_text = str(item.get("message", ""))
        if len(message_text) > 180:
            message_text = message_text[:177] + "..."
        lines.append(f"{stamp} {item.get('type', '')}: {message_text}")
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=main_menu_keyboard())


def _run_orders_sync(chat_id):
    try:
        with sync_playwright() as p:
            browser = browser_utils.launch_browser(p.chromium)
            context = browser_utils.new_context(browser)
            page = context.new_page()
            details_page = context.new_page()
            auth.login(page)
            orders, _ = scraper.scrape_orders(
                page,
                details_page,
                max_orders=config.ORDERS_SYNC_MAX_ORDERS,
                scroll_rounds=config.ORDERS_SCROLL_ROUNDS,
                seen_order_ids=None,
                max_pages=config.ORDERS_PAGINATION_MAX_PAGES,
                stop_after_empty_pages=0,
                process_only_new=False,
            )
            if not orders:
                bot.send_message(chat_id, "⚠️ Nu am găsit comenzi pentru sincronizare.")
            else:
                ok, err = backend.send_orders_sync(orders)
                if ok:
                    bot.send_message(chat_id, f"✅ Sync comenzi trimis ({len(orders)} înregistrări).")
                else:
                    bot.send_message(chat_id, f"❌ Sync comenzi eșuat: {err}")
            browser.close()
    except Exception as e:
        bot.send_message(chat_id, f"❌ Eroare la sync comenzi: {e}")


@bot.message_handler(commands=['syncorders'])
def trigger_orders_sync(message):
    bot.send_message(message.chat.id, "⏳ Pornesc sync comenzi (orders)...")
    thread = threading.Thread(target=_run_orders_sync, args=(message.chat.id,))
    thread.daemon = True
    thread.start()

def trigger_scrape(message):
    bot.send_message(message.chat.id, "⏳ *Inițiez scraping manual...*\n_Repornesc procesul scraper..._", parse_mode="Markdown", reply_markup=main_menu_keyboard())

    try:
        restarted = None
        errors = []
        for process_name in ("xometry-main", "xometry_scraper"):
            result = subprocess.run(
                ["pm2", "restart", process_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                restarted = process_name
                break
            stderr = (result.stderr or result.stdout or "").strip()
            errors.append(f"{process_name}: {stderr}")

        if restarted:
            bot.send_message(
                message.chat.id,
                f"✅ *Scraper repornit ({restarted})!*\n_Durează 1-2 minute până apar date noi._",
                parse_mode="Markdown",
            )
        else:
            err_text = "\n".join(errors) if errors else "Unknown PM2 error"
            bot.send_message(message.chat.id, f"⚠️ *Eroare la restart:*\n`{err_text}`", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ *Eroare execuție:*\n`{str(e)}`", parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "📊 Platform Status")
def button_status_handler(message):
    send_status(message)

@bot.message_handler(func=lambda message: message.text == "📦 Top RFQ (Qty)")
def button_rfq_handler(message):
    report = get_top_rfqs_report()
    send_markdown_message(message.chat.id, report, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "📑 Top Sheet")
def button_sheet_handler(message):
    report = get_sheet_report()
    send_markdown_message(message.chat.id, report, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == "🔄 Force Scrape")
def button_scrape_handler(message):
    trigger_scrape(message)

@bot.message_handler(func=lambda message: message.text == "🧾 Sync Orders")
def button_sync_orders_handler(message):
    trigger_orders_sync(message)

def trigger_scrape(message):
    bot.send_message(
        message.chat.id,
        "Scraping manual pornit. Trimit trigger-ul catre containerul scraper.",
        reply_markup=main_menu_keyboard(),
    )
    try:
        _write_force_scrape_flag()
        bot.send_message(
            message.chat.id,
            "Trigger trimis catre scraper. Daca /app/data este volum comun, ruleaza imediat fara PM2.",
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"Eroare la trigger scrape: {e}")

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("decline:"))
def handle_decline_callback(call):
    chat_id = str(call.message.chat.id)
    if chat_id not in config.TELEGRAM_CHAT_IDS:
        bot.answer_callback_query(call.id, "Not allowed", show_alert=True)
        return

    offer_id = call.data.split(":", 1)[1].strip()
    job = find_job_by_offer_id(offer_id)
    job_id = job.get("id") if job else None

    bot.answer_callback_query(call.id, "Decline in progress...")

    if job_id:
        bot.send_message(call.message.chat.id, f"⏳ Decline offer {offer_id} (Job {job_id})...")
    else:
        bot.send_message(call.message.chat.id, f"⏳ Decline offer {offer_id}...")

    ok, err = decline_job_offer(offer_id)
    if ok:
        if job_id:
            bot.send_message(call.message.chat.id, f"✅ Declined offer {offer_id} (Job {job_id})")
        else:
            bot.send_message(call.message.chat.id, f"✅ Declined offer {offer_id}")
    else:
        bot.send_message(call.message.chat.id, f"❌ Decline failed for offer {offer_id}: {err}")

if __name__ == "__main__":
    print("Telegram Bot listener started...")
    # Set commands for the menu
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("status", "Arată statusul platformei"),
            telebot.types.BotCommand("scrape", "Forțează actualizarea datelor"),
            telebot.types.BotCommand("syncorders", "Sincronizează comenzile (orders)"),
            telebot.types.BotCommand("myid", "Arată ID-ul tău de chat"),
            telebot.types.BotCommand("help", "Ajutor")
        ])
    except Exception as e:
        print(f"Failed to set commands: {e}")
    
    # Notify startup
    try:
        try:
            bot.remove_webhook()
        except Exception as e:
            print(f"remove_webhook failed: {e}")
        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
                bot.send_message(chat_id, f"🟢 *Bot Online v{config.BOT_VERSION}*\n_Comenzi disponibile..._", parse_mode="Markdown", reply_markup=main_menu_keyboard())
            except Exception as e:
                print(f"Startup msg failed for {chat_id}: {e}")
    except Exception as e:
        print(f"Startup msg loop failed: {e}")

    print("Starting infinity polling...")
    acquired, owner, wait_seconds = _acquire_polling_lock()
    if not acquired:
        print(
            "Another Telegram polling instance is active "
            f"({owner}). Waiting instead of starting getUpdates polling."
        )
        while True:
            sleep_for = min(
                TELEGRAM_POLL_HEARTBEAT,
                max(5, int(wait_seconds) if wait_seconds else TELEGRAM_POLL_HEARTBEAT),
            )
            time.sleep(sleep_for)
            acquired, owner, wait_seconds = _acquire_polling_lock()
            if acquired:
                break
            print(
                "Polling lock still owned by another instance "
                f"({owner}); retrying in {int(max(1, wait_seconds))}s."
            )

    heartbeat_thread = threading.Thread(target=_poll_lock_heartbeat, daemon=True)
    heartbeat_thread.start()

    # restart_on_change=True allows it to recover from some errors, though usually for file changes.
    # timeout=25 default is 20. long_polling_timeout=20 default is 20.
    # We increase them slightly to match server latency.
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=25, skip_pending=True)
        except Exception as e:
            print(f"Polling crashed, retry in 5s: {e}")
            time.sleep(5)

import signal
import sys

def shutdown_handler(signum, frame):
    try:
        msg = f"🛑 *Bot Stopping*\nCalea: `{os.path.abspath(__file__)}`\nSemnal: {signum}"
        for chat_id in config.TELEGRAM_CHAT_IDS:
             try:
                bot.send_message(chat_id, msg, parse_mode="Markdown")
             except Exception as inner_e:
                print(f"Failed to send shutdown msg to {chat_id}: {inner_e}")
        print("Shutdown message sent.")
    except Exception as e:
        print(f"Failed to send shutdown msg: {e}")
    _release_polling_lock()
    sys.exit(0)

# Register signals
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)


