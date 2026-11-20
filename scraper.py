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
                    if search_term.lower() in track or track in search_term.lower() or len(results) == 1:
                        art = item.get("artworkUrl100", "")
                        if art:
                            hd_art = art.replace("100x100bb", "600x600bb")
                            POSTER_CACHE[title] = hd_art
                            return hd_art
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
    cleaned = re.sub(r"\s*[\(\[](?:O\.?V\.?|V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB\s*ITA|VM\d+|EVENTO|\bIT\b)[\)\]]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:O\.?V\.?|V\.?O\.?S?\.?|SUB\s*ITA)\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\(\)\[\]\-\–\:\.\s]+", "", cleaned)
    return " ".join(cleaned.split()).strip().title()

def parse_webtic_json(data, today_iso: str, base_cinema_url: str, results: list):
    """Estrae dal JSON API di Webtic titolo, locandina, URL diretto evento e orari tondi di oggi."""
    if isinstance(data, dict):
        title = ""
        for k in ["Title", "title", "EventName", "eventName", "MovieTitle", "movieTitle", "Descrizione", "descrizione"]:
            val = data.get(k)
            if isinstance(val, str) and 2 <= len(val.strip()) <= 80:
                title = val.strip()
                break

        if title:
            poster = ""
            for pk in ["Poster", "poster", "Image", "image", "ImageUrl", "imageUrl", "Locandina", "locandina", "Picture", "Thumb", "thumb", "Cover", "cover"]:
                pval = data.get(pk)
                if isinstance(pval, str) and pval.startswith("http"):
                    poster = pval
                    break

            event_id = data.get("EventId") or data.get("eventId") or data.get("Id") or data.get("id")
            direct_url = base_cinema_url
            if event_id and "/local/" in base_cinema_url:
                clean_base = base_cinema_url.split("?")[0].rstrip("/")
                if "/event/" not in clean_base:
                    direct_url = f"{clean_base}/event/{event_id}"

            raw_str = json.dumps(data)
            # Cerca orari associati alla data odierna (YYYY-MM-DDTHH:MM) con minuti multipli di 5
            today_times = re.findall(rf"{today_iso}[T\s]+([12]\d):([0-5][05])", raw_str)
            if today_times:
                showtimes = [{"time": f"{h}:{m}", "url": direct_url} for h, m in sorted(set(today_times))]
                results.append({"title": title, "poster": poster, "showtimes": showtimes, "url": direct_url})

        for v in data.values():
            parse_webtic_json(v, today_iso, base_cinema_url, results)
    elif isinstance(data, list):
        for item in data:
            parse_webtic_json(item, today_iso, base_cinema_url, results)

def scrape_all_rome():
    today_iso = datetime.now().strftime("%Y-%m-%d")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio raccolta JSON API cinema Roma per {today_iso}...")
    movies_dict = {}
    counter = 1

    def add_screening(raw_title: str, cinema_name: str, showtimes: list, event_url: str, poster: str = ""):
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
                "synopsis": "Biglietteria ufficiale. Tocca un orario per aprire la scheda spettacolo e scegliere il posto.",
                "screenings": []
            }
            counter += 1
        else:
            if not movies_dict[norm_title]["posterUrl"] and poster:
                movies_dict[norm_title]["posterUrl"] = poster
            if is_ov:
                movies_dict[norm_title]["hasOV"] = True

        clean_c_name = normalize_cinema_name(cinema_name)
        lang_label = "V.O. · Sub ITA" if is_ov else "Italiano"

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
                "bookingUrl": event_url
            })
        else:
            merged = {st["time"]: st["url"] for st in existing.get("showtimes", [])}
            for st in showtimes:
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
        dismiss_cookies(page)

        excluded_towns = [
            "santa marinella", "civitavecchia", "velletri", "tivoli", "frascati",
            "albano", "anzio", "nettuno", "pomezia", "guidonia", "colleferro",
            "bracciano", "fiumicino", "monterotondo", "palestrina", "ladispoli",
            "grottaferrata", "trevignano", "ostia", "parco leonardo"
        ]
        all_cinema_names = []
        seen_cinemas = set()

        for page_num in range(1, 8):
            for _ in range(4):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(200)

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
                    if btn.is_visible(timeout=400) and btn.is_enabled():
                        btn.click(force=True)
                        page.wait_for_timeout(1800)
                        next_clicked = True
                        break
                except Exception:
                    pass
            if not next_clicked:
                break

        print(f"Trovati {len(all_cinema_names)} cinema unici a Roma.")

        for target_page, cinema_name in all_cinema_names:
            try:
                if page.url != rome_list_url:
                    page.goto(rome_list_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                    dismiss_cookies(page)

                for p_idx in range(1, target_page):
                    for selector in [f"button:has-text('{p_idx + 1}')", f"a:has-text('{p_idx + 1}')", "[aria-label*='Next']"]:
                        try:
                            btn = page.locator(selector).first
                            if btn.is_visible(timeout=400):
                                btn.click(force=True)
                                page.wait_for_timeout(1200)
                                break
                        except Exception:
                            pass

                cinema_el = page.get_by_text(cinema_name, exact=True).first
                if not cinema_el.is_visible(timeout=800):
                    cinema_el = page.get_by_text(cinema_name, exact=False).first
                if not cinema_el.is_visible(timeout=800):
                    continue

                raw_payloads = []
                def on_resp(resp):
                    try:
                        if "json" in resp.headers.get("content-type", "") and resp.status == 200:
                            raw_payloads.append(resp.json())
                    except Exception:
                        pass

                page.on("response", on_resp)
                cinema_el.click(force=True, timeout=5000)
                page.wait_for_timeout(2600)
                dismiss_cookies(page)
                cinema_url = page.url

                oggi_btn = page.get_by_text("Oggi", exact=True).first
                if oggi_btn.is_visible(timeout=1000):
                    oggi_btn.click(force=True, timeout=2500)
                    page.wait_for_timeout(1800)

                page.remove_listener("response", on_resp)

                extracted = []
                for payload in raw_payloads:
                    parse_webtic_json(payload, today_iso, cinema_url, extracted)

                print(f"→ {cinema_name}: {len(extracted)} film con orari oggi")
                for it in extracted:
                    add_screening(it["title"], cinema_name, it["showtimes"], it["url"], it["poster"])

            except Exception as e:
                print(f"  Salto {cinema_name}: {str(e)[:80]}")

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
