"""Chequeo único: busca 'Benin' en AFA Tickets y avisa al celular por ntfy.sh"""
import os
import sys
import unicodedata
import urllib.request

from playwright.sync_api import sync_playwright

URL = "https://shop.afatickets.com.ar/content?lang=es"
TOPIC = os.environ["NTFY_TOPIC"]


def norm(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def avisar(titulo, msg, prioridad="urgent"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": titulo, "Priority": prioridad, "Click": URL, "Tags": "soccer,tickets"},
    )
    urllib.request.urlopen(req, timeout=15)


def main():
    if "--test" in sys.argv:
        avisar("Prueba", "Si ves esto, las notificaciones funcionan.", "default")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale="es-AR").new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        texto = page.inner_text("body")
        browser.close()

    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    print("Líneas leídas de la página:", len(lineas))
    for i, l in enumerate(lineas):
        if "benin" in norm(l):
            ctx = lineas[max(0, i - 3): i + 5]
            agotado = any(a in norm(" ".join(ctx)) for a in ("agotado", "sold out", "no disponible"))
            print("Encontrado:", ctx, "| agotado:", agotado)
            if not agotado:
                avisar("ENTRADAS ARGENTINA vs BENIN", "Apareció el partido en AFA Tickets. Entrá ya!\n" + " | ".join(ctx))
            return
    print("Todavía no aparece Benin.")


if __name__ == "__main__":
    main()
