"""AM SF PPR TE+ selective alignment with AM PPR (Alan, Oct 21): Superflex mainly changes QB value.

The RB / WR / TE values of AM SF PPR TE+ were fitted toward AM PPR's values converted to the SF board's format (12-team
Superflex, Full PPR, TE premium +0.5) wherever the two boards' tiers agree; SF-only tier boundaries keep their gaps.
Seven tier boundaries moved (RB7 -> RB8, RB22 -> RB23, RB25 | RB26 merged, RB30 -> RB32, RB40 -> RB41, TE5 -> TE6,
TE8 -> TE9; RB18 | RB19 kept). QB values, AM PPR, tag tiers and value-0 players are untouched.

This suite prices the board as it was before (tests/fixtures/sf-alignment/before.csv) and after
(tests/fixtures/sf-alignment/after.csv) with today's code, so later ranking publishes never break it.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/sf_alignment_check.py

Checks, over 108 formats (8 / 10 / 12 / 14 teams x 1QB / Superflex / 2QB x 0 / 0.5 / 1 PPR x TE premium 0 / +0.5 / +1):
1. The fixtures: same players, ranks 1..N, positions in the same order, QB rows and value-0 / tag-tier rows identical,
   the seven tier boundaries exactly as approved.
2. Every QB's league-adjusted value is identical before and after in every Superflex / 2QB format.
3. Every 1QB format (priced on AM PPR) is identical before and after for every player.
4. Board-0 players read 0 in every format; the SF board's own format gives exactly its saved values.
5. The same RB / WR / TE position spot is worth much the same in 1QB and Superflex (same teams, scoring, TE premium):
   the median gap falls from about 9% to at most 5%, the share over 20% to at most half of what it was.
6. Bowers + Concepcion + Jones for Nabers + Burden + Kincaid: the raw % in 12-team Full PPR TEP 1QB and Superflex end
   within 1 point of each other (they were about 10 apart).
7. SPM.formatCheck() passes on the after board. No page errors.
"""
import csv, functools, http.server, io, math, os, re, socketserver, statistics, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sf-alignment")
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
CSV_RE = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
BEFORE = open(os.path.join(FIX, "before.csv"), encoding="utf-8").read().rstrip("\n")
AFTER = open(os.path.join(FIX, "after.csv"), encoding="utf-8").read().rstrip("\n")
FORMATS = [dict(teams=t, qb=q, rec=r, tep=e) for t in (8, 10, 12, 14) for q in ("1", "sf", "2") for r in (0, 0.5, 1) for e in (0, 0.5, 1)]
key = lambda f: f"{f['teams']}-team {dict(zip(('1', 'sf', '2'), ('1QB', 'SF', '2QB')))[f['qb']]} {f['rec']} PPR TEP {f['tep']}"
board_of = lambda f: "ppr" if f["qb"] == "1" else "sf-tep"
BREAKS = {"RB": [2, 4, 8, 11, 18, 23, 32, 41, 51], "TE": [3, 6, 9, 14, 15, 29, 32, 36]}   # first position rank of each tier
TRADE = (("11604", "13298", "4199"), ("11632", "12519", "10236"))   # Bowers, Concepcion, Aaron Jones for Nabers, Burden, Kincaid (Sleeper IDs)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def table(c): return list(csv.DictReader(io.StringIO(c)))
B, A = table(BEFORE), table(AFTER)
bs, as_ = {r["sleeper_id"]: r for r in B}, {r["sleeper_id"]: r for r in A}
ok(set(bs) == set(as_) and sorted(int(r["rank"]) for r in A) == list(range(1, len(A) + 1)), f"Fixtures: the same {len(A)} players, ranks 1..{len(A)}")
ok(all(bs[s]["pos"] == as_[s]["pos"] and bs[s]["pos_rank"] == as_[s]["pos_rank"] for s in bs), "Position ranks unchanged (AM PPR's position order is kept)")
ok(all(bs[s] == {**as_[s], "rank": bs[s]["rank"]} for s in bs if bs[s]["pos"] == "QB"), "QB rows unchanged except their overall rank (the board re-sorts by value)")
ok(all(bs[s]["value"] == as_[s]["value"] and bs[s]["tier"] == as_[s]["tier"] for s in bs if bs[s]["value"] == "0" or int(bs[s]["tier"]) >= 90), "Value-0 and tag-tier players unchanged")
for pos, want in BREAKS.items():
    g = sorted([r for r in A if r["pos"] == pos and int(r["tier"]) < 90], key=lambda r: int(r["pos_rank"]))
    got = [int(b["pos_rank"]) for a, b in zip(g, g[1:]) if a["tier"] != b["tier"]]
    ok(got == want, f"{pos} tier boundaries {got}" + ("" if got == want else f" (expected {want})"))
for pos in ("QB", "RB", "WR", "TE"):
    g = sorted([r for r in A if r["pos"] == pos], key=lambda r: int(r["pos_rank"]))
    v = [int(r["value"]) for r in g]
    ok(all(x > y or x == y == 0 for x, y in zip(v, v[1:])), f"{pos} values strictly down the position")

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
errors = []

