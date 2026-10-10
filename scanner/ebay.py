"""eBay Browse API (official). Needs a free eBay developer app:
EBAY_CLIENT_ID / EBAY_CLIENT_SECRET as repo secrets. Without them this source
is skipped. Each watchlist card (a PriceCharting product URL, which supplies
fair value + pop) is searched for graded Buy-It-Now listings."""
from __future__ import annotations
import base64, os, re
import requests

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
GR = r"(PSA|CGC|BGS|BECKETT|SGC|TAG|ACE)"


def available():
    return bool(os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET"))


def _token():
    auth = base64.b64encode(f"{os.environ['EBAY_CLIENT_ID']}:{os.environ['EBAY_CLIENT_SECRET']}".encode()).decode()
    r = requests.post(TOKEN_URL, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}, timeout=30)
    r.raise_for_status(); return r.json()["access_token"]


def parse_grade(title):
    m = re.search(GR + r"\s*(?:GEM\s*MINT\s*|MINT\s*|NM-MT\s*|NM\s*|EX-MT\s*|VG-EX\s*)?(\d{1,2}(?:\.5)?)\b", title.upper())
    if not m: return None, None
    g = m.group(1).replace("BECKETT", "BGS"); v = float(m.group(2))
    return (g, v) if 1 <= v <= 10 else (None, None)


def search(query, limit=50):
    tok = _token()
    r = requests.get(SEARCH_URL, headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                     params={"q": query, "category_ids": "183454", "filter": "buyingOptions:{FIXED_PRICE},conditionIds:{2750}", "limit": limit}, timeout=30)
    r.raise_for_status()
    out = []
    for it in r.json().get("itemSummaries", []):
        g, v = parse_grade(it.get("title", ""))
        if not g: continue
        price = float(it["price"]["value"])
        ship = it.get("shippingOptions", [{}])[0].get("shippingCost", {}).get("value")
        out.append({"title": it["title"], "grader": g, "grade": v, "price": price + (float(ship) if ship else 0),
                    "url": it.get("itemWebUrl"), "shipping_included": float(ship) if ship else None})
    return out
