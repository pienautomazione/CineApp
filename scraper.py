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
    cleaned = re.sub(r"\s*[\(\[](?:V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB ITA|VM\d+|EVENTO)[\)\]]", "", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().title()

def extract_today_from_webtic_dom(page) -> list:
    """Estrae solo i film e gli orari del primo blocco giornaliero (Oggi) dalla scheda Webtic."""
    return page.evaluate("""
    () => {
        const results = [];
        const timeRegex = /^([01]?\\d|2[0-3]):[0-5]\\d$/;
        
        // Cerca i blocchi film strutturati su Webtic
        const movieBlocks = document.querySelectorAll('[class*="event"], [class*="movie"], [class*="film"], article, .card');
        const seen = new Set();

        movieBlocks.forEach(block => {
            if (block.children.length > 18) return;
            const titleEl = block.querySelector('h1, h2, h3, h4, [class*="title"], [class*="titolo"]');
            if (!titleEl) return;

            const title = (titleEl.innerText || '').trim();
            if (title.length < 2 || title.length > 75 || seen.has(title.toLowerCase())) return;
            if (/webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|crea informatica|provincia|roma|lazio/i.test(title)) return;

            // Estrae SOLO i bottoni/badge che contengono un orario esatto HH:MM (ignora testi descrittivi o durate)
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

            // Cerca locandina
            let poster = '';
            const img = block.querySelector('img') || (block.parentElement && block.parentElement.querySelector('img'));
            if (img) {
                const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
                if (src.startsWith('http') && !/logo|icon|flag|placeholder/i.test(src)) {
                    poster = src;
                }
            }

            seen.add(title.toLowerCase());
            results.push({
                title: title,
                times: [...new Set(times)].sort(),
                poster: poster
            });
        });

        return results;
    }
    """)

def scrape_all_rome():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio raccolta completa Roma (Webtic + Circuito Cinema)...")
    movies_dict = {}
    counter = 1

    def add_screening(raw_title: str, cinema_name: str, city: str, times: list, booking_url: str, poster: str = ""):
        nonlocal counter
        norm_title = normalize_title(raw_title)
        if not norm_title or len(norm_title) < 2 or not times:
            return

        if not poster:
            poster = fetch_hd_poster(norm_title)

        if norm_title not in movies_dict:
            grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
            movies_dict[norm_title] = {
                "id": counter,
                "title": norm_title,
                "genre": "In Sala",
                "duration": "Programmazione odierna",
                "rating": "★",
                "posterUrl": poster,
                "gradient": grad,
                "accent": acc,
                "tag": city.upper(),
                "synopsis": "Proiezione ufficiale in sala. Seleziona un orario per accedere direttamente alla biglietteria del cinema.",
                "screenings": []
            }
            counter += 1
        elif not movies_dict[norm_title]["posterUrl"] and poster:
            movies_dict[norm_title]["posterUrl"] = poster

        if not any(s["cinema"] == cinema_name for s in movies_dict[norm_title]["screenings"]):
            movies_dict[norm_title]["screenings"].append({
                "city": city,
                "cinema": cinema_name,
                "zone": detect_zone(cinema_name),
                "times": sorted(list(dict.fromkeys(times))),
                "bookingUrl": booking_url
            })

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

        # 1. Raccoglie tutte le sale su Webtic Roma (all-locals/RM)
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

        for _ in range(6):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(400)

        raw_links = page.evaluate("""
        () => {
            const items = [];
            const seenUrls = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href || '';
                const text = (a.innerText || '').trim();
                if (href.includes('/app/') && !href.includes('/all-locals') && !href.includes('/all-provinces') && !href.includes('/home') && !href.includes('/events')) {
                    if (text.length >= 3 && !seenUrls.has(href)) {
                        seenUrls.add(href);
                        items.push({ name: text.splitlines()[0].trim(), url: href });
                    }
                }
            });
            return items;
        }
        """)

        excluded_towns = ["santa marinella", "civitavecchia", "velletri", "tivoli", "frascati", "albano", "anzio", "nettuno", "pomezia", "guidonia", "colleferro", "bracciano", "fiumicino"]
        cinema_list = [
            {"name": re.sub(r"\s*[-–|]\s*Roma$", "", item["name"], flags=re.I).strip(), "url": item["url"]}
            for item in raw_links
            if not any(t in item["name"].lower() for t in excluded_towns)
        ]

        print(f"Trovate {len(cinema_list)} sale su Webtic Roma.")

        for cinema in cinema_list:
            try:
                page.goto(cinema["url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2800)
                items = extract_today_from_webtic_dom(page)
                print(f"→ {cinema['name']}: {len(items)} film")
                for it in items:
                    add_screening(it["title"], cinema["name"], "Roma", it["times"], cinema["url"], it["poster"])
            except Exception as e:
                print(f"  Errore su {cinema['name']}: {e}")

        # 2. Integra Circuito Cinema Roma (Barberini, Quattro Fontane, Adriano, Giulio Cesare, Eurcine, Lux, Odeon, Fiamma, Mignon, Savoy)
        circuito_cinemas = [
            {"name": "Cinema Barberini", "url": "https://www.circuitocinema.com/cinema/barberini/"},
            {"name": "Cinema Quattro Fontane", "url": "https://www.circuitocinema.com/cinema/quattro-fontane/"},
            {"name": "Cinema Adriano", "url": "https://www.circuitocinema.com/cinema/adriano/"},
            {"name": "Cinema Giulio Cesare", "url": "https://www.circuitocinema.com/cinema/giulio-cesare/"},
            {"name": "Cinema Eurcine", "url": "https://www.circuitocinema.com/cinema/eurcine/"},
            {"name": "Cinema Lux", "url": "https://www.circuitocinema.com/cinema/lux/"},
            {"name": "Cinema Odeon", "url": "https://www.circuitocinema.com/cinema/odeon/"},
            {"name": "Cinema Mignon", "url": "https://www.circuitocinema.com/cinema/mignon/"},
            {"name": "Cinema Savoy", "url": "https://www.circuitocinema.com/cinema/savoy/"}
        ]

        for cc in circuito_cinemas:
            if any(cc["name"].lower() in c["name"].lower() for c in cinema_list):
                continue
            try:
                page.goto(cc["url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
                items = extract_today_from_webtic_dom(page)
                print(f"→ [Circuito Cinema] {cc['name']}: {len(items)} film")
                for it in items:
                    add_screening(it["title"], cc["name"], "Roma", it["times"], cc["url"], it["poster"])
            except Exception as e:
                print(f"  Errore Circuito Cinema {cc['name']}: {e}")

        browser.close()

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")

if __name__ == "__main__":
    scrape_all_rome()
