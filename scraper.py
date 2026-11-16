import json
import re
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_ZONES = {
    "barberini": "Centro",
    "quattro fontane": "Centro",
    "farnese": "Campo de' Fiori",
    "fiamma": "Centro",
    "troisi": "Trastevere",
    "nuovo sacher": "Trastevere",
    "sacher": "Trastevere",
    "intrastevere": "Trastevere",
    "adriano": "Prati",
    "eden": "Prati",
    "giulio cesare": "Prati",
    "azzurro scipioni": "Prati",
    "lux": "Trieste / Salario",
    "odeon": "Trieste / Salario",
    "savoy": "Salario",
    "mignon": "Salario",
    "greenwich": "Testaccio",
    "eurcine": "EUR",
    "atlantic": "Tuscolana",
    "madison": "San Paolo",
    "antares": "Monte Sacro",
    "broadway": "Prenestina",
    "tibur": "San Lorenzo",
    "andromeda": "Termini",
    "caravaggio": "Parioli",
    "maestoso": "Appia",
    "reale": "Trastevere",
    "alhambra": "Prati"
}

GRADIENTS = [
    ("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]", "bg-amber-500/20 text-amber-300"),
    ("from-[#162942] via-[#101824] to-[#0a0a0c]", "bg-sky-500/20 text-sky-300"),
    ("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]", "bg-rose-500/20 text-rose-300"),
    ("from-[#17332b] via-[#101c19] to-[#0a0a0c]", "bg-emerald-500/20 text-emerald-300"),
    ("from-[#2c1d42] via-[#181224] to-[#0a0a0c]", "bg-purple-500/20 text-purple-300")
]

