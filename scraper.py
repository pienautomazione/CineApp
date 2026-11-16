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

EXTRACT_JS = """
() => {
    const timeRegex = /\\b([01]?\\d|2[0-3]):[0-5]\\d\\b/g;
    const results = [];
    const seen = new Set();

    // Cerca qualsiasi elemento con orari HH:MM nella pagina o frame
    const allElements = document.querySelectorAll('div, li, article, section, tr, p, span, a');
    
    allElements.forEach(el => {
        // Considera solo elementi foglia o piccoli blocchi che contengono orari
        if (el.children.length > 8) return;
        const text = (el.innerText || '').trim();
        if (text.length < 4 || text.length > 350) return;

        const matches = text.match(timeRegex);
        if (!matches || matches.length === 0 || matches.length > 12) return;

        // Risale nel DOM per trovare il titolo più vicino sopra questo blocco orari
        let box = el.parentElement;
        let title = '';
        let bookingUrl = '';
        let poster = '';

        for (let i = 0; i < 5 && box; i++) {
            const h = box.querySelector('h1, h2, h3, h4, h5, strong, b, [class*="title"], [class*="titolo"]');
            if (h) {
                const candidate = (h.innerText || '').trim();
                if (candidate.length >= 2 && candidate.length <= 85 && !timeRegex.test(candidate)) {
                    title = candidate;
                    const a = box.querySelector('a[href*="webtic"], a[href*="bigliett"], a[href*="ticket"], a[href*="acquista"], a');
                    if (a) bookingUrl = a.href;
                    const img = box.querySelector('img');
                    if (img) poster = img.src || img.getAttribute('data-src') || '';
                    break;
                }
            }
            box = box.parentElement;
        }

        if (title && !/biglietteria|contatti|dove siamo|cookie|privacy|tariff|abbonament/i.test(title)) {
            const key = title.toLowerCase();
            if (!seen.has(key)) {
                seen.add(key);
                results.push({
                    title: title,
                    times: [...new Set(matches)],
                    bookingUrl: bookingUrl,
                    poster: poster
                });
            }
        }
    });
    return results;
}
"""

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA|VM\d+)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio estrazione completa (pagina + iframe)...")
    movies_dict = {}
    counter = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        for cinema in ROME_CINEMAS:
            print(f"\n→ Controllo {cinema['name']} ({cinema['url']})...")
            try:
                resp = page.goto(cinema["url"], wait_until="domcontentloaded", timeout=25000)
                status = resp.status if resp else "N/A"
                page.wait_for_timeout(4500)

                # Chiude eventuali banner cookie
                for btn_text in ["Accetta", "Accetto", "Accept", "Chiudi"]:
                    try:
                        btn = page.get_by_text(btn_text, exact=False).first
                        if btn.is_visible(timeout=400):
                            btn.click(timeout=400)
                    except Exception:
                        pass

                page.wait_for_timeout(1500)

                # Diagnostica: mostra stato HTTP e prime parole visibili
                body_preview = " ".join(page.inner_text("body").split())[:140]
                print(f"  HTTP {status} | Frame totali: {len(page.frames)} | Testo: {body_preview}...")

                # Estrae sia dal frame principale che da tutti gli iframe (es. Webtic)
                extracted = []
                for frame in page.frames:
                    try:
                        frame_items = frame.evaluate(EXTRACT_JS)
                        extracted.extend(frame_items)
                    except Exception:
                        pass

                print(f"  Film trovati: {len(extracted)}")

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
        print(f"\n✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("\n⚠️ Nessun dato estratto.")

if __name__ == "__main__":
    scrape_with_browser()
