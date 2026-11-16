import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_CINEMAS = [
    {"name": "Cinema Adriano", "keyword": "Adriano", "zone": "Prati"},
    {"name": "Cinema Barberini", "keyword": "Barberini", "zone": "Centro"},
    {"name": "Cinema Quattro Fontane", "keyword": "Quattro Fontane", "zone": "Centro"},
    {"name": "Cinema Giulio Cesare", "keyword": "Giulio Cesare", "zone": "Prati"},
    {"name": "Cinema Troisi", "keyword": "Troisi", "zone": "Trastevere"},
    {"name": "Nuovo Sacher", "keyword": "Sacher", "zone": "Trastevere"},
    {"name": "Cinema Eurcine", "keyword": "Eurcine", "zone": "EUR"},
    {"name": "Cinema Lux", "keyword": "Lux", "zone": "Trieste / Salario"},
    {"name": "Cinema Odeon", "keyword": "Odeon", "zone": "Trieste / Salario"},
    {"name": "Cinema Greenwich", "keyword": "Greenwich", "zone": "Testaccio"},
    {"name": "Cinema Madison", "keyword": "Madison", "zone": "San Paolo"},
    {"name": "Cinema Atlantic", "keyword": "Atlantic", "zone": "Tuscolana"},
    {"name": "Cinema Antares", "keyword": "Antares", "zone": "Monte Sacro"},
    {"name": "Cinema Broadway", "keyword": "Broadway", "zone": "Prenestina"},
    {"name": "Azzurro Scipioni", "keyword": "Azzurro Scipioni", "zone": "Prati"}
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
    if isinstance(payload, dict):
        # Cerca qualsiasi oggetto che abbia un titolo e una lista di spettacoli/orari
        title = ""
        for k in ["Title", "title", "EventName", "eventName", "MovieTitle", "movieTitle", "Descrizione", "descrizione"]:
            if isinstance(payload.get(k), str) and len(payload[k].strip()) >= 2:
                title = payload[k].strip()
                break

        if title:
            raw_str = json.dumps(payload)
            times = list(dict.fromkeys(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", raw_str)))
            poster = ""
            for pk in ["Poster", "poster", "Image", "image", "ImageUrl", "imageUrl", "Locandina", "locandina", "Picture"]:
                if isinstance(payload.get(pk), str) and payload[pk].startswith("http"):
                    poster = payload[pk]
                    break
            if times:
                found_list.append({
                    "title": title,
                    "times": times,
                    "poster": poster
                })

        for v in payload.values():
            extract_from_json_payload(v, found_list)
    elif isinstance(payload, list):
        for item in payload:
            extract_from_json_payload(item, found_list)

def parse_visible_text(body_text: str) -> list:
    """Associa ogni blocco titolo agli orari HH:MM che compaiono nelle righe successive."""
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

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Apertura diretta lista cinema di Roma su Webtic...")
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

        # URL diretto della provincia di Roma scoperto dal log!
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

        first_cinema_logged = False

        for cinema in ROME_CINEMAS:
            try:
                if page.url != rome_list_url:
                    page.goto(rome_list_url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                cinema_el = page.get_by_text(cinema["keyword"], exact=False).first
                if not cinema_el.is_visible(timeout=1200):
                    continue

                print(f"→ Apertura {cinema['name']}...")
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
                cinema_el.click()
                page.wait_for_timeout(4000)
                booking_url = page.url

                body_text = page.inner_text("body")
                if not first_cinema_logged:
                    preview = " | ".join([l.strip() for l in body_text.splitlines() if l.strip()][:28])
                    print(f"  [Scheda {cinema['name']} - URL: {booking_url}]: {preview}")
                    first_cinema_logged = True

                if not intercepted_items:
                    intercepted_items = parse_visible_text(body_text)

                page.remove_listener("response", handle_response)

                unique_cinema_movies = {}
                for it in intercepted_items:
                    nt = normalize_title(it["title"])
                    if not nt or len(nt) < 2:
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
        print("\n⚠️ Nessun dato estratto in questo giro.")

if __name__ == "__main__":
    scrape_with_browser()
