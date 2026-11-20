import json, re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ZONES = {
    "barberini": "Centro", "quattro fontane": "Centro", "farnese": "Campo de' Fiori",
    "fiamma": "Centro", "troisi": "Trastevere", "sacher": "Trastevere",
    "intrastevere": "Trastevere", "reale": "Trastevere", "adriano": "Prati",
    "eden": "Prati", "giulio cesare": "Prati", "azzurro scipioni": "Prati",
    "lux": "Trieste / Salario", "odeon": "Trieste / Salario", "savoy": "Salario",
    "mignon": "Salario", "greenwich": "Testaccio", "eurcine": "EUR",
    "atlantic": "Tuscolana", "madison": "San Paolo", "antares": "Monte Sacro",
    "broadway": "Prenestina", "tibur": "San Lorenzo", "andromeda": "Termini",
    "caravaggio": "Parioli", "maestoso": "Appia", "parco de' medici": "Magliana",
    "moderno": "Repubblica", "porta di roma": "Bufalotta", "roma est": "Lunghezza",
    "romaest": "Lunghezza", "maximo": "Laurentina", "cineferonia": "Fiano Romano",
    "doria": "Prati", "trianon": "Appio"
}

GRADS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300")
]

def norm_cinema(raw):
    n = re.sub(r"\s*[-–|]?\s*Roma$", "", raw, flags=re.I).strip()
    n = re.sub(r"^(?:Multisala|Nuovo\s+Cinema|Cinema)\s+", "", n, flags=re.I).strip()
    return "Cineferonia" if ("cineferonia" in n.lower() or "fiano" in n.lower()) else (n.title() or raw.strip())

def get_zone(c):
    return next((z for k, z in ZONES.items() if k in c.lower()), "Roma")

def is_ov(raw):
    return bool(re.search(r"(?:\bO\.?V\.?\b|\bV\.?O\.?S?\.?\b|SUB\s*ITA|VERSIONE\s*ORIGINALE)", raw, re.I))

def norm_title(raw):
    c = re.sub(r"^\s*[\(\[](?:O\.?V\.?\vert{}V\.?O\.?S?\.?\vert{}2D\vert{}3D\vert{}EVENTO\vert{}SUB\s*ITA)[\)\]]\s*", "", raw, flags=re.I)
    c = re.sub(r"\s*[\(\[](?:O\.?V\.?\vert{}V\.?O\.?S?\.?\vert{}2D\vert{}3D\vert{}DOLBY ATMOS\vert{}SUB\s*ITA\vert{}VM\d+\vert{}EVENTO\vert{}\bIT\b)[\)\]]", "", c, flags=re.I) c = re.sub(r"\b(?:O\.?V\.?\vert{}V\.?O\.?S?\.?\vert{}SUB\s*ITA)\b\s*$", "", c, flags=re.I) return " ".join(re.sub(r"^[\(\)\[\]\-\–\:\.\s]+", "", c).split()).strip().title()

def find_img(obj):
    raw = json.dumps(obj)
    m = re.search(r"https?://[^\"'\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\s]*)?", raw, re.I)
    if m and not re.search(r"logo|icon|flag|placeholder|avatar|sprite", m.group(0), re.I):
        return m.group(0)
    r = re.search(r"\"(/[^\"'\s]+\.(?:jpg|jpeg|png|webp))\"", raw, re.I)
    return f"https://www.webtic.it{r.group(1)}" if (r and not re.search(r"logo|icon|flag|placeholder|avatar|sprite", r.group(1), re.I)) else ""

def parse_json(data, today, base_url, out):
    if isinstance(data, dict):
        t = next((data[k].strip() for k in ["Title","title","EventName","eventName","MovieTitle","movieTitle","Descrizione","descrizione"] if isinstance(data.get(k), str) and 2 <= len(data[k].strip()) <= 80), "")
        if t:
            times = re.findall(rf"{today}[T\s]+([12]\d):([0-5][05])", json.dumps(data))
            if times:
                out.append({"raw": t, "poster": find_img(data), "url": base_url, "st": [{"time": f"{h}:{m}", "url": base_url} for h, m in sorted(set(times))]})
        for v in data.values():
            parse_json(v, today, base_url, out)
    elif isinstance(data, list):
        for i in data:
            parse_json(i, today, base_url, out)

def run():
    today = datetime.now().strftime("%Y-%m-%d")
    movies, idx = {}, 1
    excl = ["santa marinella","civitavecchia","velletri","tivoli","frascati","albano","anzio
