import json, re, requests
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "movies.json"
ZONES = {"barberini":"Centro","quattro fontane":"Centro","farnese":"Campo de' Fiori","fiamma":"Centro","troisi":"Trastevere","sacher":"Trastevere","intrastevere":"Trastevere","reale":"Trastevere","adriano":"Prati","eden":"Prati","giulio cesare":"Prati","azzurro scipioni":"Prati","lux":"Trieste / Salario","odeon":"Trieste / Salario","savoy":"Salario","mignon":"Salario","greenwich":"Testaccio","eurcine":"EUR","atlantic":"Tuscolana","madison":"San Paolo","antares":"Monte Sacro","broadway":"Prenestina","tibur":"San Lorenzo","andromeda":"Termini","caravaggio":"Parioli","maestoso":"Appia","parco de' medici":"Magliana","moderno":"Repubblica","porta di roma":"Bufalotta","roma est":"Lunghezza","romaest":"Lunghezza","maximo":"Laurentina","cineferonia":"Fiano Romano","doria":"Prati","trianon":"Appio"}
GRADS = [("from-[#3a2818] via-[#1c1613] to-[#0a0a0c]","bg-amber-500/20 text-amber-300"),("from-[#162942] via-[#101824] to-[#0a0a0c]","bg-sky-500/20 text-sky-300"),("from-[#3d1a24] via-[#1f1216] to-[#0a0a0c]","bg-rose-500/20 text-rose-300"),("from-[#17332b] via-[#101c19] to-[#0a0a0c]","bg-emerald-500/20 text-emerald-300")]
PCACHE = {}

def get_poster(title):
    if title in PCACHE: return PCACHE[title]
    clean = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", title).strip().lower()
    if len(clean) < 3: return ""
    for c in ["it", "us"]:
        try:
            r = requests.get("https://itunes.apple.com/search", params={"term": clean, "media": "movie", "country": c, "limit": 5}, timeout=5).json()
            for it in r.get("results", []):
                tn = (it.get("trackName") or "").lower().strip()
                if tn == clean or (len(clean) >= 6 and (clean in tn or tn in clean)):
                    art = it.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
                    if art: PCACHE[title] = art; return art
        except Exception: pass
    PCACHE[title] = ""; return ""

def norm_cinema(raw):
    n = re.sub(r"\s*[-–|]?\s*Roma$", "", raw, flags=re.I).strip()
    n = re.sub(r"^(?:Multisala|Nuovo\s+Cinema|Cinema)\s+", "", n, flags=re.I).strip()
    if "sacher" in n.lower(): return "Nuovo Sacher"
    return "Cineferonia" if ("cineferonia" in n.lower() or "fiano" in n.lower()) else (n.title() or raw.strip())

def get_zone(c): return next((z for k, z in ZONES.items() if k in c.lower()), "Roma")
def is_ov(raw): return bool(re.search(r"(?:\bO\.?V\.?\b|\bV\.?O\.?S?\.?\b|SUB\s*ITA|VERSIONE\s*ORIGINALE)", raw, re.I))

def norm_title(raw):
    c = re.sub(r"^\s*[\(\[](?:O\.?V\.?|V\.?O\.?S?\.?|2D|3D|EVENTO|SUB\s*ITA)[\)\]]\s*", "", raw, flags=re.I)
    c = re.sub(r"\s*[\(\[](?:O\.?V\.?|V\.?O\.?S?\.?|2D|3D|DOLBY ATMOS|SUB\s*ITA|VM\d+|EVENTO|\bIT\b)[\)\]]", "", c, flags=re.I)
    c = re.sub(r"\b(?:O\.?V\.?|V\.?O\.?S?\.?|SUB\s*ITA)\b\s*$", "", c, flags=re.I)
    return " ".join(re.sub(r"^[\(\)\[\]\-\–\:\.\s]+", "", c).split()).strip().title()

