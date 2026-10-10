# Pokemon graded-card +EV steal scanner

Finds graded Pokemon cards (grades 1-8, low pop) listed well below fair value. Runs every 3 hours via GitHub Actions and publishes
https://jonesmgabe.github.io/pokemon-ev-scanner/ plus `steals.json` (stable `id` per listing+price, for new-item alerts).

- Listings: PriceCharting Marketplace (public pages), eBay Browse API (optional: add `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` repo secrets from a free developer.ebay.com app; searches the `ebay_watchlist` cards in config.json).
- Fair value: median of recent same-grader, same-grade eBay sold comps shown on the card's PriceCharting page; fallback PriceCharting grade guide x grader haircut. `confidence` = high / medium / low.
- Pop: PSA/CGC pop from PriceCharting (0 is treated as unknown).
- Not used: TCGplayer, Fanatics Collect, Goldin, Alt, Courtyard, Heritage, 130point, PSA pop site, Facebook Marketplace (no public API, blocks bots, or ToS forbids scraping).

Tune thresholds in `config.json`. Run locally: `python3 run.py --out site`.
