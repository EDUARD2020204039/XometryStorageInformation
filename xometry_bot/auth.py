import json
import time

import requests
from playwright.sync_api import Page

import config


SESSION_TEST_QUERY = """query gshJobOffers($filter: OffersFilterType!, $offsetAttributes: OffsetAttributes) {
  gshJobOffers(filter: $filter, offsetAttributes: $offsetAttributes) {
    metadata { totalCount hasMore }
    offers {
      __typename
      ... on JobOffer { id code }
      ... on Offer { id job { displayId } }
    }
  }
}
"""


class XometryLoginError(RuntimeError):
    def __init__(self, message: str, status: dict | None = None):
        super().__init__(message)
        self.status = status or {}


def _now_status(**values):
    return {"checked_at": time.time(), **values}


def _remove_cookie_banner(page: Page) -> None:
    try:
        page.evaluate("""
            () => {
                const root = document.getElementById('usercentrics-root');
                if (root) root.remove();
            }
        """)
    except Exception:
        pass


def _is_visible(page: Page, selector: str, timeout: int = 750) -> bool:
    try:
        return page.locator(selector).first.is_visible(timeout=timeout)
    except Exception:
        return False


def _body_sample(page: Page) -> tuple[str, int]:
    try:
        text = page.locator("body").inner_text(timeout=1500).strip()
    except Exception:
        text = ""
    return text[:500], len(text)


def _auth_token(page: Page) -> str:
    try:
        return page.evaluate("() => localStorage.getItem('authToken') || ''") or ""
    except Exception:
        return ""


def _validate_api_token(token: str) -> dict:
    if not token:
        return {"ok": False, "reason": "missing_auth_token"}
    try:
        response = requests.post(
            "https://api.xometry.eu/partners/graphql?gshJobOffers",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "authorization": f"Bearer {token}",
            },
            data=json.dumps({
                "operationName": "gshJobOffers",
                "query": SESSION_TEST_QUERY,
                "variables": {
                    "filter": {"urgentStatus": "without_urgent", "responseStatus": "empty"},
                    "offsetAttributes": {"limit": 1, "offset": 0},
                },
            }),
            timeout=20,
        )
        if response.status_code != 200:
            return {"ok": False, "reason": f"graphql_http_{response.status_code}"}
        payload = response.json()
        if payload.get("errors"):
            message = str(payload.get("errors"))[:240]
            return {"ok": False, "reason": "graphql_errors", "detail": message}
        data = payload.get("data") or {}
        offers = (data.get("gshJobOffers") or {}).get("offers")
        if offers is None:
            return {"ok": False, "reason": "graphql_missing_offers"}
        return {"ok": True, "reason": "graphql_ok", "sample_count": len(offers)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def inspect_session(page: Page, validate_api: bool = True) -> dict:
    _remove_cookie_banner(page)
    sample, body_len = _body_sample(page)
    login_form = _is_visible(page, "#basic_email") or _is_visible(page, "#basic_password")
    job_board = _is_visible(page, "text=Job Board", timeout=1200)
    order_value = _is_visible(page, "text=Total order value", timeout=1200)
    token = _auth_token(page)
    api = _validate_api_token(token) if validate_api else {"ok": bool(token), "reason": "not_validated"}

    lowered = sample.lower()
    blank_like = body_len < 50 and not job_board and not order_value and not login_form
    login_text = any(marker in lowered for marker in ("sign in", "log in", "email", "password"))
    ui_ok = (job_board or order_value) and not login_form and not blank_like
    ok = bool(api.get("ok") or ui_ok)

    reason = "ok"
    if not ok:
        if login_form or login_text:
            reason = "login_required"
        elif blank_like:
            reason = "blank_page"
        elif token and not api.get("ok"):
            reason = f"token_invalid:{api.get('reason')}"
        else:
            reason = "unknown_xometry_state"
    elif ui_ok and not api.get("ok"):
        reason = f"ui_ok_api_warning:{api.get('reason')}"

    return _now_status(
        ok=ok,
        reason=reason,
        url=page.url,
        title=page.title() if not blank_like else "",
        body_length=body_len,
        body_sample=sample,
        login_form=login_form,
        job_board=job_board,
        total_order_value=order_value,
        auth_token_present=bool(token),
        api_ok=bool(api.get("ok")),
        api_reason=api.get("reason") or "",
        api_detail=api.get("detail") or "",
        api_sample_count=api.get("sample_count"),
    )


def _fill_login_form(page: Page) -> None:
    js_login_script = f"""
    (function() {{
        const emailInput = document.getElementById('basic_email');
        const passwordInput = document.getElementById('basic_password');

        const setNativeValue = (element, value) => {{
            const valueSetter = Object.getOwnPropertyDescriptor(element.__proto__, 'value').set;
            const prototype = Object.getPrototypeOf(element);
            const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value').set;

            if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {{
                prototypeValueSetter.call(element, value);
            }} else {{
                valueSetter.call(element, value);
            }}
        }};

        if (emailInput) {{
            setNativeValue(emailInput, {json.dumps(config.XOMETRY_EMAIL)});
            emailInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            emailInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            emailInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        }}
        if (passwordInput) {{
            setNativeValue(passwordInput, {json.dumps(config.XOMETRY_PASSWORD)});
            passwordInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            passwordInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            passwordInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        }}
    }})();
    """
    page.evaluate(js_login_script)
    time.sleep(1)


def _save_debug_artifacts(page: Page) -> None:
    try:
        page.screenshot(path="login_debug.png", full_page=True)
        print("Saved login_debug.png")
    except Exception as exc:
        print(f"Could not save login_debug.png: {exc}")
    try:
        with open("login_debug.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("Saved login_debug.html")
    except Exception as exc:
        print(f"Could not save login_debug.html: {exc}")


def login(page: Page) -> dict:
    """
    Logs into Xometry Partner Portal and validates that the session is usable.
    A usable session means either GraphQL accepts the auth token or the Job Board UI
    is visible enough for the fallback UI scraper. Blank/login pages are fatal.
    """
    print(f"Navigating to {config.XOMETRY_LOGIN_URL}...")
    page.goto(config.XOMETRY_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
    _remove_cookie_banner(page)
    time.sleep(1)

    login_form = _is_visible(page, "#basic_email", timeout=3000)
    if login_form:
        print("Xometry login form detected. Attempting login...")
        _fill_login_form(page)
        try:
            print("Clicking login button via Playwright...")
            page.click("button.ant-btn-primary", timeout=5000)
        except Exception:
            print("Playwright click failed; trying JS click fallback...")
            page.evaluate("document.querySelector('button.ant-btn-primary')?.click()")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(2)
    else:
        print("No login form detected. Validating existing Xometry session...")

    status = inspect_session(page, validate_api=True)
    print(
        "Xometry session check: "
        f"ok={status['ok']} reason={status['reason']} "
        f"url={status['url']} token={status['auth_token_present']} api={status['api_ok']}"
    )
    if not status["ok"]:
        _save_debug_artifacts(page)
        raise XometryLoginError(f"Xometry session invalid: {status['reason']}", status=status)
    if not status.get("api_ok"):
        print(f"Warning: Xometry UI looks logged in, but API token check failed: {status.get('api_reason')}")
    return status
