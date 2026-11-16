import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

# Link diretti alle biglietterie ufficiali Webtic dei cinema di Roma
ROME_CINEMAS = [
    {"name": "Cinema Barberini", "zone": "Centro", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5191"},
    {"name": "Cinema Quattro Fontane", "zone": "Centro", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5195"},
    {"name": "Cinema Adriano", "zone": "Prati", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5188"},
    {"name": "Cinema Giulio Cesare", "zone": "Prati", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5193"},
    {"name": "Cinema Troisi", "zone": "Trastevere", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5487"},
    {"name": "Nuovo Sacher", "zone": "Trastevere", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5201"},
    {"name": "Cinema Eurcine", "zone": "EUR", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5192"},
    {"name": "Cinema Lux", "zone": "Trieste / Salario", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5194"},
    {"name": "Cinema Odeon", "zone": "Trieste / Salario", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5196"},
    {"name": "Cinema Greenwich", "zone": "Testaccio", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5197"},
    {"name": "Cinema Madison", "zone": "San Paolo", "url": "https://www.webtic.it/#/shopping?action=loadLocal&localId=5198"}
]

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

EXTRACT_WEBTIC_JS = """
() => {
    const timeRegex = /\\b([01]?\\d|2[0-3]):[0-5]\\d\\b/g;
    const results = [];
    const seen = new Set();

    // Su Webtic ogni evento ha un titolo e i bottoni/badge con gli orari nella stessa riga o card
    const blocks = document.querySelectorAll('.event-item, .movie-item, .card, .panel, [ng-repeat], .row, li');
    
    blocks.forEach(box => {
        const text = (box.innerText || '').trim();
        if (text.length < 8 || text.length > 600) return;

        const matches = text.match(timeRegex);
        if (!matches || matches.length === 0 || matches.length > 15) return;

        // Cerca il titolo principale del film
        const titleEl = box.querySelector('h1, h2, h3, h4, h5, .title, .event-title, strong, b');
        if (!titleEl) return;

        const rawTitle = (titleEl.innerText || '').trim();
        if (rawTitle.length < 2 || rawTitle.length > 85 || timeRegex.test(rawTitle)) return;
        if (/webtic|carrello|accedi|registrati|privacy|cookie|seleziona|sala|posto/i.test(rawTitle)) return;

        const img = box.querySelector('img');
        const poster = img ? (img.src || img.getAttribute('data-src') || '') : '';

        const key = rawTitle.toLowerCase();
        if (!seen.has(key)) {
            seen.add(key);
            results.push({
                title: rawTitle,
                times: [...new Set(matches)],
                poster: poster
            });
        }
    });
    return results;
}
"""

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA|VM\d+)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio raccolta diretta da biglietterie Webtic Roma...")
    movies_dict = {}
    counter = 1

    with sync_playwright() as p:
        # --disable-http2 risolve ERR_HTTP2_PROTOCOL_ERROR; --disable-blink-features evita il blocco bot
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-http2",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="it-IT"
        )
        page = context.new_page()

        for cinema in ROME_CINEMAS:
            print(f"→ Controllo {cinema['name']}...")
            try:
                page.goto(cinema["url"], wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(4500)

                extracted = page.evaluate(EXTRACT_WEBTIC_JS)
                print(f"  Trovati {len(extracted)} film.")

                for item in extracted:
                    norm_title = normalize_title(item["title"])
                    if not norm_title:
                        continue

                    poster = item["poster"] if item["poster"].startswith("http") else ""

                    if norm_title not in movies_dict:
                        grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
                        movies_dict[norm_title] = {
                            "id": counter,
                            "title": norm_title,
                            "genre": "In Sala · Roma",
                            "duration": "Programmazione odierna",
                            "rating": "★",
                            "posterUrl": poster,
                            "gradient": grad,
                            "accent": acc,
                            "tag": "ROMA",
                            "synopsis": "Biglietteria ufficiale Webtic. Tocca un orario per scegliere il posto in sala e acquistare.",
                            "screenings": []
                        }
                        counter += 1
                    elif not movies_dict[norm_title]["posterUrl"] and poster:
                        movies_dict[norm_title]["posterUrl"] = poster

                    if not any(s["cinema"] == cinema["name"] for s in movies_dict[norm_title]["screenings"]):
                        movies_dict[norm_title]["screenings"].append({
                            "city": "Roma",
                            "cinema": cinema["name"],
                            "zone": cinema["zone"],
                            "times": item["times"],
                            "bookingUrl": cinema["url"]
                        })

            except Exception as e:
                print(f"  Errore su {cinema['name']}: {e}")

        browser.close()

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("\n⚠️ Nessun dato estratto in questo giro.")

if __name__ == "__main__":
    scrape_with_browser()
