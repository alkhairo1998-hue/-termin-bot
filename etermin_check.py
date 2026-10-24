"""Prueft die eTermin-Seite der Auslaenderbehoerde Heilbronn und meldet freie Termine per Telegram.

Benoetigte Umgebungsvariablen (GitHub Secrets):
  TELEGRAM_BOT_TOKEN  - Token von BotFather
  TELEGRAM_CHAT_ID    - Deine Chat-ID

Optional:
  SERVICE_TEXT  - Name der Leistung (Standard: Niederlassungserlaubnis)
  THRESHOLD     - Nur melden, wenn ein Termin FRUEHER als dieses Datum liegt (YYYY-MM-DD)
  TEST_MESSAGE  - wenn "1": nur eine Testnachricht senden
"""
import os
import re
import sys
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.etermin.net/qtermin-stadtheilbronn-abh"
SERVICE_TEXT = os.environ.get("SERVICE_TEXT", "Niederlassungserlaubnis")
THRESHOLD = datetime.strptime(os.environ.get("THRESHOLD", "2027-04-15"), "%Y-%m-%d")
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def send(text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"},
        timeout=30,
    )
    r.raise_for_status()


def find_dates(text: str):
    dates = []
    for d, m, y in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        try:
            dates.append(datetime(int(y), int(m), int(d)))
        except ValueError:
            pass
    return sorted(set(dates))


def check() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="de-DE", viewport={"width": 1280, "height": 1600})
        page.goto(URL, wait_until="networkidle", timeout=60000)

        # Cookies akzeptieren
        try:
            page.get_by_text("Alle akzeptieren").first.click(timeout=5000)
        except Exception:
            pass

        # Leistung auswaehlen
        item = page.get_by_text(SERVICE_TEXT, exact=False).first
        item.scroll_into_view_if_needed()
        item.click()
        page.wait_for_timeout(1000)

        # Weiter zur Terminauswahl
        page.get_by_text("Weiter zur Terminauswahl").first.click(timeout=15000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        page.screenshot(path="screenshot.png", full_page=True)
        body = page.inner_text("body")
        with open("page.txt", "w", encoding="utf-8") as f:
            f.write(body)
        browser.close()

    dates = find_dates(body)
    earlier = [d for d in dates if d < THRESHOLD]
    if earlier:
        first = earlier[0].strftime("%d.%m.%Y")
        send(f"Freier Termin gefunden: {first}\n{URL}")
        print("Benachrichtigung gesendet:", first)
    else:
        print("Nichts Neues. Gefundene Daten:", [d.strftime("%d.%m.%Y") for d in dates])


if __name__ == "__main__":
    if os.environ.get("TEST_MESSAGE") == "1":
        send("Test: Der Termin-Bot funktioniert.")
        sys.exit(0)
    check()
