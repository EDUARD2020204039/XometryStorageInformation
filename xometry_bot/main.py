import logging
import sys
import time
import json
import os
from playwright.sync_api import sync_playwright
import config
import auth
import scraper
import filter
import notifier
import backend
import browser_utils
import agent_client

FORCE_SCRAPE_FLAG = os.path.join("data", "force_scrape.flag")
FORCE_SCRAPE_POLL_INTERVAL = 5

# Configure logging
logger = logging.getLogger('xometry_bot')
logger.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Console Handler
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File Handler
    fh = logging.FileHandler('bot.log')
    fh.setFormatter(formatter)
    logger.addHandler(fh)


def _consume_force_scrape_flag():
    if not os.path.exists(FORCE_SCRAPE_FLAG):
        return False
    try:
        os.remove(FORCE_SCRAPE_FLAG)
        logger.info("Consumed manual force-scrape trigger from shared volume.")
        return True
    except Exception as e:
        logger.warning(f"Failed to consume force-scrape trigger: {e}")
        return False


def _sleep_until_next_iteration(sleep_time):
    remaining = max(0, float(sleep_time))
    while remaining > 0:
        if _consume_force_scrape_flag():
            logger.info("Manual force-scrape trigger detected. Starting next iteration early.")
            return
        chunk = min(FORCE_SCRAPE_POLL_INTERVAL, remaining)
        time.sleep(chunk)
        remaining -= chunk

