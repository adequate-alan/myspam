"""Manual / Auto inside AM PPR's Provisional tier never changes league pricing (Alan, Oct 21).

On AM PPR (provisionalAuto) the tiers holding Auto players are priced as one tail: a player moved there (which makes him
Manual) is priced like the Auto players around him. Before, 14-team 1QB read Cam Ward (QB31, Auto) 94 -> Jalon Daniels
(QB32, Manual) 12, -87% where the board has 25 -> 12 (-52%), because Daniels took a tier factor (~1x) from the few
Manual players in the tier while the Auto players beside him took Tier 11's (~3.8x).

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/provisional_pricing_check.py

Checks:
1. Classification never changes pricing: the live AM PPR block, the same block with every Provisional-tier player Auto,
   and the same block with seven more Provisional players (QB / RB / WR / TE, top, middle and bottom of the tier) made
   Manual give identical league-adjusted values for every player in all 24 1QB formats (8/10/12/14 teams, 0/0.5/1 PPR,
   TE premium off / +). That includes the projection ranks behind the league layer's tier pricing, which used to be
   grouped by Manual / Auto: moving a player in or out of Manual inside Provisional shifted the projection rank of the
   other Manual players and moved values up to ~2% (20 points at ~1,100 in 14-team 1QB) at unrelated spots.
2. No artificial gap: in every 14-team 1QB format each Provisional QB worth 5+ on the board keeps at least 85% of the
   board's own step from the QB ahead of him (Ward -> Daniels reads 94 -> 45, -52%, like the board).
3. A real positional move inside Provisional in the editor (AM PPR edited, Mariota QB34 -> QB28, which makes him Manual)
   leaves check 2 holding and gives the same values as the same order with him Auto.
4. Scope: on AM SF PPR TE+ the rule doesn't apply (making one of its Manual players in a mixed tier Auto still changes its
   values), and AM PPR's own format still gives exactly its board values. No page errors.
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
FORMATS = [dict(teams=t, qb="1", rec=r, tep=e) for t in (8, 10, 12, 14) for r in (0, 0.5, 1) for e in (0, 0.5)]
NATIVE = dict(teams=12, qb="1", rec=1, tep=0)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def block_re(name): return re.compile(r"(const " + name + r" = `\n)([\s\S]*?)(\n`;)")
PPR_RE, SF_RE = block_re("RANKINGS_CSV_PPR"), block_re("RANKINGS_CSV")
def rows_of(text):
    r = list(csv.reader(io.StringIO(text))); return r[0], r[1:]
def write(h, rows):
    out = io.StringIO(); w = csv.writer(out, lineterminator="\n"); w.writerow(h); w.writerows(rows); return out.getvalue().rstrip("\n")
def with_sources(rx, fn):
    """the page with one board's source column rewritten by fn(header, row) -> new source"""
    m = rx.search(SRC); h, rows = rows_of(m[2]); si = h.index("source")
    for r in rows: r[si] = fn(h, r)
    return SRC[:m.start(2)] + write(h, rows) + SRC[m.end(2):]

h, ppr = rows_of(PPR_RE.search(SRC)[2])
col = {k: h.index(k) for k in ("player", "pos", "pos_rank", "tier", "source", "sleeper_id")}
prov = {(r[col["pos"]], r[col["tier"]]) for r in ppr if r[col["source"]] == "auto" and int(r[col["tier"]]) < 90}
in_prov = lambda r: (r[col["pos"]], r[col["tier"]]) in prov
# the live board may or may not have Manual players inside a Provisional tier (it depends on Alan's latest list; Oct 28:
# none), so the case under test is built below ("more Manual") and the live count is information only
print(f"INFO Manual players inside a Provisional tier on the live board: {sum(1 for r in ppr if r[col['source']] == 'manual' and in_prov(r))}")
# seven more Manual players spread over the tier: first, middle and last Auto player at QB, plus one RB, WR, TE; only from a
# position's Provisional tier that keeps Auto players after the picks (a tier left with no Auto player at his position is an
# ordinary Manual tier, priced as one, by design: provTierSet is per position and tier)
from collections import Counter
autos = Counter((r[col["pos"]], r[col["tier"]]) for r in ppr if r[col["source"]] == "auto" and in_prov(r))
pick = set()
by_pos = {}
for r in sorted(ppr, key=lambda r: (r[col["pos"]], int(r[col["pos_rank"]]))):
    if r[col["source"]] == "auto" and in_prov(r) and autos[(r[col["pos"]], r[col["tier"]])] >= 4: by_pos.setdefault(r[col["pos"]], []).append(r[col["sleeper_id"]])
