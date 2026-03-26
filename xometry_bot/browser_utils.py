import time

import config


def launch_browser(chromium, logger=None):
    base_options = {
        "headless": config.HEADLESS,
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
    }
    channel_candidates = []
    preferred_channel = (config.PLAYWRIGHT_BROWSER_CHANNEL or "").strip()
    if preferred_channel:
        channel_candidates.append(preferred_channel)
    channel_candidates.append(None)

    # Keep order while removing duplicates.
    unique_channels = []
    seen = set()
    for channel in channel_candidates:
        if channel in seen:
            continue
        seen.add(channel)
        unique_channels.append(channel)

    last_error = None
    for attempt in range(1, config.PLAYWRIGHT_LAUNCH_RETRIES + 1):
        for channel in unique_channels:
            launch_options = dict(base_options)
            label = channel or "default"
            if channel:
                launch_options["channel"] = channel
            try:
                if logger:
                    logger.info(f"Launching Chromium via channel={label} (attempt {attempt}/{config.PLAYWRIGHT_LAUNCH_RETRIES})")
                return chromium.launch(**launch_options)
            except Exception as exc:
                last_error = exc
                if logger:
                    logger.warning(f"Chromium launch failed via channel={label} (attempt {attempt}/{config.PLAYWRIGHT_LAUNCH_RETRIES}): {exc}")
        if attempt < config.PLAYWRIGHT_LAUNCH_RETRIES:
            time.sleep(config.PLAYWRIGHT_LAUNCH_RETRY_DELAY)

    raise last_error


def new_context(browser):
    return browser.new_context(user_agent=config.BROWSER_USER_AGENT)
