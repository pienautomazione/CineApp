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
    "moderno": "Repubblica", "porta di roma": "Bufalotta", "roma est": "Lunghezza",
    "romaest": "Lunghezza", "maximo": "Laurentina", "cineferonia": "Fiano Romano",
    "doria": "Prati", "trianon": "Appio"
}

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

POSTER_CACHE = {}

JS_GET_CINEMA_CARDS = r"""
() => {
    const names = [];
    const seen = new Set();
    const ignore = /^(salta al|eventi|locali|magazine|chi siamo|privacy|scegli il locale|cerca eventi|provincia|roma|tutta italia|crea informatica|accedi|carrello|tutti|oggi|cookie|\d+)$/i;

    document.querySelectorAll('h1, h2, h3, h4, h5, strong, [class*="title"], [class*="name"]').forEach(el => {
        if (el.children.length > 2) return;
        const txt = (el.innerText || '').trim().split('\n')[0].trim();
        if (txt.length < 4 || txt.length > 50) return;
        if (txt.includes(',') || /\b(via|viale|piazza|corso|largo|piazzale|lido)\b/i.test(txt)) return;
        if (ignore.test(txt) || /crea informatica|cookie|privacy/i.test(txt)) return;
        if (!seen.has(txt.toLowerCase())) {
            seen.add(txt.toLowerCase());
            names.push(txt);
        }
    });
    return names;
}
"""

JS_GET_DOM_POSTERS = r"""
() => {
    const posters = [];
    document.querySelectorAll('img').forEach(img => {
        const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
        if (!src || !src.startsWith('http') || /logo|icon|flag|placeholder|avatar|sprite/i.test(src)) return;
        if (img.naturalWidth > 0 && img.naturalWidth < 45) return;

        let box = img.parentElement;
        for (let i = 0; i < 4 && box; i++) {
            const text = (box.innerText || '').trim();
            if (text.length >= 3 && text.length <= 300) {
                posters.push({ text: text.toLowerCase(), src });
                break;
            }
            box = box.parentElement;
        }
    });
    return posters;
}
"""

def dismiss_cookies(page):
    try:
        page.evaluate("""() => {
            document.querySelectorAll('[class*="cookie"], [id*="cookie"], .cdk-overlay-backdrop').forEach(el => el.remove());
        }""")
    except Exception:
        pass

def fetch_hd_poster(title: str) -> str:
    if title in POSTER_CACHE:
        return POSTER_CACHE[title]
    search_term = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", title).strip()

    for country in ["it", "us"]:
        try:
            r = requests.get(
                "https://itunes.apple.com/search",
                params={"term": search_term, "media": "movie", "country": country, "limit": 5},
                timeout=5
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                for item in results:
                    track = (item.get("trackName") or "").lower()
                    if search_term.lower