def page_with(csv_block):
    m = CSV_RE.search(SRC)
    return SRC[:m.start(2)] + csv_block + SRC[m.end(2):]

def run(br, html, fc=False):
    pg = br.new_page()
    pg.route(re.compile(r"https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    pg.add_init_script("window.__SPM_TEST_HOOKS = true; window.__SPM_ORDER_SYNC_OFF = true;")
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/"); pg.wait_for_function("() => window.SPM && SPM.adjFor", timeout=60000)
    out = {key(f): {r["sid"]: r for r in pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, board_of(f)])} for f in FORMATS}
    nat = pg.evaluate("() => SPM.adjFor({ teams: 12, qb: 'sf', rec: 1, tep: 0.5 }, 'sf-tep')")
    chk = pg.evaluate("async () => await SPM.formatCheck()") if fc else None
    pg.close()
    return out, nat, chk

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    before, _, _ = run(br, page_with(BEFORE))
    after, nat, chk = run(br, page_with(AFTER), fc=True)
    br.close()

sf = [f for f in FORMATS if f["qb"] != "1"]
qb = [(key(f), r["name"], before[key(f)][s]["adj"], r["adj"]) for f in sf for s, r in after[key(f)].items() if r["pos"] == "QB" and r["adj"] != before[key(f)][s]["adj"]]
nqb = sum(1 for f in sf for r in after[key(f)].values() if r["pos"] == "QB")
ok(nqb > 0 and not qb, f"QB league-adjusted values identical before and after: {nqb} QB-formats in {len(sf)} Superflex / 2QB formats" + (f"; changed: {qb[:4]}" if qb else ""))
one = [(key(f), r["name"]) for f in FORMATS if f["qb"] == "1" for s, r in after[key(f)].items() if r["adj"] != before[key(f)][s]["adj"]]
ok(not one, f"Every 1QB format (AM PPR) identical before and after: {sum(len(after[key(f)]) for f in FORMATS if f['qb'] == '1')} player-formats" + (f"; changed: {one[:4]}" if one else ""))
zero = [(k, r["name"], r["adj"]) for k, rows in after.items() for r in rows.values() if not (r["v"] > 0) and r["adj"] != 0]
ok(not zero, "Board-0 players read 0 in every format" + (f"; not 0: {zero[:4]}" if zero else ""))
off = [r["name"] for r in nat if r["adj"] != round(r["v"])]
ok(not off, "The SF board's own format gives exactly its saved values" + (f"; differ: {off[:4]}" if off else ""))

def gaps(res):
    g = []
    for t in (8, 10, 12, 14):
        for rec in (0, 0.5, 1):
            for tep in (0, 0.5, 1):
                a = {(r["pos"], r["pn"]): r["adj"] for r in res[key(dict(teams=t, qb="1", rec=rec, tep=tep))].values()}
                b = {(r["pos"], r["pn"]): r["adj"] for r in res[key(dict(teams=t, qb="sf", rec=rec, tep=tep))].values()}
                g += [abs(math.log(a[k] / b[k])) for pos, n in (("RB", 36), ("WR", 48), ("TE", 16)) for k in ((pos, i) for i in range(1, n + 1))
                      if (a.get(k) or 0) >= 300 and (b.get(k) or 0) >= 300]
    return 100 * (math.exp(statistics.median(g)) - 1), 100 * sum(x > math.log(1.2) for x in g) / len(g)
mb, ob = gaps(before); ma, oa = gaps(after)
ok(ma <= 5 and ma < mb, f"Same RB / WR / TE spot, 1QB vs Superflex: median gap {mb:.1f}% -> {ma:.1f}% (at most 5%)")
ok(oa <= ob / 2, f"Same spot gaps over 20%: {ob:.0f}% -> {oa:.0f}% of spots (at most half)")

def trade_pct(res, f):
    by = {s: r["adj"] for s, r in res[key(f)].items()}
    s = [sum(by[n] for n in side) for side in TRADE]
    return 100 * (s[0] - s[1]) / min(s)
for label, res in (("before", before), ("after", after)):
    q1, q2 = trade_pct(res, dict(teams=12, qb="1", rec=1, tep=0.5)), trade_pct(res, dict(teams=12, qb="sf", rec=1, tep=0.5))
    print(f"     {label}: Bowers + Concepcion + Jones for Nabers + Burden + Kincaid, raw 1QB {q1:+.1f}% · Superflex {q2:+.1f}%")
    if label == "after": ok(abs(q1 - q2) <= 1, f"Named trade: 1QB and Superflex raw % within 1 point ({q1:+.1f}% vs {q2:+.1f}%)")
bad = [c["check"] + ": " + "; ".join(map(str, c.get("values") or []))[:160] for c in chk if not c.get("pass")]
ok(not bad, f"SPM.formatCheck() passes on the after board ({len(chk)} checks)" + (f"; failing: {bad}" if bad else ""))
ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
