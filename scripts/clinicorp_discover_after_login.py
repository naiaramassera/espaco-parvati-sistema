import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError, sync_playwright


TMP = Path(r"C:\tmp")
CODE_FILE = TMP / "clinicorp_code.txt"
STATUS_FILE = TMP / "clinicorp_status.txt"
NETWORK_FILE = TMP / "clinicorp_network.jsonl"
DISCOVERY_FILE = TMP / "clinicorp_discovery.txt"


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


def capture_response(response):
    url = response.url
    if "clinicorp" not in url:
        return
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type and "application" not in content_type:
        return
    try:
        text = response.text()
    except Exception:
        return
    record = {
        "url": url,
        "status": response.status,
        "content_type": content_type,
        "body_start": text[:4000],
    }
    with NETWORK_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def visible_texts(page, selector):
    items = []
    for i in range(min(120, page.locator(selector).count())):
        item = page.locator(selector).nth(i)
        try:
            text = item.inner_text(timeout=500).strip()
            if text and item.is_visible():
                items.append((i, text))
        except Exception:
            pass
    return items


def close_overlays(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    for text in ["close", "Close", "Fechar", "Agora não", "Não obrigado", "Minimizar todas"]:
        try:
            page.get_by_text(text, exact=True).click(timeout=1000)
            page.wait_for_timeout(500)
        except Exception:
            pass


def write_discovery(page, label):
    with DISCOVERY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n===== {label} =====\n")
        fh.write(f"URL: {page.url}\n")
        try:
            fh.write(page.locator("body").inner_text(timeout=10000)[:12000])
        except Exception as exc:
            fh.write(f"BODY_ERROR: {exc}\n")
        fh.write("\n\nBUTTONS:\n")
        for idx, text in visible_texts(page, "button"):
            fh.write(f"{idx}: {text}\n")
        fh.write("\nLINKS:\n")
        for idx, text in visible_texts(page, "a"):
            href = ""
            try:
                href = page.locator("a").nth(idx).get_attribute("href") or ""
            except Exception:
                pass
            fh.write(f"{idx}: {text} -> {href}\n")


def login(page, context):
    user = os.environ["CLINICORP_USER"]
    password = os.environ["CLINICORP_PASS"]

    CODE_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)
    NETWORK_FILE.unlink(missing_ok=True)
    DISCOVERY_FILE.unlink(missing_ok=True)

    status("abrindo_login")
    page.goto("https://sistema.clinicorp.com/auth/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    page.locator("input").nth(0).fill(user)
    page.locator("input").nth(1).fill(password)
    page.get_by_text("Entrar", exact=True).click()
    page.wait_for_timeout(10000)

    if "/auth/2fa" not in page.url:
        status("login_nao_chegou_2fa")
        page.screenshot(path=str(TMP / "clinicorp_error.png"), full_page=True)
        return False

    status("enviando_whatsapp")
    page.locator("#challenge-WHATSAPP").click(force=True)
    page.wait_for_timeout(1000)
    page.locator("button").nth(2).click(force=True)
    page.wait_for_timeout(5000)
    status("aguardando_codigo")
    code = wait_for_code()
    if not code:
        status("codigo_nao_recebido")
        return False

    status("confirmando_codigo")
    inputs = page.locator("input")
    visible_non_radio = []
    for i in range(inputs.count()):
        item = inputs.nth(i)
        if item.is_visible() and item.is_enabled() and item.get_attribute("type") != "radio":
            visible_non_radio.append(item)

    for index, char in enumerate(code):
        if index < len(visible_non_radio):
            visible_non_radio[index].fill(char)

    for i in range(page.locator("button").count()):
        button = page.locator("button").nth(i)
        try:
            text = button.inner_text(timeout=1000)
        except Exception:
            text = ""
        if button.is_visible() and button.is_enabled() and "Confirmar" in text:
            button.click()
            break

    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except TimeoutError:
        pass
    page.wait_for_timeout(12000)
    context.storage_state(path=str(TMP / "clinicorp_logged_state.json"))
    return "/auth/login" not in page.url and "/auth/2fa" not in page.url


def main():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome)
        context = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        page = context.new_page()
        page.on("response", capture_response)

        if not login(page, context):
            status("falha_login")
            browser.close()
            return

        status("logado_descobrindo")
        close_overlays(page)
        write_discovery(page, "home")
        page.screenshot(path=str(TMP / "clinicorp_home.png"), full_page=True)

        for label in ["Pacientes", "Agenda", "Relatórios"]:
            status(f"abrindo_{label}")
            try:
                page.get_by_text(label, exact=True).click(timeout=8000)
            except Exception:
                try:
                    page.get_by_text(label).first.click(timeout=8000)
                except Exception as exc:
                    with DISCOVERY_FILE.open("a", encoding="utf-8") as fh:
                        fh.write(f"\nCLICK_ERROR {label}: {exc}\n")
                    continue
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except TimeoutError:
                pass
            page.wait_for_timeout(12000)
            close_overlays(page)
            write_discovery(page, label)
            page.screenshot(path=str(TMP / f"clinicorp_{label}.png"), full_page=True)

        status("descoberta_concluida")
        browser.close()


if __name__ == "__main__":
    main()
