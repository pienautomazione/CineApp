import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

OUTPUT_FILE = "movies.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "it-IT,it;q=0.9"
}

# Elenco delle principali sale di Roma con sito diretto / Webtic
ROME_CINEMAS = [
    {"name": "Cinema Barberini", "zone": "Centro", "url": "https://www.cinemabarberini.it/", "webtic_id": "5191"},
    {"name": "Cinema Quattro Fontane", "zone": "Centro", "url": "https://www.circuitocinema.com/cinema/quattro-fontane/", "webtic_id": "5195"},
    {"name": "Cinema Adriano", "zone": "Prati", "url": "https://www.circuitocinema.com/cinema/adriano/", "webtic_id": "5188"},
    {"name": "Cinema Giulio Cesare", "zone": "Prati", "url": "https://www.circuitocinema.com/cinema/giulio-cesare/", "webtic_id": "5193"},
    {"name": "Cinema Troisi", "zone": "Trastevere", "url": "https://cinematroisi.it/programmazione/", "webtic_id": "5487"},
    {"name": "Nuovo Sacher", "zone": "Trastevere", "url": "https://www.sacherfilm.eu/", "webtic_id": "5201"},
    {"name": "Cinema Eurcine", "zone": "EUR", "url": "https://www.circuitocinema.com/cinema/eurcine/", "webtic_id": "5192"},
    {"name": "Cinema Lux", "zone": "Trieste / Salario", "url": "https://www.circuitocinema.com/cinema/lux/", "webtic_id": "5194"},
    {"name": "Cinema Odeon", "zone": "Trieste / Salario", "url": "https://www.circuitocinema.com/cinema/odeon/", "webtic_id": "5196"},
    {"name": "Cinema Greenwich", "zone": "Testaccio", "url": "https://www.cinemagreenwich.it/", "webtic_id": "5197"},
    {"name": "Cinema Madison", "zone": "San Paolo", "url": "https://www.cinemamadison.it/", "webtic_id": "5198"},
    {"name": "Cinema Farnese", "zone": "Campo de' Fiori", "url": "https://www.cinemafarnese.it/", "webtic_id": "5202"}
]

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

def normalize_title(raw: str) -> str:
    # Rimuove suffissi tecnici tipo "(V.O.S.)", "[2D]", "3D" per raggruppare lo stesso film tra sale diverse
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def extract_times(text: str) -> list:
    times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
    return list(dict.fromkeys(times))

def fetch_webtic_api(local_id: str) -> list:
    """Interroga direttamente l'endpoint JSON di Webtic per il singolo cinema."""
    api_url = f"https://www.webtic.it/api/v1/events?localId={local_id}"
    results = []
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=12)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/json"):
            data = r.json()
            events = data if isinstance(data, list) else data.get("events", data.get("data", []))
            for ev in events:
                title = ev.get("title") or ev.get("name") or ""
                shows = ev.get("performances") or ev.get("shows") or ev.get("times") or []
                times = []
                for sh in shows:
                    if isinstance(sh, str):
                        times.extend(extract_times(sh))
                    elif isinstance(sh, dict):
                        t_str = sh.get("time") or sh.get("startDate") or ""
                        times.extend(extract_times(str(t_str)))
                if title and times:
                    results.append({
                        "title": title,
                        "times": list(dict.fromkeys(times)),
                        "poster": ev.get("poster") or ev.get("image") or "",
                        "synopsis": ev.get("description") or ev.get("synopsis") or "",
                        "booking_url": f"https://www.webtic.it/#/shopping?action=loadLocal&localId={local_id}"
                    })
    except Exception:
        pass
    return results

def fetch_direct_site(cinema: dict) -> list:
    """Legge la pagina programmazione ufficiale del cinema se l'API JSON non risponde."""
    results = []
    try:
        r = requests.get(cinema["url"], headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return results
        soup = BeautifulSoup(r.text, "html.parser")

        # Cerca contenitori che contengono sia un titolo (h2/h3/h4) sia degli orari HH:MM
        for card in soup.select("article, .film, .movie, .programma, .event, .scheda-film, .item"):
            title_el = card.select_one("h2, h3, h4, .title, .titolo")
            if not title_el:
                continue
            raw_title = title_el.get_text(" ", strip=True)
            if len(raw_title) < 2 or len(raw_title) > 90:
                continue

            times = extract_times(card.get_text(" ", strip=True))
            if not times:
                continue

            link_el = card.select_one("a[href*='webtic'], a[href*='bigliett'], a[href*='ticket'], a[href*='acquista']")
            booking_url = link_el["href"] if link_el and link_el.has_attr("href") else f"https://www.webtic.it/#/shopping?action=loadLocal&localId={cinema['webtic_id']}"

            img_el = card.select_one("img")
            poster = ""
            if img_el:
                poster = img_el.get("data-src") or img_el.get("src") or ""
                if poster.startswith("/"):
                    from urllib.parse import urljoin
                    poster = urljoin(cinema["url"], poster)

            results.append({
                "title": raw_title,
                "times": times,
                "poster": poster,
                "synopsis": "",
                "booking_url": booking_url
            })
    except Exception as e:
        print(f"  Errore su {cinema['name']}: {e}")
    return results

def scrape_rome_cinemas():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Raccolta diretta dalle sale di Roma...")
    movies_dict = {}
    counter = 1

    for cinema in ROME_CINEMAS:
        print(f"→ Controllo {cinema['name']}...")
        items = fetch_webtic_api(cinema["webtic_id"])
        if not items:
            items = fetch_direct_site(cinema)

        print(f"  Trovati {len(items)} film in programmazione.")

        for item in items:
            norm_title = normalize_title(item["title"])
            if not norm_title:
                continue

            if norm_title not in movies_dict:
                grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
                movies_dict[norm_title] = {
                    "id": counter,
                    "title": norm_title,
                    "genre": "In Sala · Roma",
                    "duration": "Programmazione odierna",
                    "rating": "★",
                    "posterUrl": item["poster"] if item["poster"].startswith("http") else "",
                    "gradient": grad,
                    "accent": acc,
                    "tag": "ROMA",
                    "synopsis": item["synopsis"] or "Proiezione ufficiale in programma oggi. Tocca un orario per andare direttamente alla biglietteria della sala.",
                    "screenings": []
                }
                counter += 1
            elif not movies_dict[norm_title]["posterUrl"] and item["poster"].startswith("http"):
                movies_dict[norm_title]["posterUrl"] = item["poster"]

            if not any(s["cinema"] == cinema["name"] for s in movies_dict[norm_title]["screenings"]):
                movies_dict[norm_title]["screenings"].append({
                    "city": "Roma",
                    "cinema": cinema["name"],
                    "zone": cinema["zone"],
                    "times": item["times"],
                    "bookingUrl": item["booking_url"]
                })

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("⚠️ Nessun dato estratto in questo giro.")

if __name__ == "__main__":
    scrape_rome_cinemas()
