import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_CINEMAS = [
    {"name": "Cinema Barberini", "search": "Cinema Barberini", "zone": "Centro"},
    {"name": "Cinema Quattro Fontane", "search": "Quattro Fontane", "zone": "Centro"},
    {"name": "Cinema Adriano", "search": "Cinema Adriano", "zone": "Prati"},
    {"name": "Cinema Giulio Cesare", "search": "Giulio Cesare", "zone": "Prati"},
    {"name": "Cinema Troisi", "search": "Cinema Troisi", "zone": "Trastevere"},
    {"name": "Nuovo Sacher", "search": "Nuovo Sacher", "zone": "Trastevere"},
    {"name": "Cinema Eurcine", "search": "Eurcine", "zone": "EUR"},
    {"name": "Cinema Lux", "search": "Cinema Lux Roma", "zone": "Trieste / Salario"},
    {"name": "Cinema Odeon", "search": "Cinema Odeon Roma", "zone": "Trieste / Salario"},
    {"name": "Cinema Greenwich", "search": "Greenwich", "zone": "Testaccio"},
    {"name": "Cinema Madison", "search": "Madison Roma", "zone": "San Paolo"}
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

def extract_from_json_payload(payload, found_list):
    """Cerca ricorsivamente dentro qualsiasi risposta JSON di Webtic titoli e orari."""
    if isinstance(payload, dict):
        title = (
            payload.get("Title") or payload.get("title") or
            payload.get("EventName") or payload.get("eventName") or
            payload.get("Description") or ""
        )
        performances = (
            payload.get("Performances") or payload.get("performances") or
            payload.get("Shows") or payload.get("shows") or
            payload.get("Events") or payload.get("events") or []
        )
        poster = (
            payload.get("Poster") or payload.get("poster") or
            payload.get("Image") or payload.get("image") or
            payload.get("ImageUrl") or payload.get("imageUrl") or ""
        )

        if isinstance(title, str) and len(title.strip()) >= 2 and isinstance(performances, list) and len(performances) > 0:
            raw_str = json.dumps(performances)
            times = list(dict.fromkeys(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", raw_str)))
            if times:
                found_list.append({
                    "title": title.strip(),
                    "times": times,
                    "poster": poster if isinstance(poster, str) else ""
                })

        for v in payload.values():
            extract_from_json_payload(v, found_list)
    elif isinstance(payload, list):
        for item in payload:
            extract_from_json_payload(item, found_list)

def parse_visible_text(body_text: str) -> list:
    lines = [l.strip() for l in body_text.splitlines() if l.strip()]
    results = []
    current_title = ""
    time_re = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")

    for line in lines:
        times = time_re.findall(line)
        if times:
            if current_title:
                results.append({
                    "title": current_title,
                    "times": list(dict.fromkeys(times)),
                    "poster": ""
                })
        else:
            if 3 <= len(line) <= 75 and not re.search(
                r"webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|cinema|teatri|musical|tutta italia",
                line,
                re.I
            ):
                current_title = line
    return results

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Avvio ricerca diretta su Webtic...")
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

        for cinema in ROME_CINEMAS:
            print(f"→ Ricerca {cinema['name']} su Webtic...")
            intercepted_items = []

            def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct and response.status == 200:
                        data = response.json()
                        extract_from_json_payload(data, intercepted_items)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto("https://www.webtic.it/", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)

                # Chiude eventuale banner cookie alla prima apertura
                for btn_text in ["Accetta", "Accetto", "Accept"]:
                    try:
                        btn = page.get_by_text(btn_text, exact=False).first
                        if btn.is_visible(timeout=400):
                            btn.click(timeout=400)
                    except Exception:
                        pass

                # Trova la barra di ricerca visibile in homepage e digita il nome del cinema
                search_input = page.locator("input[type='text'], input[type='search'], input[placeholder*='Cerca']").first
                search_input.fill(cinema["search"])
                page.wait_for_timeout(2000)

                # Clicca sul primo suggerimento/risultato che contiene il nome del cinema (o premi Invio)
                suggestion = page.locator(f"a:has-text('{cinema['search']}'), li:has-text('{cinema['search']}'), div[role='option']:has-text('{cinema['search']}')").first
                if suggestion.is_visible(timeout=2000):
                    suggestion.click()
                else:
                    search_input.press("Enter")

                page.wait_for_timeout(3500)
                current_cinema_url = page.url

                # Se l'intercettazione JSON non ha catturato nulla, usa il testo visibile della pagina del cinema
                if not intercepted_items:
                    body_text = page.inner_text("body")
                    if cinema == ROME_CINEMAS[0]:
                        preview = " | ".join([l.strip() for l in body_text.splitlines() if l.strip()][:15])
                        print(f"  [Dopo click - URL: {current_cinema_url}]: {preview}")
                    intercepted_items = parse_visible_text(body_text)

                unique_cinema_movies = {}
                for it in intercepted_items:
                    nt = normalize_title(it["title"])
                    if not nt:
                        continue
                    if nt not in unique_cinema_movies:
                        unique_cinema_movies[nt] = it
                    else:
                        unique_cinema_movies[nt]["times"] = list(dict.fromkeys(unique_cinema_movies[nt]["times"] + it["times"]))

                print(f"  Trovati {len(unique_cinema_movies)} film.")

                for norm_title, item in unique_cinema_movies.items():
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
                            "bookingUrl": current_cinema_url
                        })

            except Exception as e:
                print(f"  Errore su {cinema['name']}: {e}")
            finally:
                page.remove_listener("response", handle_response)

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
