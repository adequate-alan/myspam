"""Value-curve safeguards on the SPAM Board (Alan, Oct 7). Warnings only on the site; this test fails on the serious ones.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/value_curve_check.py

Prints every SPM.valueCheck() warning (formula cliffs, rank gaps, tier gaps, tier sizes and spreads), then fails on:
1. any model value worth more than someone ranked ahead of him (overall or at his position);
2. a tier boundary with almost no value gap (< 3%), or a one-player tier below a position's Tier 1;
3. a formula cliff of more than 30% where the player ahead is worth 1,000+ (drops between neighbours close together on
   the overall board; drops across a big gap in your overall order are listed, not failed);
4. a stored value that doesn't show exactly as stored (values are state since Oct 12). No page errors.
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
    print(f"{len(W)} warning(s):")
    for w in W: print(f"   [{w['kind']}] {w['text']}")

    ok(not [w for w in W if w["kind"] == "order"], "Values never rise down the overall or position order")
    ok(not [w for w in W if "boundary gap" in w["text"]], "Every tier boundary has a real value gap (3%+)")
    ok(not [w for w in W if "has one player" in w["text"]], "No one-player tiers below Tier 1")
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
