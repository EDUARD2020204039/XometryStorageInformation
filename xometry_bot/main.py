import logging
import sys
import time
import json
import os
from urllib.parse import quote
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

    def _sheet_part_ids(job):
        ids = set()
        for part in job.get("parts") or []:
            if not isinstance(part, dict):
                continue
            values = [
                part.get("process"),
                part.get("processType"),
                part.get("process_type"),
                part.get("material"),
                part.get("part_name"),
                part.get("name"),
            ]
            processes = part.get("processes")
            if isinstance(processes, list):
                values.extend(processes)
            elif processes:
                values.append(processes)
            haystack = " ".join(str(value or "") for value in values).lower()
            if not any(keyword in haystack for keyword in ("sheet", "sheet metal", "metal sheet", "laser", "laser cutting", "bending", "tabla", "tablă")):
                continue
            part_id = str(part.get("part_id") or part.get("id") or "").strip()
            if part_id:
                ids.add(part_id.lower())
                digits = "".join(ch for ch in part_id if ch.isdigit())
                if digits:
                    ids.add(digits.lower())
        return ids

    def _geo_item_matches_sheet_part(item, sheet_ids):
        if not sheet_ids:
            return True
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("part_id", "part_name", "partName", "target_path", "targetPath")
        ).lower()
        return any(part_id and part_id in haystack for part_id in sheet_ids)

    def _geo_items(geo_status, job=None):
        if not geo_status:
            return []
        sheet_ids = _sheet_part_ids(job or {})
        return [
            (index, item)
            for index, item in enumerate(geo_status.get("geo_items") or [])
            if (item.get("target_path") or item.get("targetPath")) and item.get("geo_exists") is True
            and _geo_item_matches_sheet_part(item, sheet_ids)
        ]

    def _geo_view_url(offer_id, item_index):
        return (
            f"{config.AGENT_PUBLIC_URL.rstrip('/')}/api/agents/geo/"
            f"{quote(str(offer_id))}/files/{item_index}/view"
        )

    def _geo_file_label(item, number):
        target_path = str(item.get("target_path") or item.get("targetPath") or "").strip()
        filename = target_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        part_name = str(item.get("part_name") or item.get("partName") or "").strip()
        return filename or part_name or f"GEO {number}"

    def _fetch_geo_status(job):
        offer_id = job.get("offer_id")
        if not offer_id:
            return None
        ok, err, data = agent_client.fetch_geo_status(offer_id)
        if not ok:
            logger.debug(f"GEO status unavailable for {job.get('id')}: {err}")
            return None
        return data

    def _requires_geo_before_notify(job):
        haystack = f"{job.get('material', '')} {job.get('process', '')}".lower()
        geo_keywords = (
            "sheet",
            "metal sheet",
            "sheet metal",
            "tabla",
            "tablă",
            "laser",
            "laser cutting",
            "bending",
        )
        return any(keyword in haystack for keyword in geo_keywords)

    def _interesting_message(job, geo_status=None):
        jid = job["id"]
        link = job.get("link", "")
        offer_id = job.get("offer_id")
        jid_safe = escape_html(jid)
        link_safe = escape_html(link)
        id_str = f'<a href="{link_safe}">{jid_safe}</a>' if link else f"<code>{jid_safe}</code>"

        type_label = "🔥 Urgent" if job["type"] == "Urgent" else job["type"]
        type_label_safe = escape_html(type_label)
        material_safe = escape_html(job["material"])
        process_safe = escape_html(job["process"])
        price_safe = escape_html(job["price"])

        geo_line = ""
        geo_url = None
        geo_state_key = "geo:none"
        geo_ready_items = _geo_items(geo_status, job)
        geo_blocked = False
        if geo_ready_items and offer_id:
            geo_links = []
            for number, (item_index, item) in enumerate(geo_ready_items, start=1):
                geo_url = _geo_view_url(offer_id, item_index)
                label = _geo_file_label(item, number)
                geo_links.append(f'{number}. <a href="{escape_html(geo_url)}">{escape_html(label)}</a>')
            geo_line = "Geo:\n" + "\n".join(geo_links) + "\n"
            bend_report = geo_status.get("bend_report") or {}
            if bend_report and not bend_report.get("has_bend_issues") and int(bend_report.get("info_count") or 0) > 0:
                geo_line += "Indoire: fara indoiri detectate\n"
            geo_state_key = "geo_links_all_v1:" + "|".join(
                str(item.get("target_path") or item.get("targetPath") or "")
                for _, item in geo_ready_items
            )
        elif geo_status and geo_status.get("status") == "skipped_rfq":
            geo_line = "GEO: RFQ fără fișiere pentru desfașurată automată\n"
            geo_state_key = "geo:skipped_rfq"

        if not geo_ready_items and geo_status and geo_status.get("status") in ("blocked_login", "blocked_documentation"):
            geo_blocked = True
            state = geo_status.get("state") or {}
            sheet = state.get("sheet_metal_laser") or {}
            reason = sheet.get("error") or geo_status.get("status")
            action = sheet.get("failure_action") or ""
            geo_line = f"GEO: blocat - {escape_html(reason)}\n"
            if action:
                geo_line += f"Actiune: {escape_html(action)}\n"
            geo_state_key = f"geo:{geo_status.get('status')}:{reason}"

        keyboard = []
        if offer_id:
            keyboard.append([{"text": "❌ Decline", "callback_data": f"decline:{offer_id}"}])
        reply_markup = {"inline_keyboard": keyboard} if keyboard else None

        msg = (
            f"🚀 <b>INTERESTING JOB FOUND</b> 🚀\n"
            f"ID: {id_str}\n"
            f"Type: {type_label_safe}\n"
            f"Material: {material_safe}\n"
            f"Price: €{price_safe}\n"
            f"Process: {process_safe}\n"
            f"{geo_line}"
        )
        return msg, reply_markup, geo_state_key, bool(geo_ready_items), geo_blocked

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

            # 1. Login and validate the Xometry session before scraping.
            try:
                session_status = auth.login(page)
                ok, info = agent_client.report_xometry_session({
                    **session_status,
                    "source": "scraper",
                    "phase": "login",
                })
                if not ok:
                    logger.warning(f"Could not report Xometry session status: {info}")
            except auth.XometryLoginError as e:
                session_status = {
                    **getattr(e, "status", {}),
                    "ok": False,
                    "source": "scraper",
                    "phase": "login",
                }
                ok, info = agent_client.report_xometry_session(session_status)
                if not ok:
                    logger.warning(f"Could not report failed Xometry session status: {info}")
                logger.error(f"Xometry login/session validation failed: {e}")
                return
            
            # 2. Scrape
            logger.info("Scraping jobs...")
            jobs = scraper.scrape_all(page)
            if not jobs:
                agent_client.report_xometry_session({
                    **(session_status or {}),
                    "ok": False,
                    "reason": "scrape_returned_zero_jobs",
                    "phase": "scrape",
                    "source": "scraper",
                })
                logger.error("Scrape returned 0 jobs. Keeping previous data and skipping notifications.")
                return
            logger.info(f"Total jobs found: {len(jobs)}")
            agent_client.report_xometry_session({
                **(session_status or {}),
                "ok": True,
                "reason": "scrape_ok",
                "phase": "scrape",
                "source": "scraper",
                "jobs_count": len(jobs),
            })

            # 3. Save to JSON for bot_app.py
            os.makedirs("data", exist_ok=True)
            with open("data/all_jobs.json", "w") as f:
                json.dump(jobs, f, indent=4)
            logger.info(f"Saved {len(jobs)} jobs to data/all_jobs.json")

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
            payload_by_offer_id = {str(payload.get("offer_id")): payload for payload in payloads if payload.get("offer_id")}
            detailed_agent_jobs = []
            for job in jobs:
                payload = payload_by_offer_id.get(str(job.get("offer_id")))
                if not payload:
                    continue
                job["parts"] = payload.get("parts") or []
                job["parts_pricing"] = payload.get("parts_pricing") or []
                if payload.get("title"):
                    job["id"] = payload["title"]
                if payload.get("url"):
                    job["link"] = payload["url"]
                has_detailed_parts = bool(job.get("parts"))
                if _sheet_part_ids(job) or (not has_detailed_parts and _requires_geo_before_notify(job)):
                    detailed_agent_jobs.append(dict(job))

            if detailed_agent_jobs:
                ok, agent_info = agent_client.submit_jobs(detailed_agent_jobs, source="scraper-details")
                if ok:
                    logger.info(f"Submitted detailed jobs to XometryAnaliza agents: {agent_info}")
                else:
                    logger.error(f"Failed to submit detailed jobs to XometryAnaliza agents: {agent_info}")
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
                    geo_status = _fetch_geo_status(job)
                    msg, reply_markup, geo_state_key, geo_ready, geo_blocked = _interesting_message(job, geo_status)
                    logger.info(f"Checking/Sending notification for {job['id']}")
                    if _requires_geo_before_notify(job) and not geo_ready and not geo_blocked:
                        status = (geo_status or {}).get("status") or "not_ready"
                        logger.info(f"Waiting for GEO before Telegram notification for {job['id']} ({status}).")
                        continue
                    if notifier.is_already_notified(job["id"]):
                        if geo_ready:
                            notifier.edit_telegram_if_changed(
                                job["id"],
                                msg,
                                reply_markup=reply_markup,
                                state_key=geo_state_key,
                            )
                    else:
                        notifier.send_telegram(
                            msg,
                            job_id=job["id"],
                            reply_markup=reply_markup,
                            state_key=geo_state_key,
                        )
                    continue
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
