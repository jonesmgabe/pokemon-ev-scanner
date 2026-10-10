#!/usr/bin/env python3
"""Scan -> site/index.html + site/steals.json.
  python3 run.py --out site [--prev-url https://jonesmgabe.github.io/pokemon-ev-scanner/]"""
from __future__ import annotations
import argparse, hashlib, html, json, os, re, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from scanner import pricecharting as pcm, ebay

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")


def evaluate(src, card, set_, grader, grade, price, link, prod, cfg, extra=None, variant=""):
    if grade is None or not (cfg["min_grade"] <= grade <= cfg["max_grade"]): return None
    fv, basis, ncomps = pcm.fair_value(prod, grade, grader, cfg, variant)
    if not fv or fv < cfg["min_fair_value"]: return None
    pop = pcm.pop_for(prod, grade, grader, variant)
    if pop is not None and pop > cfg["max_pop"]: return None
    disc = round(100 * (1 - price / fv), 1)
    item = {"id": hashlib.sha1(f"{src}|{link}|{price}".encode()).hexdigest()[:16], "source": src, "card": card, "set": set_,
            "grader": grader or "?", "grade": grade, "variant": variant, "pop": pop, "list_price": price, "fair_value": fv,
            "discount_pct": disc, "confidence": basis.split(":")[0], "fair_value_basis": basis, "comps_used": ncomps, "link": link}
    item.update(extra or {})
    return item if disc >= cfg["min_discount_pct"] else None


def scan(cfg):
    pc = pcm.PC(cfg["request_delay_s"]); steals, status = [], {}
    # 1) PriceCharting marketplace
    try:
        n = 0
        for cid in cfg["pricecharting_condition_ids"]:
            for o in pc.offers(cid):
                grade = pcm.grade_from_label(o["label"])
                if grade is None or not (cfg["min_grade"] <= grade <= cfg["max_grade"]): continue
                n += 1
                try:
                    d = pc.offer_detail(o["offer_url"])
                    if not d["product_url"] or "InStock" not in d["availability"]: continue
                    prod = pc.product(d["product_url"])
                    s = evaluate("PriceCharting Marketplace", o["card"], o["set"], d["grader"], grade, o["price"],
                                 o["offer_url"], prod, cfg, {"cert": d["cert"], "price_includes_shipping": o["shipping_included"], "comps_url": d["product_url"]}, pcm.variant_from_label(o["label"]))
                    if s: steals.append(s)
                except Exception as e:
                    print("offer error", o["offer_url"], e, file=sys.stderr)
        status["PriceCharting Marketplace"] = f"ok: {n} graded {cfg['min_grade']}-{cfg['max_grade']} listings checked"
    except Exception as e:
        status["PriceCharting Marketplace"] = f"error: {e}"
    # 2) eBay Browse API (key-gated)
    if ebay.available():
        try:
            n = 0
            for url in cfg["ebay_watchlist"]:
                prod = pc.product(url)
                h = pc.get(url); t = re.search(r"<title>([^<|]+)", h)
                name = html.unescape(t.group(1)).replace(" Prices", "").strip() if t else url
                for it in ebay.search(name + " graded"):
                    n += 1
                    s = evaluate("eBay", it["title"], name, it["grader"], it["grade"], it["price"], it["url"], prod, cfg,
                                 {"price_includes_shipping": it["shipping_included"], "comps_url": url, "match": "title search; verify card/variant"})
                    if s: steals.append(s)
            status["eBay"] = f"ok: {n} graded listings checked across {len(cfg['ebay_watchlist'])} watchlist cards"
        except Exception as e:
            status["eBay"] = f"error: {e}"
    else:
        status["eBay"] = "skipped: needs EBAY_CLIENT_ID / EBAY_CLIENT_SECRET repo secrets (free eBay developer app)"
    for k, v in {"TCGplayer": "no public graded-listing API (partner API closed to new devs); not scraped",
                 "Fanatics Collect / Goldin / Alt / Courtyard": "listings render via private JS APIs; no public API -> not used",
                 "Heritage": "403 to automated requests; no public API",
                 "130point / PSA pop / eBay sold pages": "403 to automated requests; PriceCharting comps + pop used instead",
                 "Facebook Marketplace": "no API, login-walled, ToS bans scraping -> not feasible"}.items():
        status[k] = v
    steals.sort(key=lambda s: -s["discount_pct"])
    return steals, status


def write_site(out, steals, status, cfg):
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    doc = {"generated_at": now.isoformat(timespec="seconds"), "count": len(steals), "criteria": {k: cfg[k] for k in
           ["min_grade", "max_grade", "max_pop", "min_discount_pct", "min_fair_value", "min_comps", "comp_max_age_days"]},
           "sources": status, "steals": steals}
    (out / "steals.json").write_text(json.dumps(doc, indent=2))
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(s['card'])}</td><td>{e(s['set'])}</td><td>{e(str(s['grade']).removesuffix('.0'))}{' ' + e(s['variant']) if s.get('variant') else ''}</td><td>{e(s['grader'])}</td>"
        f"<td>{'' if s['pop'] is None else s['pop']}</td><td>${s['list_price']:,.2f}</td><td title=\"{e(s['fair_value_basis'])}\">${s['fair_value']:,.2f}</td>"
        f"<td><b>{s['discount_pct']}%</b><br><span class=m>{e(s['confidence'])}</span></td><td>{e(s['source'])}</td><td><a href=\"{e(s['link'])}\" target=_blank>listing</a>"
        f"{' · <a href=%s target=_blank>comps</a>' % e(s['comps_url']) if s.get('comps_url') else ''}</td></tr>" for s in steals) or \
        "<tr><td colspan=10>No listings meet the steal criteria right now.</td></tr>"
    srcs = "".join(f"<li><b>{e(k)}</b>: {e(v)}</li>" for k, v in status.items())
    c = doc["criteria"]
    (out / "index.html").write_text(f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pokemon Graded +EV Steals</title><style>body{{font-family:system-ui,sans-serif;margin:16px;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border-bottom:1px solid #333;padding:6px;text-align:left}}th{{background:#222;position:sticky;top:0}}a{{color:#6cf}}.m{{color:#aaa;font-size:13px}}</style></head><body>
<h1>Pokemon Graded +EV Steals</h1><p class=m>Updated {now.astimezone(ET):%Y-%m-%d %I:%M %p} ET · {len(steals)} steals · grades {c['min_grade']}-{c['max_grade']}, pop &le; {c['max_pop']} (PSA/CGC where known; filter skipped when unknown),
&ge;{c['min_discount_pct']}% below fair value, fair value &ge; ${c['min_fair_value']} · <a href=steals.json>steals.json</a></p>
<div style="overflow-x:auto"><table><tr><th>Card</th><th>Set</th><th>Grade</th><th>Grader</th><th>Pop</th><th>List</th><th>Est. fair</th><th>Discount</th><th>Source</th><th>Link</th></tr>{rows}</table></div>
<p class=m>Fair value = median of recent same-grader same-grade eBay sold comps (via PriceCharting); else PriceCharting grade guide &times; grader haircut (hover the value for its basis). Pop = PSA/CGC population from PriceCharting. Always verify the card, variant, and slab before buying.</p>
<h3>Sources</h3><ul class=m>{srcs}</ul></body></html>""")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="site"); a = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    steals, status = scan(cfg)
    write_site(Path(a.out), steals, status, cfg)
    print(json.dumps({"steals": len(steals), "sources": status}, indent=1))


if __name__ == "__main__":
    main()
