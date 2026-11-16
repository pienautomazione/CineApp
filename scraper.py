import json
import re
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_CINEMAS = [
    {"name": "Cinema Barberini", "zone": "Centro", "url": "https://www.cinemabarberini.it/"},
    {"name": "Cinema Quattro Fontane", "zone": "Centro", "url": "https://www.circuitocinema.com/cinema/quattro-fontane/"},
    {"name": "Cinema Adriano", "zone": "Prati", "url": "https://www.circuitocinema.com/cinema/adriano/"},
    {"name": "Cinema Giulio Cesare", "zone": "Prati", "url": "https://www.circuitocinema.com/cinema/giulio-cesare/"},
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
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA|VM\d+)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio estrazione strutturale Roma...")
    movies_dict = {}
    counter = 1

    # Script JavaScript eseguito dentro la pagina per trovare i blocchi con orari HH:MM
    extract_js = """
    () => {
        const timeRegex = /\\b([01]?\\d|2[0-3]):[0-5]\\d\\b/g;
        const results = [];
        const seenTitles = new Set();

        // Cerca tutti i titoli nella pagina
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, [class*="title"], [class*="titolo"]');
        
        headings.forEach(h => {
            const rawTitle = (h.innerText || '').trim();
            if (rawTitle.length < 2 || rawTitle.length > 85) return;
            if (/biglietteria|contatti|dove siamo|cookie|privacy|newsletter|abbonamenti|tariff/i.test(rawTitle)) return;

            // Risale fino a 4 livelli nel DOM per trovare il contenitore che include gli orari di quel film
            let container = h.parentElement;
            let foundTimes = [];
            let bookingLink = '';
            let posterSrc = '';

            for (let i = 0; i < 4 && container; i++) {
                const text = container.innerText || '';
                const matches = text.match(timeRegex);
                // Se trova orari ma non troppi (evita di prendere l'intera pagina)
                if (matches && matches.length > 0 && matches.length <= 15) {
                    foundTimes = [...new Set(matches)];
                    const a = container.querySelector('a[href*="webtic"], a[href*="bigliett"], a[href*="ticket"], a[href*="acquista"], a');
                    if (a) bookingLink = a.href;
                    const img = container.querySelector('img');
                    if (img) posterSrc = img.src || img.getAttribute('data-src') || '';
                    break;
                }
                container = container.parentElement;
            }

            if (foundTimes.length > 0 && !seenTitles.has(rawTitle.toLowerCase())) {
                seenTitles.add(rawTitle.toLowerCase());
                results.push({
                    title: rawTitle,
                    times: foundTimes,
                    bookingUrl: bookingLink,
                    poster: posterSrc
                });
            }
        });
        return results;
    }
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        for cinema in ROME_CINEMAS:
            print(f"→ Controllo {cinema['name']}...")
            try:
                page.goto(cinema["url"], wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(4000)

                # Prova a chiudere eventuali banner cookie
                for btn_text in ["Accetta", "Accetto", "Accept", "Chiudi"]:
                    try:
                        btn = page.get_by_text(btn_text, exact=False).first
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=500)
                    except Exception:
                        pass

                page.wait_for_timeout(1500)
                extracted = page.evaluate(extract_js)
                print(f"  Trovati {len(extracted)} film.")

                for item in extracted:
                    norm_title = normalize_title(item["title"])
                    if not norm_title:
                        continue

                    poster = item["poster"]
                    if poster and poster.startswith("/"):
                        poster = urljoin(cinema["url"], poster)

                    booking_url = item["bookingUrl"] or cinema["url"]
                    if booking_url.startswith("/"):
                        booking_url = urljoin(cinema["url"], booking_url)

                    if norm_title not in movies_dict:
                        grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
                        movies_dict[norm_title] = {
                            "id": counter,
                            "title": norm_title,
                            "genre": "In Sala · Roma",
                            "duration": "Programmazione odierna",
                            "rating": "★",
                            "posterUrl": poster if poster.startswith("http") else "",
                            "gradient": grad,
                            "accent": acc,
                            "tag": "ROMA",
                            "synopsis": "Proiezione ufficiale in programma oggi. Tocca un orario per accedere alla biglietteria.",
                            "screenings": []
                        }
                        counter += 1
                    elif not movies_dict[norm_title]["posterUrl"] and poster.startswith("http"):
                        movies_dict[norm_title]["posterUrl"] = poster

                    if not any(s["cinema"] == cinema["name"] for s in movies_dict[norm_title]["screenings"]):
                        movies_dict[norm_title]["screenings"].append({
                            "city": "Roma",
                            "cinema": cinema["name"],
                            "zone": cinema["zone"],
                            "times": item["times"],
                            "bookingUrl": booking_url
                        })

            except Exception as e:
                print(f"  Errore su {cinema['name']}: {e}")

        browser.close()

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("⚠️ Nessun dato estratto.")

if __name__ == "__main__":
    scrape_with_browser()
