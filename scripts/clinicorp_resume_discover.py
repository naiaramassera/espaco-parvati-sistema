import json
from pathlib import Path

from playwright.sync_api import TimeoutError, sync_playwright


TMP = Path(r"C:\tmp")
STATE_FILE = TMP / "clinicorp_logged_state.json"
NETWORK_FILE = TMP / "clinicorp_resume_network.jsonl"
DISCOVERY_FILE = TMP / "clinicorp_resume_discovery.txt"


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


def close_overlays(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    for selector in [
        "button:has-text('Ok')",
        "button:has-text('Cancelar')",
        "button:has-text('close')",
        "[aria-label='close']",
        "[data-testid='close']",
    ]:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible(timeout=1000):
                loc.click(force=True, timeout=1000)
                page.wait_for_timeout(500)
        except Exception:
            pass

    # Clinicorp sometimes leaves a custom modal overlay intercepting clicks.
    page.evaluate(
        """
        for (const selector of ['#c_modal_main_div', '[data-testid="modal_overlay"]']) {
          document.querySelectorAll(selector).forEach((node) => node.remove());
        }
        """
    )
    page.wait_for_timeout(500)


def write_discovery(page, label):
    with DISCOVERY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n===== {label} =====\n")
        fh.write(f"URL: {page.url}\n")
        try:
            fh.write(page.locator("body").inner_text(timeout=10000)[:12000])
        except Exception as exc:
            fh.write(f"BODY_ERROR: {exc}\n")


def click_text(page, text):
    candidates = [
        page.get_by_text(text, exact=True),
        page.get_by_text(text).first,
        page.locator(f"text={text}").first,
    ]
    for candidate in candidates:
        try:
            candidate.click(force=True, timeout=5000)
            return True
        except Exception:
            pass
    return False


def main():
    if not STATE_FILE.exists():
        raise SystemExit(f"Estado de login nao encontrado: {STATE_FILE}")

    NETWORK_FILE.unlink(missing_ok=True)
    DISCOVERY_FILE.unlink(missing_ok=True)

    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome)
        context = browser.new_context(
            storage_state=str(STATE_FILE),
            viewport={"width": 1440, "height": 950},
            accept_downloads=True,
        )
        page = context.new_page()
        page.on("response", capture_response)

        page.goto("https://sistema.clinicorp.com/", wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except TimeoutError:
            pass
        page.wait_for_timeout(8000)
        close_overlays(page)
        write_discovery(page, "home")
        page.screenshot(path=str(TMP / "clinicorp_resume_home.png"), full_page=True)

        for label in ["Pacientes", "Agenda", "Relatórios", "Financeiro"]:
            close_overlays(page)
            ok = click_text(page, label)
            page.wait_for_timeout(8000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except TimeoutError:
                pass
            close_overlays(page)
            write_discovery(page, label if ok else f"{label}_click_failed")
            page.screenshot(path=str(TMP / f"clinicorp_resume_{label}.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