def parse_json(data, today, base_url, out):
    if isinstance(data, dict):
        t = next((data[k].strip() for k in ["Title","title","EventName","eventName","MovieTitle","movieTitle","Descrizione","descrizione"] if isinstance(data.get(k), str) and 2 <= len(data[k].strip()) <= 80), "")
        if t:
            times = re.findall(rf"{today}[T\s]+([12]\d):([0-5][05])", json.dumps(data))
            if times:
                out.append({"raw": t, "url": base_url, "st": [{"time": f"{h}:{m}", "url": base_url} for h, m in sorted(set(times))]})
        for v in data.values(): parse_json(v, today, base_url, out)
    elif isinstance(data, list):
        for i in data: parse_json(i, today, base_url, out)
def run():
    today = datetime.now().strftime("%Y-%m-%d")
    movies, idx, visited = {}, 1, set()
    excl = ["santa marinella","civitavecchia","velletri","tivoli","frascati","albano","anzio","nettuno","pomezia","guidonia","colleferro","bracciano","fiumicino","monterotondo","palestrina","ladispoli","grottaferrata","trevignano","ostia","parco leonardo"]

    def add_item(raw_t, cinema_n, st_list, b_url):
        nonlocal idx
        ov, nt, nc = is_ov(raw_t), norm_title(raw_t), norm_cinema(cinema_n)
        if len(nt) < 3 or not st_list: return
        if nt not in movies:
            g, a = GRADS[(idx-1) % len(GRADS)]
            movies[nt] = {"id": idx, "title": nt, "genre": "In Sala · Oggi", "duration": "Oggi", "rating": "★", "posterUrl": get_poster(nt), "gradient": g, "accent": a, "tag": "ROMA", "hasOV": ov, "synopsis": "Biglietteria ufficiale. Tocca un orario per prenotare.", "screenings": []}
            idx += 1
        elif ov: movies[nt]["hasOV"] = True
        sc = next((s for s in movies[nt]["screenings"] if s["cinema"].lower()==nc.lower() and s["isOV"]==ov), None)
        if not sc:
            movies[nt]["screenings"].append({"city": "Roma", "cinema": nc, "zone": get_zone(nc), "isOV": ov, "language": "V.O. · Sub ITA" if ov else "Italiano", "showtimes": st_list, "times": [x["time"] for x in st_list], "bookingUrl": b_url})
        else:
            m = {x["time"]: x["url"] for x in sc["showtimes"]}
            for x in st_list:
                if x["time"] not in m or "/local/" in m[x["time"]]: m[x["time"]] = x["url"]
            sc["showtimes"] = [{"time": k, "url": v} for k, v in sorted(m.items())]
            sc["times"] = [x["time"] for x in sc["showtimes"]]

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-http2","--no-sandbox"])
        page = b.new_page(viewport={"width": 1280, "height": 900}, locale="it-IT")

        # 1. Webtic Roma
        list_url = "https://www.webtic.it/app/main/all-locals/RM"
        page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2200)
        page.evaluate("document.querySelectorAll('[class*=\"cookie\"],[id*=\"cookie\"],.cdk-overlay-backdrop').forEach(e=>e.remove())")

        targets = []
        for pg in range(1, 10):
            page.mouse.wheel(0, 3000); page.wait_for_timeout(400)
            names = page.evaluate("""() => [...document.querySelectorAll('h1,h2,h3,h4,h5,strong,[class*="title"],[class*="name"]')].map(e=>(e.innerText||'').trim().split('\\n')[0].trim()).filter(t=>t.length>=4&&t.length<=50&&!t.includes(',')&&!/crea informatica|cookie|privacy|eventi|locali|provincia|tutta italia/i.test(t))""")
            for n in names:
                if not any(x in n.lower() for x in excl) and norm_cinema(n).lower() not in visited:
                    visited.add(norm_cinema(n).lower()); targets.append((pg, n))
            nxt = page.locator(f"button:has-text('{pg+1}'), a:has-text('{pg+1}')").first
            if nxt.is_visible(timeout=400): nxt.click(force=True); page.wait_for_timeout(1500)
            else: break

        for pg, cname in targets:
            try:
                page.goto(list_url, wait_until="domcontentloaded", timeout=15000); page.wait_for_timeout(1500)
                page.evaluate("document.querySelectorAll('[class*=\"cookie\"],[id*=\"cookie\"]').forEach(e=>e.remove())")
                for p_i in range(1, pg):
                    b_pg = page.locator(f"button:has-text('{p_i+1}'), a:has-text('{p_i+1}')").first
                    if b_pg.is_visible(timeout=400): b_pg.click(force=True); page.wait_for_timeout(1000)

                el = page.get_by_text(cname, exact=False).first
                if not el.is_visible(timeout=700): continue
                payloads = []
                fn = lambda r: payloads.append(r.json()) if ("json" in r.headers.get("content-type","") and r.status==200) else None
                page.on("response", fn)
                el.click(force=True, timeout=4000); page.wait_for_timeout(2000)
                c_url = page.url
                oggi = page.get_by_text("Oggi", exact=True).first
                if oggi.is_visible(timeout=800): oggi.click(force=True, timeout=2000); page.wait_for_timeout(1400)
                page.remove_listener("response", fn)

                ext = []
                for pl in payloads: parse_json(pl, today, c_url, ext)
                for it in ext:
                    try:
                        if page.url != c_url:
                            page.goto(c_url, wait_until="domcontentloaded", timeout=10000); page.wait_for_timeout(1200)
                        ev_loc = page.get_by_text(it["raw"], exact=False).first
                        if not ev_loc.is_visible(timeout=600): ev_loc = page.get_by_text(norm_title(it["raw"]), exact=False).first
                        if ev_loc.is_visible(timeout=600):
                            ev_loc.click(force=True, timeout=2500)
                            page.wait_for_function("old => window.location.href !== old", arg=c_url, timeout=3000)
                            if page.url != c_url and "all-locals" not in page.url:
                                it["url"] = page.url
                                for s in it["st"]: s["url"] = page.url
                    except Exception: pass
                for it in ext: add_item(it["raw"], cname, it["st"], it["url"])
            except Exception: pass

        # 2. Circuito Cinema Roma (Quattro Fontane, Barberini, Giulio Cesare, Eden, Eurcine, Greenwich, Intrastevere, Fiamma)
        cc_salas = {"quattro fontane":"https://www.circuitocinema.com/cinema/quattro-fontane/","barberini":"https://www.circuitocinema.com/cinema/barberini/","giulio cesare":"https://www.circuitocinema.com/cinema/giulio-cesare/","eden":"https://www.circuitocinema.com/cinema/eden/","eurcine":"https://www.circuitocinema.com/cinema/eurcine/","greenwich":"https://www.circuitocinema.com/cinema/greenwich/","intrastevere":"https://www.circuitocinema.com/cinema/intrastevere/","fiamma":"https://www.circuitocinema.com/cinema/fiamma/"}
        for s_name, s_url in cc_salas.items():
            try:
                page.goto(s_url, wait_until="domcontentloaded", timeout=15000); page.wait_for_timeout(2000)
                blocks = page.evaluate("""() => [...document.querySelectorAll('article, .film-item, .movie-item, [class*="film"], [class*="movie"], [class*="schede"]')].map(el => ({txt: el.innerText || '', href: (el.querySelector('a[href]') || {}).href || ''})).filter(x => x.txt.length > 10 && x.txt.length < 600)""")
                for bl in blocks:
                    lines = [l.strip() for l in bl["txt"].split("\n") if l.strip()]
                    if not lines: continue
                    title_cand = next((l for l in lines if len(l) >= 3 and not re.match(r"^(\d{1,2}[:.]\d{2}|sala|acquista|biglietti|oggi|domani)", l, re.I)), "")
                    t_found = re.findall(r"\b([12]\d)[:.]([0-5][05])\b", bl["txt"])
                    if title_cand and t_found:
                        link = bl["href"] if bl["href"].startswith("http") else s_url
                        st_list = [{"time": f"{h}:{m}", "url": link} for h, m in sorted(set(t_found))]
                        add_item(title_cand, s_name, st_list, link)
            except Exception: pass

        b.close()

    res = list(movies.values())
    if res:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"✅ Salvati {len(res)} film.")

if __name__ == "__main__":
    run()