# Estrae direttamente dal DOM della scheda cinema: Titolo + Locandina reale + Orari
EXTRACT_MOVIES_DOM_JS = """
() => {
    const timeRegex = /\\b([01]?\\d|2[0-3]):[0-5]\\d\\b/g;
    const results = [];
    const seen = new Set();

    // Cerca tutti i contenitori che hanno un'immagine locandina o un titolo e degli orari
    const cards = document.querySelectorAll('article, [class*="event"], [class*="movie"], [class*="film"], [class*="card"], [class*="item"], li, div');

    cards.forEach(card => {
        if (card.children.length > 15) return;
        const text = (card.innerText || '').trim();
        if (text.length < 10 || text.length > 800) return;

        const matches = text.match(timeRegex);
        if (!matches || matches.length === 0 || matches.length > 18) return;

        // Cerca il titolo principale del film
        const titleEl = card.querySelector('h1, h2, h3, h4, h5, [class*="title"], [class*="titolo"], [class*="name"], strong, b');
        if (!titleEl) return;

        const rawTitle = (titleEl.innerText || '').trim();
        if (rawTitle.length < 2 || rawTitle.length > 80 || timeRegex.test(rawTitle)) return;
        if (/webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|crea informatica|provincia|roma|lazio|via |viale |piazza |tel\\.|sala \\d/i.test(rawTitle)) return;

        // Cerca la locandina reale associata a questo film (risalendo al massimo di 2 livelli se serve)
        let poster = '';
        let searchBox = card;
        for (let i = 0; i < 3 && searchBox; i++) {
            const imgs = searchBox.querySelectorAll('img');
            for (const img of imgs) {
                const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
                if (src && src.startsWith('http') && !/logo|icon|avatar|flag|banner|placeholder/i.test(src)) {
                    poster = src;
                    break;
                }
            }
            if (poster) break;
            searchBox = searchBox.parentElement;
        }

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

def detect_zone(cinema_name: str) -> str:
    lower_name = cinema_name.lower()
    for key, zone in ROME_ZONES.items():
        if key in lower_name:
            return zone
    return "Roma"

def clean_cinema_name(raw_name: str) -> str:
    # Ripulisce eventuali righe extra (es. indirizzo o "Roma") dal nome del cinema
    first_line = raw_name.splitlines()[0].strip()
    cleaned = re.sub(r"\s*[-–|]\s*Roma$", "", first_line, flags=re.IGNORECASE).strip()
    return cleaned or first_line

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA|VM\d+)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def parse_visible_text_fallback(body_text: str) -> list:
    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    results = []
    current_title = ""
    current_times = []
    time_re = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
    ignore_re = re.compile(
        r"webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|cinema|teatri|musical|tutta italia|crea informatica|provincia|roma|lazio|via |viale |piazza |tel\.|info@|scheda|dettagli|sala \d",
        re.I
    )

    for line in lines:
        times = time_re.findall(line)
        if times:
            if current_title:
                current_times.extend(times)
        else:
            if current_title and current_times:
                results.append({
                    "title": current_title,
                    "times": list(dict.fromkeys(current_times)),
                    "poster": ""
                })
                current_title = ""
                current_times = []

            if 3 <= len(line) <= 70 and not ignore_re.search(line) and not line.isdigit():
                current_title = line

    if current_title and current_times:
        results.append({
            "title": current_title,
            "times": list(dict.fromkeys(current_times)),
            "poster": ""
        })
    return results

def scrape_all_rome_cinemas():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scansione COMPLETA sale di Roma su Webtic...")
    movies_dict = {}
    counter = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-http2", "--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="it-IT"
        )
        page = context.new_page()

        rome_list_url = "https://www.webtic.it/app/main/all-locals/RM"
        page.goto(rome_list_url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        for btn_text in ["Accetta", "Accetto", "Accept"]:
            try:
                btn = page.get_by_text(btn_text, exact=False).first
                if btn.is_visible(timeout=400):
                    btn.click(timeout=400)
            except Exception:
                pass

        # Scorre verso il basso per caricare tutti i cinema (incluso Circuito Cinema)
        for _ in range(5):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(500)

        # Raccoglie TUTTI i link ai locali presenti nella pagina di Roma
        raw_links = page.evaluate("""
        () => {
            const items = [];
            const seenUrls = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href || '';
                const text = (a.innerText || '').trim();
                // Esclude i link di navigazione generica
                if (href.includes('/app/') && !href.includes('/all-locals') && !href.includes('/all-provinces') && !href.includes('/home') && !href.includes('/events')) {
                    if (text.length >= 3 && !seenUrls.has(href)) {
                        seenUrls.add(href);
                        items.push({ name: text, url: href });
                    }
                }
            });
            return items;
        }
        """)

        # Filtra fuori eventuali cinema fuori comune di Roma (es. Santa Marinella, Civitavecchia, ecc.)
        excluded_towns = ["santa marinella", "civitavecchia", "velletri", "tivoli", "frascati", "albano", "anzio", "nettuno", "pomezia", "guidonia", "colleferro", "bracciano", "fiumicino"]
        cinema_list = []
        for item in raw_links:
            c_name = clean_cinema_name(item["name"])
            if any(town in c_name.lower() for town in excluded_towns):
                continue
            cinema_list.append({"name": c_name, "url": item["url"]})

        print(f"Trovate {len(cinema_list)} sale a Roma: {[c['name'] for c in cinema_list]}")

        for cinema in cinema_list:
            print(f"→ Apertura {cinema['name']}...")
            try:
                page.goto(cinema["url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)

                extracted = page.evaluate(EXTRACT_MOVIES_DOM_JS)
                if not extracted:
                    extracted = parse_visible_text_fallback(page.inner_text("body"))

                print(f"  Estratti {len(extracted)} film (con locandine: {sum(1 for x in extracted if x.get('poster'))}).")

                zone = detect_zone(cinema["name"])

                for item in extracted:
                    norm_title = normalize_title(item["title"])
                    if not norm_title or len(norm_title) < 2:
                        continue

                    poster = item.get("poster", "")
                    if poster and poster.startswith("/"):
                        poster = urljoin(cinema["url"], poster)

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
                            "synopsis": "Biglietteria ufficiale Webtic. Tocca un orario per scegliere il posto in sala e acquistare.",
                            "screenings": []
                        }
                        counter += 1
                    elif not movies_dict[norm_title]["posterUrl"] and poster.startswith("http"):
                        movies_dict[norm_title]["posterUrl"] = poster

                    if not any(s["cinema"] == cinema["name"] for s in movies_dict[norm_title]["screenings"]):
                        movies_dict[norm_title]["screenings"].append({
                            "city": "Roma",
                            "cinema": cinema["name"],
                            "zone": zone,
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
        print("\n⚠️ Nessun dato estratto.")

if __name__ == "__main__":
    scrape_all_rome_cinemas()
