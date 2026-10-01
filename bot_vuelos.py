"""Bot de vuelos: recibe una consulta desde Telegram, busca en Google Flights y responde."""
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
PERMITIDO = os.environ.get("ALLOWED_CHAT_ID", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
TEXTO = os.environ.get("TEXTO", "").strip()

ESP = r"[ \t\u00a0]*"
PATRONES = [
    re.compile(r"(?:US\$|USD)" + ESP + r"(\d[\d.,]*)"),
    re.compile(r"(\d[\d.,]*)" + ESP + r"(?:US\$|USD)"),
]
RE_FECHA = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})")


def norm(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def responder(texto):
    """Envia un mensaje a Telegram (partido en trozos si es largo)."""
    for i in range(0, len(texto), 3900):
        data = json.dumps({
            "chat_id": CHAT_ID,
            "text": texto[i:i + 3900],
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=20)


def a_iso(s):
    s = s.strip()
    if "/" in s:
        d, m, a = s.split("/")
        return datetime(int(a), int(m), int(d)).strftime("%Y-%m-%d")
    return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")


AYUDA = (
    "Para buscar escribi (ida y vuelta):\n"
    "/vuelo EZE MAD 2027-05-10 2027-05-24\n"
    "/vuelo AEP a Tokyo 10/04/2027 24/04/2027\n"
    "/vuelo EZE - New York 2027-06-01 2027-06-15\n\n"
    "Primero el aeropuerto de salida (EZE = Ezeiza, AEP = Aeroparque), "
    "despues el destino y al final las dos fechas.\n"
    "Con /crudo en vez de /vuelo te muestro el texto que lee Google (para ajustar el formato)."
)

SEPARADOR = re.compile(r"\s+(?:a|hasta|->|>|-)\s+", re.I)


def separar_ruta(ruta):
    """'EZE MAD' / 'EZE-MAD' / 'EZE a Tokyo' -> (origen, destino). Lanza ValueError si falta algo."""
    ruta = ruta.strip(" ,")
    m = re.match(r"^([A-Za-z]{3})\s*[-/>\s]\s*([A-Za-z]{3})$", ruta)
    if m:
        return m.group(1).upper(), m.group(2).upper()
    partes = SEPARADOR.split(ruta, maxsplit=1)
    if len(partes) == 2 and partes[0].strip() and partes[1].strip():
        o, d = partes[0].strip(), partes[1].strip()
        if len(o) == 3 and o.isalpha():
            o = o.upper()
        if len(d) == 3 and d.isalpha():
            d = d.upper()
        return o, d
    raise ValueError(
        "Tenes que decirme desde que aeropuerto salis y a donde vas, antes de las fechas.\n\n" + AYUDA
    )


def parsear(texto):
    """Devuelve (comando, origen, destino, ida, vuelta) o lanza ValueError con el motivo."""
    m = re.match(r"^/(\w+)(?:@\w+)?\s*(.*)$", texto, re.S)
    if not m:
        raise ValueError(AYUDA)
    comando, resto = m.group(1).lower(), m.group(2).strip()
    fechas = list(RE_FECHA.finditer(resto))
    if len(fechas) < 2:
        raise ValueError("Necesito la ruta y dos fechas (ida y vuelta).\n\n" + AYUDA)
    origen, destino = separar_ruta(resto[:fechas[0].start()])
    if norm(origen) == norm(destino):
        raise ValueError("El origen y el destino son iguales.")
    try:
        ida, vuelta = a_iso(fechas[0].group(1)), a_iso(fechas[1].group(1))
    except ValueError:
        raise ValueError("Alguna fecha no es valida.\n\n" + AYUDA)
    if vuelta <= ida:
        raise ValueError("La vuelta tiene que ser despues de la ida.")
    if ida < date.today().isoformat():
        raise ValueError("La fecha de ida ya paso.")
    return comando, origen, destino, ida, vuelta


def url_busqueda(origen, destino, ida, vuelta):
    q = f"Flights to {destino} from {origen} on {ida} through {vuelta}"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q) + "&curr=USD&hl=es"


def precio_de_linea(linea):
    vals = []
    for pat in PATRONES:
        for m in pat.findall(linea):
            d = re.sub(r"\D", "", m)
            if d and 40 <= int(d) <= 30000:
                vals.append(int(d))
    return min(vals) if vals else None


RE_HORA = re.compile(r"^(\d{1,2}:\d{2})(?:\s?[AaPp]\.?\s?[Mm]\.?)?(\+\d)?$")
RE_DUR = re.compile(r"^(?:\d+\s?h(?:\s?\d+\s?min)?|\d+\s?min)$")
RE_RUTA = re.compile(r"^[A-Z]{3}\s?[–-]\s?[A-Z]{3}$")
RE_CODIGOS = re.compile(r"^[A-Z]{3}(?:,\s?[A-Z]{3})*$")
RE_ESCALA_DET = re.compile(r"^((?:\d+\s?h(?:\s?\d+\s?min)?|\d+\s?min))\s+([A-Z]{3}(?:,\s?[A-Z]{3})*)$")


def extraer(lineas):
    """Cada linea con precio cierra un 'bloque': las lineas anteriores son sus detalles."""
    items, previo = [], -1
    for i, l in enumerate(lineas):
        p = precio_de_linea(l)
        if p is None:
            continue
        bloque = [x for x in lineas[previo + 1:i] if len(x) <= 120][-25:]
        previo = i
        items.append((p, bloque))
    return items


def minutos(dur):
    h = re.search(r"(\d+)\s?h", dur)
    m = re.search(r"(\d+)\s?min", dur)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def detalles(bloque):
    d = {"horas": [], "aerolinea": "", "operado": "", "duracion": "", "ruta": "",
         "escalas": "", "paradas": "", "co2": "", "emis": ""}
    ultima_hora = -1
    for i, l in enumerate(bloque):
        n = norm(l)
        if RE_HORA.match(l):
            d["horas"].append(l)
            ultima_hora = i
        elif RE_RUTA.match(l):
            d["ruta"] = l.replace(" ", "")
        elif RE_DUR.match(l):
            if not d["duracion"]:
                d["duracion"] = l
        elif "escala" in n and len(l) <= 20:
            if not d["escalas"]:
                d["escalas"] = l
                if i + 1 < len(bloque):
                    sig = bloque[i + 1]
                    mo = RE_ESCALA_DET.match(sig)
                    if mo:
                        d["paradas"] = f"{mo.group(1)} en {mo.group(2)}"
                    elif RE_CODIGOS.match(sig):
                        d["paradas"] = sig
        elif "kg co2" in n:
            d["co2"] = l
        elif "emisiones" in n:
            d["emis"] = l
    # aerolinea: la linea que sigue al ultimo horario
    if ultima_hora >= 0 and ultima_hora + 1 < len(bloque):
        cand = bloque[ultima_hora + 1]
        if not (RE_RUTA.match(cand) or RE_DUR.match(cand) or RE_HORA.match(cand)
                or "escala" in norm(cand) or "kg co2" in norm(cand)) and len(cand) <= 90:
            partes = re.split(r"\s*(?=Operado por)", cand, maxsplit=1)
            d["aerolinea"] = partes[0].strip()
            if len(partes) > 1:
                d["operado"] = partes[1].strip()
    return d


def es_vuelo(d):
    return bool(d["ruta"] or d["escalas"] or d["duracion"])


def armar_vuelos(items):
    vuelos, vistos = [], set()
    for p, b in sorted(items, key=lambda t: t[0]):
        d = detalles(b)
        if not es_vuelo(d):
            continue
        d["precio"] = p
        clave = (p, d["aerolinea"], tuple(d["horas"]), d["ruta"], d["duracion"], d["escalas"])
        if clave in vistos:
            continue
        vistos.add(clave)
        vuelos.append(d)
    return vuelos


def formato_hora(h):
    m = RE_HORA.match(h)
    if not m:
        return h
    base, mas = m.group(1), m.group(2)
    if mas:
        n = int(mas[1:])
        return f"{base} (+{n} {'dia' if n == 1 else 'dias'})"
    return base


def linea_vuelo(n, d):
    precio = f"{d['precio']:,}".replace(",", ".")
    titulo = f"{n}) USD {precio}"
    if d["aerolinea"]:
        titulo += f" · {d['aerolinea']}"
    out = [titulo]
    horario = ""
    if len(d["horas"]) >= 2:
        horario = f"🕒 {formato_hora(d['horas'][0])} → {formato_hora(d['horas'][-1])}"
    elif len(d["horas"]) == 1:
        horario = f"🕒 {formato_hora(d['horas'][0])}"
    if d["duracion"]:
        horario += (" · " if horario else "") + f"⏱ {d['duracion']}"
    if horario:
        out.append("   " + horario)
    ruta = d["ruta"]
    if d["escalas"]:
        esc = d["escalas"] + (f": {d['paradas']}" if d["paradas"] else "")
        ruta = (ruta + " · " if ruta else "") + esc
    if ruta:
        out.append("   🛫 " + ruta)
    if d["co2"]:
        out.append("   🌱 " + d["co2"] + (f" ({d['emis']})" if d["emis"] else ""))
    if d["operado"]:
        out.append("   ℹ️ " + d["operado"])
    return "\n".join(out)


def armar_mensaje(origen, destino, ida, vuelta, url, vuelos, items):
    nombre = destino if len(destino) == 3 else destino.title()
    out = [f"✈️ {origen} → {nombre}", f"📅 Ida {ida} · Vuelta {vuelta}", ""]
    if vuelos:
        for n, d in enumerate(vuelos[:6], 1):
            out.append(linea_vuelo(n, d))
            out.append("")
        con_dur = [d for d in vuelos if d["duracion"]]
        if len(con_dur) > 1:
            r = min(con_dur, key=lambda d: minutos(d["duracion"]))
            precio = f"{r['precio']:,}".replace(",", ".")
            out.append(f"⚡ Mas rapido: {r['duracion']} · USD {precio}" + (f" · {r['aerolinea']}" if r["aerolinea"] else ""))
            out.append("")
    else:
        # no pude ordenar los campos: muestro las lineas tal cual
        vistos = set()
        for n, (p, b) in enumerate(sorted(items, key=lambda t: t[0])[:6], 1):
            clave = (p, " ".join(b))
            if clave in vistos:
                continue
            vistos.add(clave)
            out.append(f"{n}) USD {p:,}".replace(",", "."))
            if b:
                out.append("   " + " · ".join(b[-8:]))
    out += ["🔗 " + url]
    return "\n".join(out)


def leer_pagina(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale="es-AR", viewport={"width": 1280, "height": 1800}).new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(10000)
        texto = page.inner_text("body")
        if "cargando resultados" in norm(texto) and not any(precio_de_linea(l) for l in texto.splitlines()):
            page.wait_for_timeout(12000)
            texto = page.inner_text("body")
        browser.close()
    return [l.strip() for l in texto.splitlines() if l.strip()]


def main():
    if not CHAT_ID or CHAT_ID != PERMITIDO:
        print("Chat no autorizado; no respondo.")
        return
    try:
        comando, origen, destino, ida, vuelta = parsear(TEXTO)
    except ValueError as e:
        responder(str(e))
        return
    if comando not in ("vuelo", "crudo"):
        responder(AYUDA)
        return

    url = url_busqueda(origen, destino, ida, vuelta)
    try:
        lineas = leer_pagina(url)
    except Exception as e:
        responder(f"No pude abrir Google Flights: {e}")
        return
    print("Lineas leidas:", len(lineas))

    if comando == "crudo":
        responder(f"Texto crudo ({len(lineas)} lineas):\n\n" + "\n".join(lineas))
        return

    items = extraer(lineas)
    if not items:
        responder(
            f"No encontre precios para {origen} → {destino} ({ida} / {vuelta}).\n"
            "Puede que esas fechas todavia no esten a la venta, que el destino no se entienda, "
            "o que Google haya bloqueado la consulta.\n" + url
        )
        return
    vuelos = armar_vuelos(items)
    responder(armar_mensaje(origen, destino, ida, vuelta, url, vuelos, items))


if __name__ == "__main__":
    main()
