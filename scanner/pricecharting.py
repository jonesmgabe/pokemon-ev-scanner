"""PriceCharting public pages: marketplace listings, per-grade guide prices,
per-grade sold comps (eBay completed sales), and PSA/CGC pop counts.
robots.txt allows /offers, /offer/* and /game/*. We fetch politely (delay, one
product page per card per run)."""
from __future__ import annotations
import html, json, re, statistics, time
from datetime import date, datetime, timedelta
import requests

BASE = "https://www.pricecharting.com"
UA = "Mozilla/5.0 (compatible; pokemon-ev-scanner/1.0; +https://jonesmgabe.github.io/pokemon-ev-scanner/)"
GRADERS = ["PSA", "CGC", "BGS", "SGC", "TAG", "ACE", "HGA", "BECKETT"]


class PC:
    def __init__(self, delay=1.5):
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.delay = delay; self._last = 0.0; self._cache = {}

    def get(self, url):
        if url in self._cache: return self._cache[url]
        wait = self.delay - (time.time() - self._last)
        if wait > 0: time.sleep(wait)
        r = self.s.get(url, timeout=30); self._last = time.time()
        r.raise_for_status(); self._cache[url] = r.text
        return r.text

    # ---- marketplace -------------------------------------------------
    def offers(self, condition_id):
        h = self.get(f"{BASE}/offers?category=pokemon-cards&status=available&sort=starts&condition-id={condition_id}")
        out = []
        for row in re.findall(r'<tr class="offer">(.*?)</tr>', h, re.S):
            m = re.search(r'href="(/offer/[a-z0-9]+)', row)
            name = re.search(r'<h2 class="product_name">\s*<a[^>]*>(.*?)</a><br>\s*(.*?)\s*</h2>', row, re.S)
            label = re.search(r'name="includes-string">([^<]*)', row)
            price = re.search(r'class="pricebox">.*?\$([\d,]+\.\d\d)', row, re.S)
            ship = re.search(r'includes \$([\d,]+\.\d\d) for shipping', row)
            if not (m and name and price): continue
            out.append({"offer_url": BASE + m.group(1), "card": html.unescape(name.group(1).strip()),
                        "set": html.unescape(name.group(2).strip()), "label": label.group(1) if label else "",
                        "price": _f(price.group(1)), "shipping_included": _f(ship.group(1)) if ship else None})
        return out

    def offer_detail(self, url):
        h = self.get(url)
        g = re.search(r'Graded By:</span>\s*([^<]+)<', h)
        c = re.search(r'Cert ID:</span>\s*(?:<a[^>]*>)?\s*([^<\s]+)', h)
        p = re.search(r'href="(/game/[a-z0-9-]+/[a-z0-9-]+)"', h)
        avail = re.search(r'itemprop="availability" content="([^"]+)"', h)
        return {"grader": (g.group(1).strip().upper() if g else ""), "cert": c.group(1) if c else "",
                "product_url": BASE + p.group(1) if p else None, "availability": avail.group(1) if avail else ""}

    # ---- product page ------------------------------------------------
    def product(self, url):
        h = self.get(url)
        pop = {}
        m = re.search(r'VGPC\.pop_data\s*=\s*(\{.*?\});', h)
        if m:
            try: pop = json.loads(m.group(1))
            except ValueError: pop = {}
        guide = {}
        i = h.find('id="full-prices"')
        if i > 0:
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h[i:i + 6000]))
            for lab, v in re.findall(r"((?:Grade \d(?:\.5)?)|(?:[A-Z]{3} 10(?: Black| Pristine)?)) \$([\d,]+\.\d\d)", txt):
                guide[norm_label(lab)] = _f(v)
        # Tab ids are reused generically across PriceCharting categories, so map them
        # from the visible dropdown labels on each page (e.g. "PSA 10 (30)").
        labels = {k: norm_label(v) for k, v in re.findall(r'<option[^>]*value="completed-auctions-([a-z-]+)"[^>]*>([^<(]*)', h)}
        # Split at every tab div so an empty tab (no table) never swallows its neighbour's rows.
        parts = re.split(r'<div class="completed-auctions-([a-z0-9-]+)[^"]*"[^>]*>', h)
        comps = {}
        for tab, body in zip(parts[1::2], parts[2::2]):
            body = body.split("</table>")[0] if "<table" in body.split('<div class="completed-auctions-')[0] else ""
            rows = []
            for r in re.findall(r'<tr id="ebay-[^"]*">(.*?)</tr>', body, re.S):
                d = re.search(r'<td class="date">([^<]+)</td>', r)
                t = re.search(r'<a[^>]*class="js-ebay-completed-sale"[^>]*>(.*?)</a>', r, re.S) or re.search(r'<td class="title">.*?<a[^>]*>(.*?)</a>', r, re.S)
                p = re.search(r'class="js-price"[^>]*>\s*\$([\d,]+\.\d\d)', r)
                if d and p:
                    rows.append({"date": d.group(1).strip(), "title": html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t.group(1))).strip()) if t else "", "price": _f(p.group(1))})
            if tab in labels: comps[labels[tab]] = rows
        return {"pop": pop, "guide": guide, "comps": comps}


