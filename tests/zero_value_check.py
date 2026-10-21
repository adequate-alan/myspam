"""A player worth 0 on the board is worth 0 in every league format (Alan, Oct 21).

In 8- and 10-team 1QB the format curve puts AM PPR's deep QBs at 0 and the tier-drop guard (smoothTiers, tierKeep) lifts
the whole Provisional tier to ~11, board values of 0 included: Jalen Hurts (board 0) read 9-12. No guard, floor or lift
may turn a 0 into a positive value.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/zero_value_check.py

Checks:
1. Live boards: every player at 0 on AM PPR (1QB formats) and AM SF PPR TE+ (Superflex formats) is 0 in all 48 formats
   (8/10/12/14 teams x 1QB / Superflex x 0 / 0.5 / 1 PPR x TE premium off / +).
2. Synthetic: the last two players at every position on both boards set to 0 on a scratch copy of the page are 0 in the
   same formats (before the fix several read 1-9 on AM SF PPR TE+ too).
3. Each board's own format still gives exactly its board values, live and synthetic; the count of positive players whose
   value moved with the synthetic zeros is printed (0 today). No page errors.
INDEX=other.html runs it against another copy of the page (one that has SPM.adjFor); without the fix checks 1-2 fail.
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.environ.get("INDEX") or os.path.join(ROOT, "index.html"), encoding="utf-8").read()   # INDEX=old.html: another copy (with SPM.adjFor)
FORMATS = [dict(teams=t, qb=q, rec=r, tep=e) for t in (8, 10, 12, 14) for q in ("1", "sf") for r in (0, 0.5, 1) for e in (0, 0.5)]
NATIVE = {"ppr": dict(teams=12, qb="1", rec=1, tep=0), "sf-tep": dict(teams=12, qb="sf", rec=1, tep=0.5)}
board_of = lambda f: "ppr" if f["qb"] == "1" else "sf-tep"
key = lambda f: f"{f['teams']}-team {'1QB' if f['qb'] == '1' else 'SF'} {f['rec']} PPR TEP {f['tep']}"

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def block_re(name): return re.compile(r"(const " + name + r" = `\n)([\s\S]*?)(\n`;)")
zeroed = set()
def zero_tail(html):
    """the last two players at each position (by position rank) on both boards set to 0"""
    for name in ("RANKINGS_CSV", "RANKINGS_CSV_PPR"):
        m = block_re(name).search(html); rows = list(csv.reader(io.StringIO(m[2]))); h = rows[0]
        c = {k: h.index(k) for k in ("pos", "pos_rank", "value", "sleeper_id")}
        for pos in ("QB", "RB", "WR", "TE"):
            g = sorted([r for r in rows[1:] if r[c["pos"]] == pos], key=lambda r: int(r[c["pos_rank"]]))
            for r in g[-2:]: r[c["value"]] = "0"; zeroed.add(r[c["sleeper_id"]])
        out = io.StringIO(); csv.writer(out, lineterminator="\n").writerows(rows)
        html = html[:m.start(2)] + out.getvalue().rstrip("\n") + html[m.end(2):]
    return html

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
errors = []

def run(br, html):
    pg = br.new_page()
    pg.route(re.compile(r"https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/"); pg.wait_for_function("() => window.SPM && SPM.adjFor", timeout=60000)
    out = {key(f): pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, board_of(f)]) for f in FORMATS}
    nat = {b: pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, b]) for b, f in NATIVE.items()}
    pg.close()
    return out, nat

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    live, live_nat = run(br, SRC)
    syn, syn_nat = run(br, zero_tail(SRC))
    br.close()

for label, res in (("Live boards", live), ("Synthetic zeros", syn)):
    zeros = {k: [r for r in rows if not (r["v"] > 0)] for k, rows in res.items()}
    n = sum(len(z) for z in zeros.values())
    bad = [(k, r["name"], r["adj"]) for k, z in zeros.items() for r in z if r["adj"] != 0]
    ok(n > 0 and not bad, f"{label}: all {n} board-0 player-formats read 0 in {len(res)} formats" + (f"; not 0: {bad[:5]}" if bad else ""))
names = {r["sid"] for rows in syn.values() for r in rows if r["sid"] in zeroed}
ok(len(names) >= 8, f"Synthetic zeros cover every position on both boards ({len(names)} players, the last two at QB / RB / WR / TE)")
for label, nat in (("Live", live_nat), ("Synthetic", syn_nat)):
    off = [(b, r["name"]) for b, rows in nat.items() for r in rows if r["adj"] != round(r["v"])]
    ok(not off, f"{label}: each board's own format gives exactly its board values" + (f"; differ: {off[:5]}" if off else ""))
# a positive player keeps his live value unless he's ranked below a zeroed player at his position (capped under him)
moved = []
for k in live:
    a = {r["sid"]: r for r in live[k]}
    for r in syn[k]:
        if r["sid"] in zeroed or r["sid"] not in a: continue
        if r["adj"] != a[r["sid"]]["adj"] and r["v"] > 0: moved.append((k, r["name"], a[r["sid"]]["adj"], r["adj"]))
print(f"     positive players whose value moved with the synthetic zeros: {len(moved)}" + (f", e.g. {moved[:3]}" if moved else ""))
ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
