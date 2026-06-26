import os
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError, sync_playwright


CODE_FILE = Path(r"C:\tmp\clinicorp_code.txt")
STATUS_FILE = Path(r"C:\tmp\clinicorp_status.txt")
STATE_FILE = Path(r"C:\tmp\clinicorp_logged_state.json")
SCREENSHOT_FILE = Path(r"C:\tmp\clinicorp-logged.png")


def status(message):
    STATUS_FILE.write_text(message, encoding="utf-8")
    print(message, flush=True)


def wait_for_code(timeout_seconds=240):
    started = time.time()
    while time.time() - started < timeout_seconds:
        if CODE_FILE.exists():
            code = re.sub(r"\D", "", CODE_FILE.read_text(encoding="utf-8", errors="ignore"))
            if code:
                return code
        time.sleep(1)
    return None


def main():
    user = os.environ["CLINICORP_USER"]
    password = os.environ["CLINICORP_PASS"]
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    CODE_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome)
        context = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        page = context.new_page()

        status("abrindo login")
        page.goto("https://sistema.clinicorp.com/auth/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        page.locator("input").nth(0).fill(user)
        page.locator("input").nth(1).fill(password)
        page.get_by_text("Entrar", exact=True).click()
        page.wait_for_timeout(10000)

        if "/auth/2fa" not in page.url:
            status("login_nao_chegou_2fa")
            page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
            browser.close()
            return

        status("selecionando_whatsapp")
        page.locator("#challenge-WHATSAPP").click(force=True)
        page.wait_for_timeout(1000)
        page.locator("button").nth(2).click(force=True)
        page.wait_for_timeout(5000)
        page.screenshot(path=r"C:\tmp\clinicorp-2fa-waiting.png", full_page=True)

        status("aguardando_codigo")
        code = wait_for_code()
        if not code:
            status("codigo_nao_recebido")
            browser.close()
            return

        status("inserindo_codigo")
        inputs = page.locator("input")
        visible_non_radio = []
        for i in range(inputs.count()):
            item = inputs.nth(i)
            if item.is_visible() and item.is_enabled() and item.get_attribute("type") != "radio":
                visible_non_radio.append(item)

        if len(visible_non_radio) == 1:
            visible_non_radio[0].fill(code)
        else:
            for index, char in enumerate(code):
                if index < len(visible_non_radio):
                    visible_non_radio[index].fill(char)

        clicked = False
        for i in range(page.locator("button").count()):
            button = page.locator("button").nth(i)
            try:
                text = button.inner_text(timeout=1000)
            except Exception:
                text = ""
            if button.is_visible() and button.is_enabled() and "Confirmar" in text:
                button.click()
                clicked = True
                break

        if not clicked:
            page.keyboard.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except TimeoutError:
            pass

        page.wait_for_timeout(12000)
        context.storage_state(path=str(STATE_FILE))
        page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
        body = page.locator("body").inner_text(timeout=10000)
        Path(r"C:\tmp\clinicorp_after_login.txt").write_text(f"{page.url}\n\n{body[:10000]}", encoding="utf-8")
        status("logado" if "/auth/login" not in page.url and "/auth/2fa" not in page.url else "falha_login")
        browser.close()


if __name__ == "__main__":
    main()