q = by_pos["QB"]; pick |= {q[0], q[len(q) // 2], q[-1]}
for pos in ("RB", "WR", "TE"):
    if by_pos.get(pos): pick |= {by_pos[pos][0], by_pos[pos][len(by_pos[pos]) // 2]}
ok(len(pick) >= 7 and any(r[col["sleeper_id"]] in pick for r in ppr), f"The case under test: {len(pick)} Auto players made Manual inside Provisional tiers that keep Auto players")
VARIANTS = {
    "live": SRC,
    "all Auto": with_sources(PPR_RE, lambda h_, r: "auto" if in_prov(r) else r[col["source"]]),
    "more Manual": with_sources(PPR_RE, lambda h_, r: "manual" if r[col["sleeper_id"]] in pick else r[col["source"]]),
}
# AM SF PPR TE+: one Manual player ranked under an Auto player of his own tier, made Auto
sh, sf = rows_of(SF_RE.search(SRC)[2])
sc = {k: sh.index(k) for k in ("pos", "pos_rank", "tier", "source", "sleeper_id", "player")}
seen, sf_target = set(), None
for r in sorted(sf, key=lambda r: (r[sc["pos"]], int(r[sc["pos_rank"]]))):
    k = (r[sc["pos"]], r[sc["tier"]])
    if r[sc["source"]] == "auto": seen.add(k)
    elif k in seen and r[sc["pos"]] == "WR" and sf_target is None: sf_target = r[sc["sleeper_id"]]
m = SF_RE.search(SRC); rows = [list(r) for r in sf]
for r in rows:
    if r[sc["sleeper_id"]] == sf_target: r[sc["source"]] = "auto"
SF_VARIANT = SRC[:m.start(2)] + write(sh, rows) + SRC[m.end(2):]

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
errors = []

def open_page(br, html, edit_board=None):
    pg = br.new_page()
    pg.route(re.compile(r"https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    init = "window.__SPM_TEST_HOOKS = true;" + (f" try {{ localStorage.setItem('spm_edit_board', '{edit_board}'); }} catch (e) {{}}" if edit_board else "")
    pg.add_init_script(init)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/"); pg.wait_for_function("() => window.SPM && SPM.adjFor", timeout=60000)
    return pg

def values(pg, f, bid="ppr"): return pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, bid])
def key(f): return f"{f['teams']}-team 1QB {f['rec']} PPR TEP {f['tep']}"

def gaps(rows):
    """Provisional QBs whose league step from the QB ahead is under 85% of the board's own step"""
    qbs = sorted([r for r in rows if r["pos"] == "QB"], key=lambda r: r["pn"]); bad = []
    for a, b in zip(qbs, qbs[1:]):
        if ("QB", b["tier"]) not in prov or a["v"] < 5 or b["v"] < 5 or not a["adj"]: continue
        if b["adj"] / a["adj"] < 0.85 * b["v"] / a["v"]: bad.append(f"{a['name']} {a['adj']} -> {b['name']} {b['adj']} (board {a['v']} -> {b['v']})")
    return bad

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    got = {}
    for name, html in VARIANTS.items():
        pg = open_page(br, html)
        got[name] = {key(f): {r["sid"]: r["adj"] for r in values(pg, f)} for f in FORMATS}
        if name == "live":
            live_rows = {key(f): values(pg, f) for f in FORMATS if f["teams"] == 14}
            nat = values(pg, NATIVE)
            off = [r["name"] for r in nat if r["adj"] != round(r["v"])]
            ok(not off, f"AM PPR's own format gives exactly its board values ({len(nat)} players){'; differ: ' + ', '.join(off[:5]) if off else ''}")
        pg.close()
    for name in ("all Auto", "more Manual"):
        diff = [(k, sid) for k in got["live"] for sid in got["live"][k] if abs(got["live"][k][sid] - got[name][k].get(sid, -99)) > 0]
        ok(not diff, f"Classification never changes pricing: live board = {name} exactly in all {len(FORMATS)} 1QB formats" + (f" ({len(diff)} differ, e.g. {diff[:3]})" if diff else ""))
    for k, rows in live_rows.items():
        bad = gaps(rows)
        ok(not bad, f"{k}: every Provisional QB keeps the board's step from the QB ahead" + (": " + "; ".join(bad[:3]) if bad else ""))
    ward = {r["name"]: r["adj"] for r in live_rows[key(dict(teams=14, rec=0, tep=0))]}
    print(f"     14-team 1QB 0 PPR: Ward {ward.get('Cam Ward')} -> Daniels {ward.get('Jalon Daniels')}")

    # a real move inside Provisional with AM PPR as the edited board
    pg = open_page(br, SRC, edit_board="ppr")
    pg.wait_for_function("() => SPM.edit && SPM.edit.board().length > 0", timeout=30000)
    me = pg.evaluate("() => SPM.edit.board().find(p => p.name === 'Marcus Mariota')")
    before = me["posNum"]
    pg.evaluate("id => SPM.edit.movePlayer(id, 28)", me["id"])
    after = pg.evaluate("() => SPM.edit.board().find(p => p.name === 'Marcus Mariota')")
    ok(after["posNum"] == 28 and after["source"] == "manual", f"Editor move: Mariota QB{before} -> QB{after['posNum']}, now {after['source']}")
    f14 = dict(teams=14, rec=0, tep=0)
    moved = values(pg, f14)
    bad = gaps(moved)
    ok(not bad, "After the move every Provisional QB keeps the board's step from the QB ahead" + (": " + "; ".join(bad[:3]) if bad else ""))
    draft = pg.evaluate("() => SPM.edit.draft()")
    pg.close()
    # the same order with every Provisional player Auto, as a published board
    dh, drows = rows_of(draft); dsi, dt, dp = dh.index("source"), dh.index("tier"), dh.index("pos")
    for r in drows:
        if (r[dp], r[dt]) in prov: r[dsi] = "auto"
    m = PPR_RE.search(SRC)
    pg = open_page(br, SRC[:m.start(2)] + write(dh, drows) + SRC[m.end(2):])
    ref = {r["sid"]: r["adj"] for r in values(pg, f14)}
    pg.close()
    diff = [r["name"] for r in moved if abs(ref.get(r["sid"], -99) - r["adj"]) > 0]
    ok(not diff, "After the move the values equal the same order with him Auto exactly (14-team 1QB 0 PPR)" + (f": {diff[:5]}" if diff else ""))

    # scope: AM SF PPR TE+ keeps per-status pricing
    f14sf = dict(teams=14, qb="sf", rec=1, tep=0)
    pg = open_page(br, SRC); a = {r["sid"]: r["adj"] for r in values(pg, f14sf, "sf-tep")}; pg.close()
    pg = open_page(br, SF_VARIANT); b = {r["sid"]: r["adj"] for r in values(pg, f14sf, "sf-tep")}; pg.close()
    ok(sf_target and a != b, "AM SF PPR TE+ is out of scope: making one of its Manual players in a mixed tier Auto still changes its values")
    br.close()

ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
