from playwright.sync_api import Page, expect
import config
import time

def login(page: Page):
    """
    Logs into Xometry Partner Portal using the configured credentials.
    Uses a JS-based approach to trigger React input events.
    """
    print(f"Navigating to {config.XOMETRY_LOGIN_URL}...")
    page.goto(config.XOMETRY_LOGIN_URL)

    # Brute force: remove the usercentrics-root element if it exists to unblock clicks
    try:
        print("DEBUG: Cookie check started")
        page.evaluate("""
            () => {
                const root = document.getElementById('usercentrics-root');
                if (root) {
                    root.remove();
                    console.log('Removed usercentrics-root');
                }
            }
        """)
        time.sleep(1)
    except:
        pass

    # Check if already logged in (look for sign out or dashboard elements)
    try:
        page.wait_for_selector("#basic_email", timeout=3000)
        print("Login page detected.")
    except:
        print("Already logged in or different page state.")
        return

    print("Attempting login...")
    
    # Use the JS injection method found during research to ensure React state updates
    js_login_script = f"""
    (function() {{
        const emailInput = document.getElementById('basic_email');
        const passwordInput = document.getElementById('basic_password');
        const loginButton = document.querySelector('button.ant-btn-primary');

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
            setNativeValue(emailInput, '{config.XOMETRY_EMAIL}');
            emailInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            emailInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            emailInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        }}
        if (passwordInput) {{
            setNativeValue(passwordInput, '{config.XOMETRY_PASSWORD}');
            passwordInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            passwordInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            passwordInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        }}
    }})();
    """
    
    page.evaluate(js_login_script)
    time.sleep(1) # Give React a moment to update state

    # Click via Playwright for better reliability
    try:
        print("Clicking login button via Playwright...")
        page.click("button.ant-btn-primary", timeout=3000)
    except:
        print("Playwright click failed (selector?), trying JS click fallback...")
        page.evaluate("document.querySelector('button.ant-btn-primary')?.click()")
    
    # Wait for navigation or success indicator
    try:
        # Wait for either URL change OR specific dashboard content
        # The URL check might fail if it's an SPA redirecting internally without updating history immediately
        # So we also check for "Job Board" text or "Total order value"
        print("Waiting for login success indicators...")
        
        # We define a predicate waiting for URL or Selector
        # Since playwright sync doesn't support 'race' easily for different types, we'll try a generic wait
        # or check multiple things. 
        # Best approach: wait for a selector that appears on the dashboard.
        
        # "Job Board" header usually appears on /offers
        page.wait_for_selector("text=Job Board", timeout=15000)
        print("Login successful (Dashboard detected).")
        
        # Optional: verify URL matches expected pattern, but don't fail if it doesn't match exactly immediately
        if "offers" not in page.url:
             print(f"Note: URL is {page.url} but dashboard content is visible.")

    except:
        print(f"Warning: Login might have failed or taken too long. Current URL: {page.url}")
        try:
            # Check one more common indicator: "Total order value"
            if page.locator("text='Total order value'").is_visible():
                print("Login successful (Secondary indicator found).")
                return
            
            page.screenshot(path="login_debug.png")
            print("Saved login_debug.png")
            with open("login_debug.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("Saved login_debug.html")
        except:
            pass
        # Optional: check for error alerts
