"""Market values from FantasyCalc (Alan, Oct 6): a secondary reference beside SPAM's own values.

Writes data/market/redraft.json:
  { updated, source, url, terms, formats: { "q2_t12": { sleeper_id: [value, overall rank, position, position rank, 30-day trend] } } }

- FantasyCalc's documented, keyless endpoint only: GET https://api.fantasycalc.com/values/current
  (isDynasty=false, numQbs 1|2, numTeams 10|12, ppr=1, tep none|te+). Eight calls per run, a few runs a day at most
  (their docs ask for no more than hourly refreshes of /values/current). Keys: "q2_t12" (no TE premium) and
  "q2_t12_tep" (te+, +0.5 per TE catch) so AM compares like with like (Alan, Oct 8: market edge).
- Non-commercial use only without FantasyCalc's written permission; every screen that shows these numbers
  must credit FantasyCalc with a link (Trade Finder, the market edge views, the player drawer and the calculator).
- Values come from real completed trades. They never change SPAM ranks, tiers, values or history.
- If every call fails the previous file is kept (exit 0), so a market outage never blocks the stats refresh.

Run from the pipeline folder: python build_market.py
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

URL = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs={q}&numTeams={t}&ppr=1&tep={tep}"
FORMATS = [(q, t, tep) for tep in ("none", "te+") for q, t in ((2, 12), (1, 12), (2, 10), (1, 10))]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market", "redraft.json")


def fetch(q, t, tep, src=None):
    if src:   # tests: a local JSON file per format
        with open(src.format(q=q, t=t, tep=tep)) as f:
            return json.load(f)
    req = urllib.request.Request(URL.format(q=q, t=t, tep=urllib.parse.quote(tep)), headers={"User-Agent": "SPAM fantasy rankings (adequate-alan.github.io/myspam)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rows(data):
    out = {}
    for x in data if isinstance(data, list) else []:
        pl = x.get("player") or {}
        sid = pl.get("sleeperId")
        if not sid or x.get("value") is None:
            continue
        out[str(sid)] = [int(round(x["value"])), x.get("overallRank"), pl.get("position"), x.get("positionRank"), x.get("trend30Day")]
    return out


def main(src=None):
    formats = {}
    for q, t, tep in FORMATS:
        try:
            r = rows(fetch(q, t, tep, src))
            if r:
                formats[f"q{q}_t{t}" + ("_tep" if tep != "none" else "")] = r
        except Exception as e:
            print(f"  FantasyCalc {q}QB {t}-team tep={tep} skipped: {e}")
        time.sleep(0 if src else 1)
    if not formats:
        print("FantasyCalc: nothing fetched, kept the last file")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": "FantasyCalc",
                   "url": "https://www.fantasycalc.com", "terms": "Non-commercial use; credit FantasyCalc with a link",
                   "formats": formats}, f, separators=(",", ":"))
    print(f"FantasyCalc: {', '.join(f'{k} {len(v)}' for k, v in formats.items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(os.environ.get("MARKET_SRC")))