def norm_label(lab):
    lab = re.sub(r"\s+", " ", lab).strip().replace("Prist.", "Pristine")
    return lab


def grade_from_label(label):
    m = re.search(r"(\d+(?:\.5)?)(?:\s+(?:Pristine|Black))?\s*$", label or "")
    return float(m.group(1)) if m else None


def variant_from_label(label):
    l = (label or "").lower()
    return "Pristine" if "pristine" in l else "Black" if "black" in l else ""


def _gs(grade):
    return str(int(grade)) if grade == int(grade) else str(grade)


def fair_value(prod, grade, grader, cfg, variant=""):
    """Median of recent same-grader, same-grade sold comps (PriceCharting's eBay
    completed sales); fallback = PriceCharting guide (x grader haircut for the
    all-grader 1-9.5 guides). Half grades other than 9.5 have no own tab or guide:
    they are valued only from exact-grade comps inside the whole-grade tab."""
    cutoff = (date.today() - timedelta(days=cfg["comp_max_age_days"])).isoformat()
    gr = grader if grader in GRADERS else None
    if grade == 10:
        if not gr: return None, "no value data", 0
        lab = f"{gr} 10" + (f" {variant}" if variant else "")
        rows = [r for r in prod["comps"].get(lab, []) if r["date"] >= cutoff][: cfg["comp_sample"]]
        if len(rows) >= cfg["min_comps"]:
            return round(statistics.median(r["price"] for r in rows), 2), f"high: median of {len(rows)} {lab} sold comps", len(rows)
        gv = prod["guide"].get(lab)
        if gv:
            return gv, ("medium: " if rows else "low: ") + f"PriceCharting {lab} guide; {len(rows)} recent solds", len(rows)
        return None, "no value data", 0
    gs = _gs(grade)
    tab = f"Grade {gs}" if grade in (9.5,) or grade == int(grade) else f"Grade {int(grade)}"
    rows = [r for r in prod["comps"].get(tab, []) if r["date"] >= cutoff]
    pat = re.compile(rf"\b{gr}\s*(?:[A-Z-]+\s+)?{re.escape(gs)}(?![.\d])") if gr else None
    same = [r for r in rows if pat and pat.search(r["title"].upper().replace("BECKETT", "BGS"))][: cfg["comp_sample"]]
    if len(same) >= cfg["min_comps"]:
        return round(statistics.median(r["price"] for r in same), 2), f"high: median of {len(same)} {gr} {gs} sold comps", len(same)
    gv = prod["guide"].get(f"Grade {gs}")
    if gv:
        hc = cfg["grader_guide_haircut"].get(grader, cfg["grader_guide_haircut"]["OTHER"])
        return round(gv * hc, 2), ("medium: " if len(rows) >= cfg["min_comps"] else "low: ") + f"PriceCharting Grade {gs} guide x{hc} ({grader or 'unknown'} haircut); {len(rows)} recent grade-{gs} solds", len(rows)
    return None, f"no value data ({len(same)} exact {gs} comps)", 0


def pop_for(prod, grade, grader, variant=""):
    """PSA/CGC pop by whole grade (PriceCharting has no half-grade or
    Pristine/Black-Label split, so those return None)."""
    key = {"PSA": "psa", "CGC": "cgc"}.get(grader)
    arr = prod["pop"].get(key) if key else None
    if variant or not arr or grade != int(grade) or not (1 <= grade <= len(arr)): return None
    v = arr[int(grade) - 1]
    return v or None  # 0 = PriceCharting has no pop data for this grade, not a true zero


def _f(s): return float(s.replace(",", ""))
