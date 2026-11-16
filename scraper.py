import json
import re
from datetime import datetime
import requests
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_ZONES = {
    "barberini": "Centro", "quattro fontane": "Centro", "farnese": "Campo de' Fiori",
    "fiamma": "Centro", "troisi": "Trastevere", "sacher": "Trastevere",
    "intrastevere": "Trastevere", "reale": "Trastevere", "adriano": "Prati",
    "eden": "Prati", "giulio cesare": "Prati", "azzurro scipioni": "Prati",
    "lux": "Trieste / Salario", "odeon": "Trieste / Salario", "savoy": "Salario",
    "mignon": "Salario", "greenwich": "Testaccio", "eurcine": "EUR",
    "atlantic": "Tuscolana", "madison": "San Paolo", "antares": "Monte Sacro",
    "broadway": "Prenestina", "tibur": "San Lorenzo", "andromeda": "Termini",
    "caravaggio": "Parioli", "maestoso": "Appia", "parco de' medici": "Magliana",
    "moderno": "Repubblica", "porta di roma": "Bufalotta", "roma est": "Lunghezza"
}

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

POSTER_CACHE = {}

def fetch_hd_poster(title: str) -> str:
    """Recupera la locandina HD ufficiale tramite iTunes Search API (gratuita, no API key)."""
    if title in POSTER_CACHE:
        return POSTER_CACHE[title]
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": title, "media": "movie", "country": "it", "limit": 1},
            timeout=6
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                art = results[0].get("artworkUrl100", "")
                if art:
                    hd_art = art.replace("100x100bb", "600x600bb")
                    POSTER_CACHE[title] = hd_art
                    return hd_art
    except Exception:
        pass
    POSTER_CACHE[title] = ""
    return ""

def detect_zone(cinema_name: str) -> str:
    lower = cinema_name.lower()
    for k, z in ROME_ZONES.items():
        if k in lower:
            return z
    return "Roma"

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?\vert{}2D\vert{}3D\vert{}DOLBY ATMOS\vert{}SUB ITA\vert{}VM\d+\vert{}EVENTO)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def extract_today_from_webtic_dom(page) -> list:
    """Estrae solo i film e gli orari del blocco giornaliero (Oggi) dalla scheda."""
    return page.evaluate("""
    () => {
        const results = [];
        const timeRegex = /^([01]?\\d|2[0-3]):[0-5]\\d$/;
        
        const movieBlocks = document.querySelectorAll('[class*="event"], [class*="movie"], [class*="film"], article, .card');
        const seen = new Set();

        movieBlocks.forEach(block => {
            if (block.children.length > 18) return;
            const titleEl = block.querySelector('h1, h2, h3, h4, [class*="title"], [class*="titolo"]');
            if (!titleEl) return;

            const title = (titleEl.innerText || '').trim();
            if (title.length < 2 || title.length > 75 || seen.has(title.toLowerCase())) return;
            if (/webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|crea informatica|provincia|roma|lazio/i.test(title)) return;

            const timeElements = block.querySelectorAll('button, a, span, div');
            const times = [];
            timeElements.forEach(el => {
                if (el.children.length === 0) {
                    const txt = (el.innerText || '').trim();
                    if (timeRegex.test(txt)) {
                        times.push(txt);
                    }
                }
            });

            if (times.length === 0) return;

            let poster = '';
            const img = block.querySelector('img') || (block.parentElement && block.parentElement.
