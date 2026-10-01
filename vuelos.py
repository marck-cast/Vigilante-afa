"""Vigilante de vuelos: Buenos Aires -> Tokio. Avisa si hay pasajes <= PRECIO_MAX."""
import os
import re
import urllib.request

from playwright.sync_api import sync_playwright

TOPIC = os.environ["NTFY_TOPIC"]
ORIGEN = "EZE"
DESTINO = "TYO"          # Tokio (Narita + Haneda)
PRECIO_MAX = 1600        # en USD
FECHAS = [               # (ida, vuelta) AAAA-MM-DD
    # Abril 2027
    ("2027-04-03", "2027-04-17"),
    ("2027-04-10", "2027-04-24"),
    ("2027-04-14", "2027-04-28"),
    # Octubre - Noviembre 2027
    ("2027-10-08", "2027-10-22"),
    ("2027-10-22", "2027-11-05"),
    ("2027-11-08", "2027-11-22"),
]

ESP = r"[ \t\u00a0]*"
PATRONES = [
    re.compile(r"(?:US\$|USD)" + ESP + r"(\d[\d.,]*)"),
    re.compile(r"(\d[\d.,]*)" + ESP + r"(?:US\$|USD)"),
]


def precios(texto):
    out = []
    for pat in PATRONES:
        for m in pat.findall(texto):
            d = re.sub(r"\D", "", m)
            if d and 300 <= int(d) <= 10000:
                out.append(int(d))
    return out


def avisar(titulo, msg, link, prioridad="urgent"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": titulo, "Priority": prioridad, "Click": link, "Tags": "airplane"},
    )
    urllib.request.urlopen(req, timeout=15)


def url_busqueda(ida, vuelta):
    return (
        "https://www.google.com/travel/flights"
        f"?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{ida}%20through%20{vuelta}"
        "&curr=USD&hl=es"
    )


def main():
    resultados = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale="es-AR", viewport={"width": 1280, "height": 1800}).new_page()
        for ida, vuelta in FECHAS:
            url = url_busqueda(ida, vuelta)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass
                page.wait_for_timeout(8000)
                texto = page.inner_text("body")
            except Exception as e:
                print(f"{ida} -> {vuelta}: error al cargar: {e}")
                continue

            lista = precios(texto)
            print(f"{ida} -> {vuelta}: {len(texto)} caracteres, precios encontrados: {sorted(set(lista))[:8]}")
            if lista:
                resultados.append((min(lista), ida, vuelta, url))
            else:
                lineas = [l.strip() for l in texto.splitlines() if l.strip()]
                print("   Sin precios. Primeras lineas:", lineas[:15])
        browser.close()

    if not resultados:
        print("No pude leer ningun precio (bloqueo, captcha, fechas todavia no a la venta o cambio de diseno).")
        return

    resultados.sort()
    print("Resumen (precio minimo por fechas):")
    for precio, ida, vuelta, _ in resultados:
        print(f"   USD {precio}  {ida} -> {vuelta}")

    baratos = [r for r in resultados if r[0] <= PRECIO_MAX]
    if baratos:
        detalle = "\n".join(f"USD {pr}: ida {i}, vuelta {v}" for pr, i, v, _ in baratos)
        avisar(
            f"Vuelo a Japon desde USD {baratos[0][0]}",
            f"Buenos Aires - Tokio, pasajes de USD {PRECIO_MAX} o menos:\n{detalle}",
            baratos[0][3],
        )
    else:
        print(f"Ninguno llega a USD {PRECIO_MAX} todavia.")


if __name__ == "__main__":
    main()
