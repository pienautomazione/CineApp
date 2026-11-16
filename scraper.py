import json
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# URL della programmazione giornaliera dei cinema di Roma
SOURCE_URL = "https://www.comingsoon.it/cinema/roma/"
OUTPUT_FILE = "movies.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "it-IT,it;q=0.9"
}

# Mappa rapida dei quartieri per le principali sale di Roma (arricchibile nel tempo)
ROME_ZONES = {
    "barberini": "Centro",
    "quattro fontane": "Centro",
    "farnese": "Campo de' Fiori",
    "troisi": "Trastevere",
    "nuovo sacher": "Trastevere",
    "intrastevere": "Trastevere",
    "adriano": "Prati",
    "eden": "Prati",
    "giulio cesare": "Prati",
    "parco de' medici": "Magliana",
    "porta di roma": "Bufalotta",
    "roma est": "Lunghezza",
    "lux": "Trieste / Salario",
    "odeo": "Trieste / Salario",
    "tibur": "San Lorenzo",
    "greenwich": "Testaccio",
    "eurcine": "EUR",
    "atlantic": "Tuscolana",
    "madison": "San Paolo"
}

# Palette gradienti di riserva se manca la locandina
GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

def detect_zone(cinema_name: str) -> str:
    lower_name = cinema_name.lower()
    for key, zone in ROME_ZONES.items():
        if key in lower_name:
            return zone
    return "Roma"

def extract_times(text_block: str) -> list:
    # Trova tutti gli orari nel formato HH:MM (es. 16:30, 21:15)
    found = re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text_block)
    # Ricostruisce l'orario completo e rimuove duplicati mantenendo l'ordine
    full_times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text_block)
    return list(dict.fromkeys(full_times))

def scrape_rome_cinemas():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio raccolta dati per Roma...")
    
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    movies_dict = {}
    movie_counter = 1

    # Cerca i blocchi cinema nella pagina di programmazione
    cinema_blocks = soup.select(".box-cinema, .cinema-item, article")

    for block in cinema_blocks:
        cinema_el = block.select_one("h2, h3, .titolo-cinema, a[href*='/cinema/']")
        if not cinema_el:
            continue
        
        cinema_name = cinema_el.get_text(strip=True)
        if not cinema_name or len(cinema_name) < 3:
            continue

        zone = detect_zone(cinema_name)

        # Cerca i film programmatti dentro questo cinema
        film_rows = block.select(".film-row, .programmazione-film, li, .box-film")
        for row in film_rows:
            title_el = row.select_one("a[href*='/film/'], .titolo-film, strong")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # Estrae orari e eventuale link diretto alla biglietteria
            times = extract_times(row.get_text(" ", strip=True))
            if not times:
                continue

            ticket_link_el = row.select_one("a[href*='bigliett'], a[href*='webtic'], a[href*='ticket']")
            booking_url = ticket_link_el["href"] if ticket_link_el and ticket_link_el.has_attr("href") else f"https://www.google.com/search?q=biglietti+{requests.utils.quote(title + ' ' + cinema_name + ' Roma')}"

            # Estrae locandina se presente
            img_el = row.select_one("img")
            poster_url = ""
            if img_el:
                poster_url = img_el.get("data-src") or img_el.get("src") or ""

            # Aggrega per titolo film
            if title not in movies_dict:
                grad, acc = GRADIENTS[(movie_counter - 1) % len(GRADIENTS)]
                movies_dict[title] = {
                    "id": movie_counter,
                    "title": title,
                    "genre": "In Sala",
                    "duration": "Programmazione odierna",
                    "rating": "★",
                    "posterUrl": poster_url if poster_url.startswith("http") else "",
                    "gradient": grad,
                    "accent": acc,
                    "tag": "ROMA",
                    "synopsis": f"Proiezione programmata oggi nelle sale di Roma. Tocca un orario per accedere alla biglietteria del cinema selezionato.",
                    "screenings": []
                }
                movie_counter += 1

            # Aggiunge la sala all'elenco del film
            movies_dict[title]["screenings"].append({
                "city": "Roma",
                "cinema": cinema_name,
                "zone": zone,
                "times": times,
                "bookingUrl": booking_url
            })

    movies_list = list(movies_dict.values())

    # Controllo di sicurezza: salva solo se ha trovato almeno 1 film valido
    if len(movies_list) == 0:
        print("⚠️ Nessun dato estratto (possibile cambio layout HTML). Mantengo il file precedente.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(movies_list, f, ensure_ascii=False, indent=2)

    print(f"✅ Salvati {len(movies_list)} film aggiornati in '{OUTPUT_FILE}'.")

if __name__ == "__main__":
    scrape_rome_cinemas()
