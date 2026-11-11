"""An Auto player's step under the player ahead follows the board's own gap when it's under 1% (Alan, Nov 10).

The league layer keeps every Auto player under everyone ranked ahead of him at his position. It used to keep him at least
1% under, so on AM PPR (Nov 10) Herbert, Auto at 214 behind Watson's 215 (Manual, 0.47% apart), read 213 in AM PPR's own
format and SPM.boardCheck() failed "the native format gives back every saved value". Now the step is 1% or the board's own
step when that is smaller; nothing else changed.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/auto_step_check.py

The board is AM PPR as published on Nov 10 (tests/fixtures/auto-step/ppr.csv, main at 51ca807), swapped into today's page,
so a later rankings publish never moves the four QBs these variants edit (Week 10, Nov 11: they left #169-#172).

Variants of AM PPR's tier-13 QBs (Brissett #169, Watson #170, Herbert #171, Mendoza #172, between Andrews 223 and Taylor 206):
  live      the frozen board as published
  a         Auto 218 · Manual 217 · Auto 216 · Manual 215   (Manual/Auto mixed, every gap under 1%)
  b         Manual 218 · Auto 217 · Auto 216 · Manual 215   (Auto behind Auto under 1%)
  c         Auto 218 · Manual 214 · Auto 210 · Manual 207   (every gap over 1%)
Each against the same page with the old 1% step (`old`), in 12 1QB formats plus AM PPR's own:
1. AM PPR's own format gives back every saved value exactly (the old step fails it in live, a and b).
2. Down each position the adjusted values never rise (whole-point ties at the bottom of shallow formats are rounding), and no tail-priced player is worth more than anyone ranked ahead of him.
("Tail-priced" = Auto, or Manual inside a tier that holds Auto players: on AM PPR those are priced together, §9.)
3. The change only relaxes: a value differs from the old step's only for a tail-priced player, only upward, never above the
   player ahead; with every gap over 1% (c) nothing differs at all; on the live board only Herbert differs.
4. Players at 0 on the board stay 0. No page errors.
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
FROZEN = open(os.path.join(ROOT, "tests", "fixtures", "auto-step", "ppr.csv"), encoding="utf-8").read().rstrip("\n")
NEW = "Math.max(0.99, p.value / prevB)"
FORMATS = [dict(teams=t, qb="1", rec=r, tep=e) for t in (8, 10, 12, 14) for r, e in ((0, 0), (1, 0), (1, 0.5))]
NATIVE = dict(teams=12, qb="1", rec=1, tep=0)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

PPR_RE = re.compile(r"(const RANKINGS_CSV_PPR = `\n)([\s\S]*?)(\n`;)")
def rows_of(text):
    r = list(csv.reader(io.StringIO(text))); return r[0], r[1:]
def write(h, rows):
    out = io.StringIO(); w = csv.writer(out, lineterminator="\n"); w.writerow(h); w.writerows(rows); return out.getvalue().rstrip("\n")

_m = PPR_RE.search(SRC); SRC = SRC[:_m.start(2)] + FROZEN + SRC[_m.end(2):]   # the frozen Nov 10 board
h, live = rows_of(PPR_RE.search(SRC)[2])
C = {k: h.index(k) for k in ("player", "pos", "rank", "tier", "value", "source", "sleeper_id")}
NAMES = ["Jacoby Brissett", "Deshaun Watson", "Justin Herbert", "Fernando Mendoza"]
byname = {r[C["player"]]: r for r in live}
ok(all(n in byname for n in NAMES) and [int(byname[n][C["rank"]]) for n in NAMES] == [169, 170, 171, 172],
   "The four tier-13 QBs sit at #169-#172 on AM PPR")

def variant(spec):
    """the page with the four QBs' (source, value) set from spec; their ranks and everyone else unchanged"""
    rows = [list(r) for r in live]
    for r in rows:
        if r[C["player"]] in spec: r[C["source"]], r[C["value"]] = spec[r[C["player"]]][0], str(spec[r[C["player"]]][1])
    m = PPR_RE.search(SRC)
    return SRC[:m.start(2)] + write(h, rows) + SRC[m.end(2):], rows

