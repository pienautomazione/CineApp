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
    "cineferonia": "Fiano Romano"
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
    const ignore = /^(salta al|eventi|locali|magazine|chi siamo|privacy|scegli il locale|cerca eventi|provincia|roma|tutta italia|crea informatica|accedi|carrello|\d+)$/i;

    document.querySelectorAll('h1, h2, h3, h4, h5, strong, [class*="title"], [class*="name"], [class*="local"]').forEach(el => {
        if (el.children.length > 2) return;
        const txt = (el.innerText || '').trim().split('\n')[0].trim();
        if (txt.length >= 4 && txt.length <= 55 && !ignore.test(txt) && !seen.has(txt.toLowerCase())) {
            seen.add(txt.toLowerCase());
            names.push(txt);
        }
    });
    return names;
}
"""

JS_EXTRACT_SHOWTIMES = r"""
(fallbackUrl) => {
    const results = [];
    const validShowtimeRegex = /^([12]\d):([0-5][05])$/;
    const seen = new Set();

    document.querySelectorAll('h1, h2, h3, h4, strong, [class*="title"], [class*="titolo"]').forEach(titleEl => {
        const title = (titleEl.innerText || '').trim();
        if (title.length < 3 || title.length > 75 || seen.has(title.toLowerCase())) return;
        if (/webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|crea informatica|provincia|roma|lazio/i.test(title)) return;

        let container = titleEl.parentElement;
        for (let i = 0; i < 6 && container; i++) {
            const dayContainers = container.querySelectorAll('[class*="day"], [class*="date"], [class*="giorno"], [class*="tab-pane"]');
            const searchScope = dayContainers.length > 0 ? dayContainers[0] : container;

            const candidates = searchScope.querySelectorAll('a, button, [class*="time"], [class*="orario"], [class*="hour"], [class*="show"]');
            const showtimesMap = new Map();

            candidates.forEach(el => {
                if (el.children.length > 1) return;
                const txt = (el.innerText || '').trim();
                if (validShowtimeRegex.test(txt)) {
                    const linkEl = el.tagName === 'A' ? el : el.closest('a');
                    let directUrl = fallbackUrl;
                    if (linkEl && linkEl.href && linkEl.href.startsWith('http') && !linkEl.href.endsWith('#')) {
                        directUrl = linkEl.href;
                    }
                    if (!showtimesMap.has(txt)) {
                        showtimesMap.set(txt, directUrl);
                    }
                }
            });

            if (showtimesMap.size > 0 && showtimesMap.size <= 9) {
                let poster = '';
                const imgs = container.querySelectorAll('img');
                for (const img of imgs) {
                    const src = img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('ng-src') || '';
                    if (src && src.startsWith('http') && !/logo|icon|flag|placeholder|avatar|sprite/i.test(src)) {
                        poster = src;
                        break;
                    }
                }
                if (!poster) {
                    const allNodes = container.querySelectorAll('*');
                    for (const n of allNodes) {
                        const bg = window.getComputedStyle(n).backgroundImage || '';
                        const m = bg.match(/url\(["']?(https?:\/\/[^"')]+)["']?\)/);
                        if (m && !/logo|icon|flag|placeholder|avatar|sprite/i.test(m[1])) {
                            poster = m[1];
                            break;
                        }
                    }
                }

                const showtimes = Array.from(showtimesMap.entries())
                    .map(([time, url]) => ({ time, url }))
                    .sort((a, b) => a.time.localeCompare(b.time));

                seen.add(title.toLowerCase());
                results.push({ title, showtimes, poster });
                break;
            }
            container = container.parentElement;
        }
    });
    return results;
}
"""

def fetch_hd_poster(title: str) -> str:
    if title in POSTER_CACHE:
        return POSTER_CACHE[title]
    search_term = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", title).strip()

    # 1. Prova iTunes Store (IT e US)
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
                    if search_term.lower() in track or track in search_term.lower() or len(results) == 1:
                        art = item.get("artworkUrl100", "")
                        if art:
                            hd_art = art.replace("100x100bb", "600x600bb")
                            POSTER_CACHE[title] = hd_art
                            return hd_art
        except Exception:
            pass

    # 2. Fallback Wikipedia IT (ottimo per film italiani recenti usciti in sala)
    try:
        r = requests.get(
            "https://it.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f"{search_term} film",
                "gsrlimit": 2,
                "prop": "pageimages",
                "pithumbsize": 600,
                "format": "json"
            },
            headers={"User-Agent": "CineApp/1.0"},
            timeout=5
        )
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            for p_data in pages.values():
                thumb = p_data.get("thumbnail", {}).get("source", "")
                if thumb and thumb.startswith("http"):
                    POSTER_CACHE[title] = thumb
                    return thumb
    except Exception:
        pass

    POSTER_CACHE[title] = ""
    return ""

def normalize_cinema_name(raw_name: str) -> str:
    name = re.sub(r"\s*[-–|]?\s*Roma$", "", raw_name, flags=re.I).strip()
    name = re.sub(r"^(?:Multisala|Nuovo\s+Cinema|Cinema)\s+", "", name, flags=re.I).strip()
    if "cineferonia" in name.lower() or "fiano romano" in name.lower():
        return "Cineferonia"
    return name.title() if name else raw_name.strip()

def detect_zone(cinema_name: str) -> str:
    lower = cinema_name.lower()
    for k, z in ROME_ZONES.items():
        if k in lower:
            return z
    return "Roma"

def detect_original_version(raw_title: str) -> bool:
    return bool(re.search(
        r"(?:\bO\.?V\.?\b|\bV\.?O\.?S?\.?\b|SUB\s*ITA|VERSIONE\s*ORIGINALE|ORIGINAL\s*VERSION)",
        raw_title,
        flags=re.IGNORECASE
    ))

def normalize_title(raw: str) -> str:
    cleaned = re.sub(r"^\s*[\(\[](?:O\.?V\.?|V\.?O\.?S?\.?|2D|3D|EVENTO|SUB\s*ITA)[\)\]]\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[\(\[](?:O\.?V\.?|V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB\s*ITA|VM\d+|EVENTO)[\)\]]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:O\.?V\.?|V\.?O\.?S?\.?|SUB\s*ITA)\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\(\)\[\]\-\–\:\.\s]+", "", cleaned)
    return " ".join(cleaned.split()).strip().title()

def scrape_all_rome():
    today_day = str(datetime.now().day)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio raccolta pulita cinema Roma (giorno {today_day})...")
    movies_dict = {}
    counter = 1

    def add_screening(raw_title: str, cinema_name: str, showtimes: list, fallback_url: str, poster: str = ""):
        nonlocal counter
        is_ov = detect_original_version(raw_title)
        norm_title = normalize_title(raw_title)
        if not norm_title or len(norm_title) < 3 or not showtimes:
            return

        if not poster:
            poster = fetch_hd_poster(norm_title)

        if norm_title not in movies_dict:
            grad, acc = GRADIENTS[(counter - 1) % len(GRADIENTS)]
            movies_dict[norm_title] = {
                "id": counter,
                "title": norm_title,
                "genre": "In Sala · Oggi",
                "duration": "Programmazione odierna",
                "rating": "★",
                "posterUrl": poster,
                "gradient": grad,
                "accent": acc,
                "tag": "ROMA",
                "hasOV": is_ov,
                "synopsis": "Biglietteria ufficiale. Tocca un orario per scegliere il posto in sala e acquistare.",
                "screenings": []
            }
            counter += 1
        else:
            if not movies_dict[norm_title]["posterUrl"] and poster:
                movies_dict[norm_title]["posterUrl"] = poster
            if is_ov:
                movies_dict[norm_title]["hasOV"] = True

        clean_c_name = normalize_cinema_name(cinema_name)
        lang_label = "V.O. · Sub ITA" if is_ov else "Lingua Italiana"

        existing = next(
            (s for s in movies_dict[norm_title]["screenings"]
             if s["cinema"].lower() == clean_c_name.lower() and s.get("isOV", False) == is_ov),
            None
        )
        if not existing:
            movies_dict[norm_title]["screenings"].append({
                "city": "Roma",
                "cinema": clean_c_name,
                "zone": detect_zone(clean_c_name),
                "isOV": is_ov,
                "language": lang_label,
                "showtimes": showtimes,
                "times": [st["time"] for st in showtimes],
                "bookingUrl": fallback_url
            })
        else:
            merged = {st["time"]: st["url"] for st in existing.get("showtimes", [])}
            for st in showtimes:
                if st["time"] not in merged or merged[st["time"]] == fallback_url:
                    merged[st["time"]] = st["url"]
            sorted_st = [{"time": t, "url": u} for t, u in sorted(merged.items())]
            existing["showtimes"] = sorted_st
            existing["times"] = [st["time"] for st in sorted_st]

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

        excluded_towns = [
            "santa marinella", "civitavecchia", "velletri", "tivoli", "frascati",
            "albano", "anzio", "nettuno", "pomezia", "guidonia", "colleferro",
            "bracciano", "fiumicino", "monterotondo", "palestrina", "ladispoli"
        ]
        all_cinema_names = []
        seen_cinemas = set()

        for page_num in range(1, 8):
            for _ in range(4):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(250)

            cards = page.evaluate(JS_GET_CINEMA_CARDS)
            for name in cards:
                low = name.lower()
                if any(t in low for t in excluded_towns):
                    continue
                norm_c = normalize_cinema_name(name).lower()
                if norm_c not in seen_cinemas:
                    seen_cinemas.add(norm_c)
                    all_cinema_names.append((page_num, name))

            next_clicked = False
            for selector in [f"button:has-text('{page_num + 1}')", f"a:has-text('{page_num + 1}')", "[aria-label*='Next']", "[aria-label*='Successiv']"]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=500) and btn.is_enabled():
                        btn.click()
                        page.wait_for_timeout(2000)
                        next_clicked = True
                        break
                except Exception:
                    pass
            if not next_clicked:
                break

        print(f"Trovati {len(all_cinema_names)} cinema unici: {[c[1] for c in all_cinema_names]}")

        for target_page, cinema_name in all_cinema_names:
            try:
                if page.url != rome_list_url:
                    page.goto(rome_list_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2200)

                for p_idx in range(1, target_page):
                    for selector in [f"button:has-text('{p_idx + 1}')", f"a:has-text('{p_idx + 1}')", "[aria-label*='Next']"]:
                        try:
                            btn = page.locator(selector).first
                            if btn.is_visible(timeout=500):
                                btn.click()
                                page.wait_for_timeout(1500)
                                break
                        except Exception:
                            pass

                cinema_el = page.get_by_text(cinema_name, exact=True).first
                if not cinema_el.is_visible(timeout=1200):
                    cinema_el = page.get_by_text(cinema_name, exact=False).first
                if not cinema_el.is_visible(timeout=1200):
                    continue

                cinema_el.click()
                page.wait_for_timeout(3200)
                cinema_url = page.url

                for today_sel in ["button:has-text('Oggi')", "a:has-text('Oggi')", f"button:has-text('{today_day}/')"]:
                    try:
                        t_btn = page.locator(today_sel).first
                        if t_btn.is_visible(timeout=400):
                            t_btn.click()
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        pass

                extracted = page.evaluate(JS_EXTRACT_SHOWTIMES, cinema_url)
                print(f"→ {cinema_name}: {len(extracted)} film (con locandine: {sum(1 for x in extracted if x.get('poster'))})")

                for it in extracted:
                    add_screening(it["title"], cinema_name, it["showtimes"], cinema_url, it.get("poster", ""))

            except Exception as e:
                print(f"  Errore su {cinema_name}: {e}")

        browser.close()

    movies_list = list(movies_dict.values())
    if movies_list:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(movies_list, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Salvati {len(movies_list)} film totali in '{OUTPUT_FILE}'.")
    else:
        print("\n⚠️ Nessun film estratto in questo giro.")

if __name__ == "__main__":
    scrape_all_rome()
