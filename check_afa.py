"""Vigilante AFA Tickets: avisa cuando el partido contra Benin tenga boton COMPRAR"""
import os
import sys
import unicodedata
import urllib.request

from playwright.sync_api import sync_playwright

URL = "https://shop.afatickets.com.ar/content?lang=es"
TOPIC = os.environ["NTFY_TOPIC"]
RIVAL = "benin"


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


def leer_pagina():
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
    return [l.strip() for l in texto.splitlines() if l.strip()]


def analizar(lineas):
    """Devuelve (estado, bloque). Estados: NO_ENCONTRADO, SIN_VENTA, ESPERA, VENTA"""
    idx = None
    for i, l in enumerate(lineas):
        if RIVAL in norm(l):
            idx = i
            break
    if idx is None:
        return "NO_ENCONTRADO", []

    bloque = [lineas[idx]]
    for l in lineas[idx + 1: idx + 7]:
        if " vs " in norm(l):  # empieza otro partido
            break
        bloque.append(l)
    txt = norm(" ".join(bloque))

    if any(x in txt for x in ("agotado", "sold out", "no disponible")):
        return "SIN_VENTA", bloque
    if "comprar" in txt:
        return "VENTA", bloque
    if "espera" in txt or "waiting" in txt:
        return "ESPERA", bloque
    return "SIN_VENTA", bloque


def main():
    if "--test" in sys.argv:
        avisar("Prueba", "Si ves esto, las notificaciones funcionan.", "default")
        return

    lineas = leer_pagina()
    print("Lineas leidas de la pagina:", len(lineas))
    print("Primeras lineas:", lineas[:40])

    estado, bloque = analizar(lineas)
    print("Estado:", estado, "| Bloque Benin:", bloque)

    if estado == "VENTA":
        avisar("ENTRADAS ARGENTINA vs BENIN", "Aparecio el boton COMPRAR. Entra ya!\n" + " | ".join(bloque))
    elif estado == "ESPERA":
        avisar("Benin: lista de espera", "Aparecio algo de lista de espera. Revisa la pagina.\n" + " | ".join(bloque), "high")
    elif estado == "NO_ENCONTRADO":
        print("No encontre el partido en la pagina (bloqueo, sala de espera o cambio de diseno).")
    else:
        print("Sin venta todavia.")


if __name__ == "__main__":
    main()
