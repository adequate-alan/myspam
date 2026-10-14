"""Market values from FantasyCalc (Alan, Oct 6): a secondary reference beside SPAM's own values.

Writes data/market/redraft.json:
  { updated, changed, provider_updated, sync, source, url, terms,
    formats: { "q2_t12": { sleeper_id: [value, overall rank, position, position rank, 30-day trend] } } }

Freshness fields (Alan, Oct 11; the Rankings page's Market rankings freshness indicator reads them):
- `updated`: when this job last retrieved the values successfully (Adequate's sync time, never the provider's).
- `changed`: the last sync at which the values or ranks differed from the file before it, so "synced an hour ago" and
  "the market hasn't moved in two days" can be told apart. Adequate's own observation, not FantasyCalc's timestamp.
- `provider_updated`: the newest Last-Modified header FantasyCalc sent, or null; FantasyCalc's JSON carries no
  update time of its own, so the site says "Provider update unknown" when this is null rather than inventing one.
- `sync`: { attempted, ok, formats, of, error }: the last attempt. When every call fails the previous values are kept
  and only `sync` is rewritten (ok false, the error), so the site can show "Sync failed" instead of a quietly
  ageing timestamp.

- FantasyCalc's documented, keyless endpoint only: GET https://api.fantasycalc.com/values/current
  (isDynasty=false, numQbs 1|2, numTeams 10|12, ppr=1 tep none|te+, and ppr=0.5 tep none). Twelve calls per run, a
  few runs a day at most (their docs ask for no more than hourly refreshes of /values/current). Keys: "q2_t12" (Full
  PPR, no TE premium), "q2_t12_tep" (te+, +0.5 per TE catch) and "q2_t12_half" (Half PPR, no TE premium; Alan, Oct 14,
  Flock market lists PR 3) so AM compares like with like (Alan, Oct 8: market edge). A Half PPR league reads the
  "_half" key; until it exists the site falls back to Full PPR at a reduced weight.
- Non-commercial use only without FantasyCalc's written permission; every screen that shows these numbers
  must credit FantasyCalc with a link (Trade Finder, the market edge views, the player drawer and the calculator).
- Values come from real completed trades. They never change SPAM ranks, tiers, values or history.
- If every call fails the previous file is kept (exit 0), so a market outage never blocks the stats refresh.

Run from the pipeline folder: python build_market.py
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

URL = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs={q}&numTeams={t}&ppr={ppr}&tep={tep}"
# (numQbs, numTeams, tep, ppr): Full PPR with and without TE premium, Half PPR without
FORMATS = [(q, t, tep, 1) for tep in ("none", "te+") for q, t in ((2, 12), (1, 12), (2, 10), (1, 10))] + \
          [(q, t, "none", 0.5) for q, t in ((2, 12), (1, 12), (2, 10), (1, 10))]


def key_of(q, t, tep, ppr):
    return f"q{q}_t{t}" + ("_tep" if tep != "none" else "") + ("_half" if ppr == 0.5 else "")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market", "redraft.json")


def fetch(q, t, tep, src=None, ppr=1):
    """Returns (json, Last-Modified header or None)."""
    if src:   # tests: a local JSON file per format
        with open(src.format(q=q, t=t, tep=tep, ppr=ppr)) as f:
            return json.load(f), None
    req = urllib.request.Request(URL.format(q=q, t=t, ppr=ppr, tep=urllib.parse.quote(tep)), headers={"User-Agent": "SPAM fantasy rankings (adequate-alan.github.io/myspam)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), r.headers.get("Last-Modified")


def rows(data):
    out = {}
    for x in data if isinstance(data, list) else []:
        pl = x.get("player") or {}
        sid = pl.get("sleeperId")
        if not sid or x.get("value") is None:
            continue
        out[str(sid)] = [int(round(x["value"])), x.get("overallRank"), pl.get("position"), x.get("positionRank"), x.get("trend30Day")]
    return out


def previous():
    try:
        with open(OUT) as f:
            return json.load(f)
    except Exception:
        return None


def http_date(s):
    """An HTTP Last-Modified header as ISO 8601 UTC, or None."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def same_values(a, b):
    """True when every format has the same players at the same values and ranks (the 30-day trend may differ).
    A format the previous file didn't have (the Half PPR keys on their first sync) isn't a change of values."""
    if not a or not b or not set(a) <= set(b) and not set(b) <= set(a):
        return False
    common = set(a) & set(b)
    return bool(common) and all(set(a[k]) == set(b[k]) and all(a[k][sid][:4] == b[k][sid][:4] for sid in a[k]) for k in common)


def write(doc):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))


def main(src=None, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = previous()
    formats, errors, modified = {}, [], []
    for q, t, tep, ppr in FORMATS:
        try:
            data, lm = fetch(q, t, tep, src, ppr)
            r = rows(data)
            if r:
                formats[key_of(q, t, tep, ppr)] = r
                if lm and http_date(lm):
                    modified.append(http_date(lm))
            else:
                errors.append(f"{q}QB {t}-team ppr={ppr} tep={tep}: empty answer")
        except Exception as e:
            errors.append(f"{q}QB {t}-team ppr={ppr} tep={tep}: {e}")
            print(f"  FantasyCalc {q}QB {t}-team ppr={ppr} tep={tep} skipped: {e}")
        time.sleep(0 if src else 1)
    if not formats:
        print("FantasyCalc: nothing fetched, kept the last file")
        if prev and isinstance(prev, dict):   # record the failed attempt; values and `updated` stay as they were
            prev["sync"] = {"attempted": stamp, "ok": False, "formats": 0, "of": len(FORMATS), "error": "; ".join(errors)[:400]}
            write(prev)
        return 0
    prev_formats = prev.get("formats") if isinstance(prev, dict) else None
    changed = (prev.get("changed") or prev.get("updated")) if prev_formats and same_values(prev_formats, formats) else stamp
    write({"updated": stamp, "changed": changed, "provider_updated": max(modified) if modified else None,
           "sync": {"attempted": stamp, "ok": True, "formats": len(formats), "of": len(FORMATS), "error": "; ".join(errors)[:400] if errors else ""},
           "source": "FantasyCalc", "url": "https://www.fantasycalc.com", "terms": "Non-commercial use; credit FantasyCalc with a link",
           "formats": formats})
    print(f"FantasyCalc: {', '.join(f'{k} {len(v)}' for k, v in formats.items())}" + (" · values unchanged since " + changed if changed != stamp else " · values changed"))
    return 0


if __name__ == "__main__":
    sys.exit(main(os.environ.get("MARKET_SRC")))