def run_iteration():
    """
    Performs one full scrape iteration: launch -> login -> scrape -> close.
    This fixes EPIPE issues in long-lived background processes.
    """
    def escape_html(text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _orders_sync_state_path():
        return os.path.join("data", "orders_last_sync.txt")

    def _orders_seen_path():
        return os.path.join("data", "orders_seen.json")

    def _orders_lock_path():
        return os.path.join("data", "orders_sync.lock")

    def _read_last_orders_sync():
        path = _orders_sync_state_path()
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r") as f:
                return float(f.read().strip() or 0)
        except Exception:
            return 0

    def _write_last_orders_sync(ts):
        os.makedirs("data", exist_ok=True)
        try:
            with open(_orders_sync_state_path(), "w") as f:
                f.write(str(ts))
        except Exception:
            pass

    def _load_seen_orders():
        path = _orders_seen_path()
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return set(data or [])
        except Exception:
            return set()

    def _save_seen_orders(seen):
        os.makedirs("data", exist_ok=True)
        try:
            with open(_orders_seen_path(), "w") as f:
                json.dump(sorted(seen), f)
        except Exception:
            pass

    def _acquire_orders_lock():
        os.makedirs("data", exist_ok=True)
        path = _orders_lock_path()
        if os.path.exists(path):
            age = time.time() - os.path.getmtime(path)
            if age < config.ORDERS_SYNC_LOCK_MAX_AGE:
                return False
        try:
            with open(path, "w") as f:
                f.write(str(time.time()))
        except Exception:
            return False
        return True

    def _release_orders_lock():
        path = _orders_lock_path()
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        details_page = None
        try:
            browser = browser_utils.launch_browser(p.chromium, logger=logger)
            context = browser_utils.new_context(browser)
            page = context.new_page()
            details_page = context.new_page()

            # 1. Login
            auth.login(page)
            
            # 2. Scrape
            logger.info("Scraping jobs...")
            jobs = scraper.scrape_all(page)
            if not jobs:
                logger.error("Scrape returned 0 jobs. Keeping previous data and skipping notifications.")
                return
            logger.info(f"Total jobs found: {len(jobs)}")

            # 3. Save to JSON for bot_app.py
            os.makedirs("data", exist_ok=True)
            with open("data/all_jobs.json", "w") as f:
                json.dump(jobs, f, indent=4)
            logger.info(f"Saved {len(jobs)} jobs to data/all_jobs.json")

            agent_ok, agent_info = agent_client.submit_jobs(jobs, source="scraper")
            if agent_ok:
                logger.info(f"Submitted jobs to XometryAnaliza agents: {agent_info}")
            else:
                logger.error(f"Failed to submit jobs to XometryAnaliza agents: {agent_info}")

            existing_offer_ids = backend.fetch_existing_offer_ids()
            synced_offer_ids = backend.load_synced_offer_ids()
            if config.BACKEND_RESEND_EXISTING:
                skip_offer_ids = synced_offer_ids
            else:
                skip_offer_ids = existing_offer_ids | synced_offer_ids

            payloads = scraper.build_backend_payloads(
                details_page,
                jobs,
                skip_offer_ids=skip_offer_ids,
                max_offers=config.BACKEND_MAX_OFFERS_PER_RUN,
            )
            logger.info(
                f"Backend payloads ready: {len(payloads)} "
                f"(skip existing: {len(existing_offer_ids)}, synced: {len(synced_offer_ids)}, "
                f"resend_existing={config.BACKEND_RESEND_EXISTING})"
            )
            if not payloads:
                logger.info("No new offers to send to backend.")
            else:
                ok, err, ok_ids = backend.send_payloads(payloads)
                backend.mark_synced(ok_ids)
                if ok:
                    logger.info("Sent offers to backend.")
                else:
                    logger.error(f"Backend send failed: {err}")

            # 4. Filter & Notify
            interesting_count = 0
            for job in jobs:
                if filter.is_interesting(job):
                    interesting_count += 1
                    jid = job['id']
                    link = job.get('link', '')
                    
                    jid_safe = escape_html(jid)
                    link_safe = escape_html(link)
                    id_str = f'<a href="{link_safe}">{jid_safe}</a>' if link else f"<code>{jid_safe}</code>"
                    
                    type_label = "🔥 Urgent" if job['type'] == "Urgent" else job['type']
                    type_label_safe = escape_html(type_label)
                    material_safe = escape_html(job['material'])
                    process_safe = escape_html(job['process'])
                    price_safe = escape_html(job['price'])
                    reply_markup = None
                    offer_id = job.get("offer_id")
                    if offer_id:
                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": "❌ Decline", "callback_data": f"decline:{offer_id}"}]
                            ]
                        }

                    msg = (
                        f"🚀 <b>INTERESTING JOB FOUND</b> 🚀\n"
                        f"ID: {id_str}\n"
                        f"Type: {type_label_safe}\n"
                        f"Material: {material_safe}\n"
                        f"Price: €{price_safe}\n"
                        f"Process: {process_safe}\n"
                    )
                    logger.info(f"Checking/Sending notification for {job['id']}")
                    notifier.send_telegram(msg, job_id=job['id'], reply_markup=reply_markup)
            
            logger.info(f"Iteration finished. Found {interesting_count} interesting jobs.")

            if config.ORDERS_SYNC_ENABLED:
                last_sync = _read_last_orders_sync()
                now = time.time()
                if now - last_sync >= config.ORDERS_SYNC_INTERVAL:
                    if not _acquire_orders_lock():
                        logger.info("Orders sync already running. Skipping this cycle.")
                    else:
                        try:
                            seen_orders = _load_seen_orders()
                            logger.info("Scraping orders for backend sync...")
                            orders, seen_after = scraper.scrape_orders(
                                page,
                                details_page,
                                max_orders=config.ORDERS_SYNC_MAX_ORDERS,
                                scroll_rounds=config.ORDERS_SCROLL_ROUNDS,
                                seen_order_ids=seen_orders,
                                max_pages=config.ORDERS_PAGINATION_MAX_PAGES,
                                stop_after_empty_pages=config.ORDERS_STOP_AFTER_EMPTY_PAGES,
                                process_only_new=config.ORDERS_PROCESS_ONLY_NEW,
                            )
                            if not orders:
                                logger.warning("Orders sync: no data found.")
                            else:
                                ok, err = backend.send_orders_sync(orders)
                                if ok:
                                    _write_last_orders_sync(now)
                                    logger.info(f"Orders sync sent: {len(orders)} records.")
                                else:
                                    logger.error(f"Orders sync failed: {err}")
                            if 'seen_after' in locals():
                                _save_seen_orders(seen_after)
                        finally:
                            _release_orders_lock()
            
        except Exception as e:
            logger.error(f"Error during iteration: {e}")
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if details_page:
                    details_page.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception as e:
                logger.warning(f"Browser close skipped: {e}")

def main():
    logger.info("Starting Xometry Bot (Stable Mode)...")
    _consume_force_scrape_flag()

    while True:
        start_time = time.time()
        try:
            run_iteration()
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Unhandled iteration failure. Keeping process alive for next cycle.")

        elapsed = time.time() - start_time
        sleep_time = max(0, config.CHECK_INTERVAL - elapsed)

        logger.info(f"Iteration took {elapsed:.1f}s. Sleeping for {sleep_time:.1f}s...")
        _sleep_until_next_iteration(sleep_time)

if __name__ == "__main__":
    main()
