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
# completed-sales tab per grade (verified against the Full Price Guide values)
GRADE_TAB = {1: "loose-and-box", 2: "box-and-manual", 3: "grade-three", 4: "grade-four",
             5: "grade-five", 6: "grade-six", 7: "cib", 8: "new", 9: "graded"}
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
            for g, v in re.findall(r"Grade (\d(?:\.5)?) \$([\d,]+\.\d\d)", txt):
                guide[g] = _f(v)
        comps = {}
        for tab, body in re.findall(r'<div class="completed-auctions-([a-z0-9-]+)[^"]*"[^>]*>(.*?)</table>', h, re.S):
            rows = []
            for r in re.findall(r'<tr id="ebay-[^"]*">(.*?)</tr>', body, re.S):
                d = re.search(r'<td class="date">([^<]+)</td>', r)
                t = re.search(r'<td class="title">.*?<a[^>]*>(.*?)</a>', r, re.S)
                p = re.search(r'class="js-price"[^>]*>\s*\$([\d,]+\.\d\d)', r)
                if d and p:
                    rows.append({"date": d.group(1).strip(), "title": html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t.group(1))).strip()) if t else "", "price": _f(p.group(1))})
            comps[tab] = rows
        return {"pop": pop, "guide": guide, "comps": comps}


def grade_from_label(label):
    m = re.search(r"(\d+(?:\.5)?)\s*$", label or "")
    return float(m.group(1)) if m else None


def fair_value(prod, grade, grader, cfg):
    """Median of recent same-grade, same-grader sold comps; falls back to the
    PriceCharting guide (an all-grader blend of solds) times a grader haircut."""
    if grade != int(grade): return None, "half grade: no comps tab", 0
    g = int(grade)
    rows = prod["comps"].get(GRADE_TAB.get(g, ""), [])
    cutoff = (date.today() - timedelta(days=cfg["comp_max_age_days"])).isoformat()
    rows = [r for r in rows if r["date"] >= cutoff]
    gr = grader if grader in GRADERS else None
    same = [r for r in rows if gr and re.search(rf"\b{gr}\s*{g}\b", r["title"].upper())]
    same = same[: cfg["comp_sample"]]
    if len(same) >= cfg["min_comps"]:
        return round(statistics.median(r["price"] for r in same), 2), f"high: median of {len(same)} {gr} {g} sold comps", len(same)
    gv = prod["guide"].get(str(g))
    if gv:
        hc = cfg["grader_guide_haircut"].get(grader, cfg["grader_guide_haircut"]["OTHER"])
        return round(gv * hc, 2), ("medium: " if len(rows) >= cfg["min_comps"] else "low: ") + f"PriceCharting Grade {g} guide x{hc} ({grader or 'unknown'} haircut); {len(rows)} recent grade-{g} solds", len(rows)
    return None, "no value data", 0


def pop_for(prod, grade, grader):
    key = {"PSA": "psa", "CGC": "cgc"}.get(grader)
    arr = prod["pop"].get(key) if key else None
    if not arr or grade != int(grade) or not (1 <= grade <= len(arr)): return None
    v = arr[int(grade) - 1]
    return v or None  # 0 = PriceCharting has no pop data for this grade, not a true zero


def _f(s): return float(s.replace(",", ""))
