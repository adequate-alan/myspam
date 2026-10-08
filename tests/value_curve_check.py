"""Value-curve safeguards on the SPAM Board (Alan, Oct 7). Warnings only on the site; this test fails on the serious ones.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/value_curve_check.py

Prints every SPM.valueCheck() warning (formula cliffs, rank gaps, tier gaps, tier sizes and spreads), then fails on:
1. any model value worth more than someone ranked ahead of him (overall or at his position);
2. a tier boundary with almost no value gap (< 3%);
2b. tiers split down a position (a ladder tier that comes back after a lower one: tiers stay in one piece), or a lower
   tier worth more than the tier above it (every player of a tier above the best of the next tier at his position);
3. a formula cliff of more than 30% where the player ahead is worth 1,000+ (drops between neighbours close together on
   the overall board; drops across a big gap in your overall order are listed, not failed);
4. a stored value that doesn't show exactly as stored (values are state since Oct 12). No page errors.
A one-player tier is allowed (Alan, Oct 12: Lamar Jackson alone in QB Tier 2 is intentional): it's listed as
information for review, never a failure.
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", SRC, re.S).group(1).strip())))
stored = {r["sleeper_id"]: int(r["value"]) for r in rows if r["value"].strip() and r["sleeper_id"]}

def serve():
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(c, msg):
    print(("PASS " if c else "FAIL ") + msg)
    if not c: failures.append(msg)

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    pg = br.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com))/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/?debug=1#rankings"); pg.wait_for_selector("#rank-body tr.player")
    W = pg.evaluate("() => SPM.valueCheck()")
    snap = pg.evaluate("() => SPM.rankingSnapshot()")
    pos_by_sid = {r["sleeper_id"]: r["pos"] for r in rows if r["sleeper_id"]}
    pos_of = {tuple(a): pos_by_sid.get(sid) for sid, a in snap.items()}
    snap = {sid: tuple(a) for sid, a in snap.items()}
    print(f"{len(W)} warning(s):")
    for w in W: print(f"   [{w['kind']}] {w['text']}")

    ok(not [w for w in W if w["kind"] == "order"], "Values never rise down the overall or position order")
    ok(not [w for w in W if "boundary gap" in w["text"]], "Every tier boundary has a real value gap (3%+)")
    single = [w["text"] for w in W if "has one player" in w["text"]]
    print(f"INFO {len(single)} one-player tier(s), allowed (for review only): {single}")
    split, inverted = [], []
    tag = lambda t: t == "" or t is None or int(t) >= 90
    for pos in ("QB", "RB", "WR", "TE"):
        L = sorted([a for a in snap.values() if a[0] is not None and pos_of.get(a) == pos], key=lambda a: a[1])
        ladder = [a for a in L if not tag(a[2])]
        seen, last = set(), None
        for a in ladder:
            t = int(a[2])
            if t != last and t in seen: split.append(f"{pos} Tier {t} returns at {pos}{a[1]}")
            if last is not None and t < last: split.append(f"{pos}{a[1]} is in Tier {t} below Tier {last}")
            seen.add(t); last = t
        tiers = {}
        for a in ladder: tiers.setdefault(int(a[2]), []).append(a[3])
        ks = sorted(tiers)
        for hi, lo in zip(ks, ks[1:]):
            if max(tiers[lo]) >= min(tiers[hi]) and max(tiers[lo]) > 0: inverted.append(f"{pos} Tier {lo} (best {max(tiers[lo])}) not below Tier {hi} (lowest {min(tiers[hi])})")
    ok(not split, f"Tiers stay in one piece down every position {split[:3]}")
    ok(not inverted, f"No tier is worth more than the tier above it at its position {inverted[:3]}")
    big = []
    for w in W:
        m = re.search(r"value drop = ([\d.]+)%.*?\(.*? ([\d,]+) → ", w["text"])
        if w["kind"] == "cliff" and m and float(m.group(1)) > 30 and int(m.group(2).replace(",", "")) >= 1000: big.append(w["text"])
    ok(not big, f"No formula cliff over 30% above 1,000 {big[:2]}")
    wrong = [(sid, v, snap[sid][3]) for sid, v in stored.items() if sid in snap and snap[sid][3] != v]
    ok(not wrong, f"Stored values show exactly as stored ({len(stored)} players) {wrong[:3]}")
    ok(pg.locator("#eb-vcheck").is_visible(), "?debug shows the value-check button in the editor bar")
    ok(not errs, f"No page errors {errs[:2]}")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll value-curve checks passed.")
sys.exit(1 if failures else 0)
