"""Prueft die eTermin-Seite der Auslaenderbehoerde Heilbronn.

Umgebungsvariablen (GitHub Secrets):
  TELEGRAM_BOT_TOKEN  - Token von BotFather
  TELEGRAM_CHAT_ID    - Deine Chat-ID

Optional:
  SERVICE_TEXT  - Name der Leistung (Standard: Niederlassungserlaubnis)
  THRESHOLD     - Nur melden, wenn ein Termin VOR diesem Datum frei ist (TT.MM.JJJJ)
  TEST_MESSAGE  - wenn "1": nur eine Testnachricht senden
"""
import os
import re
import sys
from datetime import date, datetime

import requests
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

URL = "https://www.etermin.net/qtermin-stadtheilbronn-abh"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SERVICE_TEXT = os.environ.get("SERVICE_TEXT") or "Niederlassungserlaubnis"
THRESHOLD = os.environ.get("THRESHOLD") or "15.04.2027"
TEST_MESSAGE = os.environ.get("TEST_MESSAGE") == "1"
BUTTON_TEXT = "Weiter zur Terminauswahl"


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=30,
    )
    print("Telegram:", r.status_code)
    r.raise_for_status()


def accept_cookies(page):
    pattern = re.compile(
        r"^(Alle akzeptieren|Akzeptieren|Zustimmen|Einverstanden|Verstanden|OK)$", re.I
    )
    try:
        page.get_by_role("button", name=pattern).first.click(timeout=3000)
        print("Cookie-Hinweis geschlossen")
        page.wait_for_timeout(1000)
    except Exception:
        pass


def weiter_button(page):
    return page.locator("button:visible", has_text=BUTTON_TEXT).first


def button_ready(page, wait_ms=2500):
    try:
        weiter_button(page).wait_for(state="visible", timeout=wait_ms)
        return True
    except PWTimeout:
        return False


def try_dropdown(page):
    for sel in page.locator("select:visible").all():
        for opt in sel.locator("option").all():
            t = opt.inner_text().strip()
            if SERVICE_TEXT.lower() in t.lower():
                sel.select_option(label=t)
                return
    raise RuntimeError("kein passendes Dropdown")


def get_label_and_row(page):
    label = page.get_by_text(SERVICE_TEXT).first
    label.wait_for(state="visible", timeout=15000)
    label.scroll_into_view_if_needed()
    row = label.locator(
        "xpath=ancestor::*[.//button[not(@id='bp1')] or .//input or .//select][1]"
    )
    return label, row


def select_service(page):
    if button_ready(page, 1500):
        print("Button schon sichtbar")
        return

    def plus():
        _, row = get_label_and_row(page)
        row.locator("button:visible").last.click(timeout=3000)

    def checkbox():
        _, row = get_label_and_row(page)
        row.locator("input[type=checkbox]").first.check(timeout=3000, force=True)

    def row_dropdown():
        _, row = get_label_and_row(page)
        row.locator("select").first.select_option(index=1, timeout=3000)

    def text_click():
        label, _ = get_label_and_row(page)
        label.click(timeout=3000)

    attempts = [
        ("Dropdown", lambda: try_dropdown(page)),
        ("Plus-Button", plus),
        ("Checkbox", checkbox),
        ("Zeilen-Dropdown", row_dropdown),
        ("Text-Klick", text_click),
    ]
    for name, fn in attempts:
        try:
            fn()
        except Exception as e:
            print(f"Versuch '{name}' fehlgeschlagen: {str(e)[:120]}")
            continue
        if button_ready(page):
            print(f"Leistung gewaehlt mit: {name}")
            return
        print(f"Versuch '{name}' ohne Wirkung")
    raise RuntimeError("Button erscheint nicht - Leistung konnte nicht gewaehlt werden")


def find_dates(text):
    today = date.today()
    found = set()
    for d, m, y in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        try:
            dt = date(int(y), int(m), int(d))
        except ValueError:
            continue
        if dt >= today:
            found.add(dt)
    return sorted(found)


def main():
    if TEST_MESSAGE:
        send_telegram("Testnachricht vom Termin-Bot: Verbindung funktioniert.")
        return 0

    limit = datetime.strptime(THRESHOLD, "%d.%m.%Y").date()
    exit_code = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1280, "height": 1600},
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            accept_cookies(page)
            select_service(page)
            weiter_button(page).click(timeout=15000)
            page.wait_for_timeout(5000)

            text = page.inner_text("body")
            print("---- Seitentext ----")
            print(text[:1500])
            print("--------------------")

            dates = find_dates(text)
            if not dates:
                print("Keine Termine gefunden")
            else:
                earliest = dates[0]
                print("Frueheste Daten:", [d.strftime("%d.%m.%Y") for d in dates[:5]])
                if earliest < limit:
                    send_telegram(
                        f"Termin frei! Frueheste Termin: {earliest.strftime('%d.%m.%Y')}\n{URL}"
                    )
                else:
                    print(f"Frueheste {earliest} nicht vor {limit} - keine Meldung")
        except Exception as e:
            print("FEHLER:", repr(e)[:500])
            try:
                print(page.inner_text("body")[:2000])
            except Exception:
                pass
            exit_code = 1
        finally:
            try:
                page.screenshot(path="screenshot.png", full_page=True)
            except Exception:
                pass
            browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