SPECS = {
    "live": None,
    "a": dict(zip(NAMES, [("auto", 218), ("manual", 217), ("auto", 216), ("manual", 215)])),
    "b": dict(zip(NAMES, [("manual", 218), ("auto", 217), ("auto", 216), ("manual", 215)])),
    "c": dict(zip(NAMES, [("auto", 218), ("manual", 214), ("auto", 210), ("manual", 207)])),
}
ok(SRC.count(NEW) == 1, "The relaxed step is in the page once (the old one is built from it)")

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
errors = []

def open_page(br, html):
    pg = br.new_page()
    pg.route(re.compile(r"https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/"); pg.wait_for_function("() => window.SPM && SPM.adjFor", timeout=60000)
    return pg
def key(f): return f"{f['teams']}-team 1QB {f['rec']} PPR TEP {f['tep']}"

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(args=["--no-sandbox"], **kw)
    for vname, spec in SPECS.items():
        html, rows = (SRC, live) if spec is None else variant(spec)
        # on AM PPR every player in a tier that holds Auto players is priced with them (provTierSet, Oct 21), Manual or not
        tail_tiers = {(r[C["pos"]], r[C["tier"]]) for r in rows if r[C["source"]] == "auto"}
        src = {r[C["sleeper_id"]]: "auto" if (r[C["pos"]], r[C["tier"]]) in tail_tiers else "manual" for r in rows}
        rank = {r[C["sleeper_id"]]: int(r[C["rank"]]) for r in rows}
        got = {}
        for tag, page_html in (("new", html), ("old", html.replace(NEW, "0.99"))):
            pg = open_page(br, page_html)
            got[tag] = {key(f): pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, "ppr"]) for f in FORMATS + [NATIVE]}
            pg.close()
        nk = key(NATIVE)
        off = [r["name"] for r in got["new"][nk] if r["adj"] != round(r["v"])]
        ok(not off, f"[{vname}] AM PPR's own format gives back every saved value ({len(got['new'][nk])} players)" + (f"; differ: {off[:5]}" if off else ""))
        old_off = [f"{r['name']} {r['adj']} (board {round(r['v'])})" for r in got["old"][nk] if r["adj"] != round(r["v"])]
        if vname != "c": ok(bool(old_off), f"[{vname}] the old 1% step fails it: {', '.join(old_off[:4])}")
        rises, over, changed, bad, zeros = [], [], set(), [], []
        for k in got["new"]:
            new = got["new"][k]; old = {r["sid"]: r["adj"] for r in got["old"][k]}
            for pos in ("QB", "RB", "WR", "TE"):
                ps = sorted([r for r in new if r["pos"] == pos], key=lambda r: rank[r["sid"]])
                top = float("inf")
                for a, b in zip(ps, ps[1:]):
                    if b["adj"] > a["adj"]: rises.append(f"{k}: {a['name']} {a['adj']} -> {b['name']} {b['adj']}")
                for r in ps:
                    if src[r["sid"]] == "auto" and r["adj"] > top: over.append(f"{k}: {r['name']} {r['adj']} > {top}")
                    top = min(top, r["adj"])
                prev = None
                for r in ps:
                    o = old.get(r["sid"])
                    if o is not None and o != r["adj"]:
                        changed.add(r["name"])
                        if src[r["sid"]] != "auto" or r["adj"] < o or (prev and r["adj"] > prev["adj"]): bad.append(f"{k}: {r['name']} {o} -> {r['adj']}")
                    prev = r
            zeros += [f"{k}: {r['name']} {r['adj']}" for r in new if round(r["v"]) == 0 and r["adj"] != 0]
        ok(not rises, f"[{vname}] adjusted values never rise down a position in {len(got['new'])} formats" + (f": {rises[:3]}" if rises else ""))
        ok(not over, f"[{vname}] no tail-priced player is worth more than anyone ranked ahead of him at his position" + (f": {over[:3]}" if over else ""))
        ok(not bad, f"[{vname}] every value that differs from the old step is a tail-priced player's, raised, still under the player ahead" + (f": {bad[:3]}" if bad else ""))
        if vname == "c": ok(not changed, f"[c] every gap over 1%: no value differs from the old step" + (f" ({sorted(changed)})" if changed else ""))
        elif vname == "live": ok(changed == {"Justin Herbert"}, f"[live] only Herbert differs from the old step ({sorted(changed)})")
        else: print(f"INFO [{vname}] differ from the old step: {sorted(changed)}")
        ok(not zeros, f"[{vname}] players at 0 on the board stay 0" + (f": {zeros[:3]}" if zeros else ""))
    br.close()

ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
