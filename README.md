import os
import re
import sys
from datetime import date

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.etermin.net/qtermin-stadtheilbronn-abh"
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
THRESHOLD = date.fromisoformat(os.getenv("THRESHOLD", "2027-04-15"))
SERVICE = os.getenv("SERVICE", "Beantragung Niederlassungserlaubnis")
MONTHS_TO_SCAN = 8

MONTHS = {m: i + 1 for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
     "september", "oktober", "november", "dezember"])}

JS_DAYS = """
() => {
  const out = [];
  document.querySelectorAll('td, div, span, a, button').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!/^\\d{1,2}$/.test(t) || el.children.length > 0) return;
    let node = el, bg = null;
    for (let i = 0; i < 3 && node; i++, node = node.parentElement) {
      const c = getComputedStyle(node).backgroundColor;
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') { bg = c; break; }
    }
    if (!bg) return;
    const m = bg.match(/\\d+(\\.\\d+)?/g);
    if (!m) return;
    const [r, g, b] = m.slice(0, 3).map(Number);
    const green = g > 140 && g > r + 20 && g > b + 20;
    const red = r > 200 && g < 110 && b < 110;
    if (green || red) out.push({day: parseInt(t, 10), kind: green ? 'green' : 'red'});
  });
  return out;
}
"""


def telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20,
    ).raise_for_status()


def current_month(page):
    txt = page.evaluate("() => document.body.innerText").lower()
    for m in re.finditer(r"(januar|februar|märz|april|mai|juni|juli|august|"
                         r"september|oktober|november|dezember)\s+(20\d\d)", txt):
        return int(m.group(2)), MONTHS[m.group(1)]
    sel = page.evaluate("""() => {
        const s = [...document.querySelectorAll('select')].map(e => e.selectedOptions[0]?.text || '');
        return s.join(' ');
    }""").lower()
    mm = next((MONTHS[k] for k in MONTHS if k in sel), None)
    yy = re.search(r"20\d\d", sel) or re.search(r"20\d\d", txt)
    if mm and yy:
        return int(yy.group(0)), mm
    raise RuntimeError("Monat/Jahr im Kalender nicht gefunden")


def main():
    found = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 430, "height": 1400}, locale="de-DE")
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)

            for label in ("Alle akzeptieren", "Auswahl bestätigen"):
                btn = page.get_by_text(label, exact=True)
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    break

            page.get_by_text(SERVICE, exact=False).first.click()
            page.get_by_text("Weiter zur Terminauswahl", exact=False).first.click()
            page.wait_for_timeout(3000)

            for _ in range(MONTHS_TO_SCAN):
                year, month = current_month(page)
                for d in page.evaluate(JS_DAYS):
                    try:
                        found.append(date(year, month, d["day"]))
                    except ValueError:
                        pass
                if found:
                    break
                nxt = page.locator("[class*=next], [aria-label*=ächst], .fa-chevron-right, "
                                   ".ui-datepicker-next").first
                nxt.click()
                page.wait_for_timeout(1500)
        except Exception:
            page.screenshot(path="debug.png", full_page=True)
            open("debug.html", "w", encoding="utf-8").write(page.content())
            raise
        finally:
            browser.close()

    if not found:
        print("Keine freien Tage gefunden.")
        return
    earliest = min(found)
    print(f"Frühester freier Tag: {earliest}")
    if earliest < THRESHOLD:
        telegram(f"🚨 Früherer Termin frei: {earliest:%d.%m.%Y}!\n"
                 f"(Bisher frühestens {THRESHOLD:%d.%m.%Y})\n{URL}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)
