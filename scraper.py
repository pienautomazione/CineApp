import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"

ROME_CINEMAS = [
    {"name": "Cinema Barberini", "keyword": "Barberini", "zone": "Centro"},
    {"name": "Cinema Quattro Fontane", "keyword": "Quattro Fontane", "zone": "Centro"},
    {"name": "Cinema Adriano", "keyword": "Adriano", "zone": "Prati"},
    {"name": "Cinema Giulio Cesare", "keyword": "Giulio Cesare", "zone": "Prati"},
    {"name": "Cinema Troisi", "keyword": "Troisi", "zone": "Trastevere"},
    {"name": "Nuovo Sacher", "keyword": "Sacher", "zone": "Trastevere"},
    {"name": "Cinema Eurcine", "keyword": "Eurcine", "zone": "EUR"},
    {"name": "Cinema Lux", "keyword": "Lux", "zone": "Trieste / Salario"},
    {"name": "Cinema Odeon", "keyword": "Odeon", "zone": "Trieste / Salario"},
    {"name": "Cinema Greenwich", "keyword": "Greenwich", "zone": "Testaccio"},
    {"name": "Cinema Madison", "keyword": "Madison", "zone": "San Paolo"}
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
        title = (
            payload.get("Title") or payload.get("title") or
            payload.get("EventName") or payload.get("eventName") or
            payload.get("Name") or payload.get("name") or ""
        )
        performances = (
            payload.get("Performances") or payload.get("performances") or
            payload.get("Shows") or payload.get("shows") or
            payload.get("Events") or payload.get("events") or
            payload.get("Schedule") or payload.get("schedule") or []
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
                r"webtic|carrello|accedi|privacy|cookie|seleziona|acquista|bigliett|oggi|domani|luned|marted|mercoled|gioved|venerd|sabat|domenic|cerca|eventi|locali|cinema|teatri|musical|tutta italia|nessun risultato|crea informatica|roma|lazio",
                line,
                re.I
            ):
                current_title = line
    return results

def scrape_with_browser():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Apertura elenco province Webtic...")
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

        # 1. Vai direttamente alla pagina delle province e clicca su "Roma"
        page.goto("https://www.webtic.it/app/main/all-provinces", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        for btn_text in ["Accetta", "Accetto", "Accept"]:
            try:
                btn = page.get_by_text(btn_text, exact=False).first
                if btn.is_visible(timeout=400):
                    btn.click(timeout=400)
            except Exception:
                pass

        # Clicca sulla voce "Roma" nell'elenco delle province
        try:
            roma_el = page.get_by_text("Roma", exact=True).first
            if roma_el.is_visible(timeout=3000):
                roma_el.click()
            else:
                page.get_by_text("Roma", exact=False).first.click()
            page.wait_for_timeout(3500)
        except Exception as e:
            print(f"Errore click su provincia Roma: {e}")

        rome_list_url = page.url
        print(f"URL pagina cinema di Roma: {rome_list_url}")

        # Legge i cinema elencati nella pagina di Roma
        body_preview = " | ".join([l.strip() for l in page.inner_text("body").splitlines() if l.strip()][:20])
        print(f"Contenuto pagina Roma: {body_preview}")

        # 2. Per ogni cinema di Roma presente, clicca sul suo nome per aprire i film e gli orari
        for cinema in ROME_CINEMAS:
            try:
                # Torna alla lista dei cinema di Roma se ci siamo spostati
                if page.url != rome_list_url:
                    page.goto(rome_list_url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                cinema_el = page.get_by_text(cinema["keyword"], exact=False).first
                if not cinema_el.is_visible(timeout=1500):
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
                page.wait_for_timeout(3500)
                booking_url = page.url

                if not intercepted_items:
                    body_text = page.inner_text("body")
                    intercepted_items = parse_visible_text(body_text)

                page.remove_listener("response", handle_response)

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
