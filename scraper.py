import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

# Siti ufficiali reali verificati
ROME_CINEMAS = [
    {"name": "Cinema Barberini", "zone": "Centro", "url": "https://www.cinemabarberini.it/"},
    {"name": "Cinema Quattro Fontane", "zone": "Centro", "url": "https://www.circuitocinema.com/cinema/quattro-fontane/"},
    {"name": "Cinema Adriano", "zone": "Prati", "url": "https://www.circuitocinema.com/cinema/adriano/"},
    {"name": "Cinema Troisi", "zone": "Trastevere", "url": "https://cinematroisi.it/programmazione/"},
    {"name": "Nuovo Sacher", "zone": "Trastevere", "url": "https://www.sacherfilm.eu/"},
    {"name": "Cinema Greenwich", "zone": "Testaccio", "url": "https://www.greenwichcinema.it/"}
]

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def extract_times(text: str) -> list:
    times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
    return list(dict.fromkeys(times))

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio browser invisibile per Roma...")
    movies_dict = {}
    counter = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        for cinema in ROME_CINEMAS:
            print(f"→ Navigazione su {cinema['name']} ({cinema['url']})...")
            try:
                page.goto(cinema["url"], wait_until="networkidle", timeout=25000)
                page.wait_for_timeout(3000) # Attende 3 secondi per il rendering JS degli orari

                # Estrae i blocchi visibili nella pagina renderizzata
                cards = page.query_selector_all("article, .film, .movie, .programma, .event, .scheda-film, .item, .card")
                found_count = 0

                for card in cards:
                    text_content = card.inner_text()
                    times = extract_times(text_content)
                    if not times:
                        continue

                    # Cerca il titolo all'interno della card
                    title_el = card.query_selector("h1, h2, h3, h4, .title, .titolo, strong")
                    if not title_el:
                        continue
                    
                    raw_title = title_el.inner_text().strip()
                    if len(raw_title) < 2 or len(raw_title) > 85:
                        continue

                    # Ignora false corrispondenze (es. menu o orari di apertura biglietteria)
                    if any(w in raw_title.lower() for w in ["biglietteria", "contatti", "dove siamo", "orari", "cookie"]):
                        continue

                    norm_title = normalize_title(raw_title)
                    if not norm_title:
                        continue

                    # Cerca locandina e link biglietti
                    img_el = card.query_selector("img")
                    poster = img_el.get_attribute("src") if img_el else ""
                    if poster and poster.startswith("/"):
                        from urllib.parse import urljoin
                        poster = urljoin(cinema["url"], poster)

                    link_el = card.query_selector("a[href*='webtic'], a[href*='bigliett'], a[href*='ticket'], a[href*='acquista'], a")
                    booking_url = link_el.get_attribute("href") if link_el else cinema["url"]
                    if booking_url and booking_url.startswith("/"):
                        from urllib.parse import urljoin
                        booking_url = urljoin(cinema["url"], booking_url)

                    if norm_title not in movies_dict:
                        grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
                        movies_dict[norm_title] = {
                            "id": counter,
                            "title": norm_title,
                            "genre": "In Sala · Roma",
                            "duration": "Programmazione odierna",
                            "rating": "★",
                            "posterUrl": poster if (poster and poster.startswith("http")) else "",
                            "gradient": grad,
                            "accent": acc,
                            "tag": "ROMA",
                            "synopsis": "Proiezione ufficiale in programma oggi. Tocca un orario per accedere alla biglietteria del cinema.",
                            "screenings": []
                        }
                        counter += 1
                    elif not movies_dict[norm_title]["posterUrl"] and poster and poster.startswith("http"):
                        movies_dict[norm_title]["posterUrl"] = poster

                    if not any(s["cinema"] == cinema["name"] for s in movies_dict[norm_title]["screenings"]):
                        movies_dict[norm_title]["screenings"].append({
                            "city": "Roma",
                            "cinema": cinema["name"],
                            "zone": cinema["zone"],
                            "times": times,
                            "bookingUrl": booking_url or cinema["url"]
                        })
                        found_count += 1

                print(f"  Estratti {found_count} film da {cinema['name']}.")
            except Exception as e:
                print(f"  Errore su {cinema['name']}: {e}")

        browser.close()

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("⚠️ Nessun dato estratto in questo giro.")

if __name__ == "__main__":
    scrape_with_browser()
