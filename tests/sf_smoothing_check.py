"""AM SF PPR TE+ value smoothing inside its own tiers (Alan, Nov 14): values only, the tiers stay as they are.

AM PPR's value method applied to the SF board's own positional tiers: every all-Manual ladder tier keeps its level
(geometric mean) with one even % step between tiermates, and every tier boundary steps at least 3% and at least twice
the average inner step of the two tiers beside it. Rankings inside a position, tier boundaries, tier names, Manual /
Auto, value-0 players, tag tiers, one-player tiers, the deep tail tiers that hold Auto players and TE Tier 6 (TE15-28,
Alan: leave it) are untouched; the overall board re-sorts by value. AM PPR is untouched.

This suite prices the board before (tests/fixtures/sf-smoothing/before.csv) and after (after.csv) with today's code,
with AM PPR frozen as published that day (ppr.csv), so later ranking publishes never break it.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/sf_smoothing_check.py

1. The fixtures: same players, position ranks, tiers, tier names and sources; exactly 143 values and 96 overall ranks
   differ; value-0, tag-tier and Auto players, tiers holding Auto players, one-player tiers and TE Tier 6 unchanged;
   smoothed tiers step evenly, keep their level within 2%, position totals within 0.25%; boundaries follow the rule;
   the three boundaries Alan accepted read as approved.
2. Over 108 formats (8 / 10 / 12 / 14 teams x 1QB / Superflex / 2QB x 0 / 0.5 / 1 PPR x TE premium 0 / +0.5 / +1): the SF
   board's own format gives exactly the saved values; every 1QB format (AM PPR) is identical before and after; board-0
   players read 0; values never rise down a position; each position's weekly starters keep their total within 1.5% in
   every Superflex / 2QB format (value moves inside tiers, not between positions).
3. Representative trades in the board's own format, pinned before and after (the smoothing is not cosmetic: Jacobs for
   Bo Nix +6.8% -> +0.9%).
4. SPM.formatCheck() and SPM.boardCheck() pass on the after board. The published history event equals the fixtures'
   differences. No page errors.
"""
import csv, functools, http.server, io, json, math, os, re, socketserver, statistics, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sf-smoothing")
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
CSV_RE = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
PPR_RE = re.compile(r"(const RANKINGS_CSV_PPR = `\n)([\s\S]*?)(\n`;)")
PPR, BEFORE, AFTER = (open(os.path.join(FIX, n), encoding="utf-8").read().rstrip("\n") for n in ("ppr.csv", "before.csv", "after.csv"))
FORMATS = [dict(teams=t, qb=q, rec=r, tep=e) for t in (8, 10, 12, 14) for q in ("1", "sf", "2") for r in (0, 0.5, 1) for e in (0, 0.5, 1)]
key = lambda f: f"{f['teams']}-team {dict(zip(('1', 'sf', '2'), ('1QB', 'SF', '2QB')))[f['qb']]} {f['rec']} PPR TEP {f['tep']}"
board_of = lambda f: "ppr" if f["qb"] == "1" else "sf-tep"
EVENT_TS = "2026-11-14T07:20:00.000Z"
N_VALUES, N_RANKS = 143, 96
ACCEPTED = (("Rhamondre Stevenson", "Quinshon Judkins", 29.5), ("TreVeyon Henderson", "Corey Kiner", 41.1), ("Keenan Allen", "Josh Downs", 43.8))
# side A, side B; pinned below (PINS) as raw % before and after (+ = side A ahead) and valueRead's verdict kind, in the board's own format
TRADES = (
    (("Josh Jacobs",), ("Bo Nix",)),
    (("Bryce Young",), ("Garrett Wilson",)),
    (("Sam LaPorta",), ("Breece Hall",)),
    (("George Kittle",), ("Zay Flowers",)),
    (("Malik Willis", "Blake Corum"), ("Geno Smith",)),
    (("Joe Burrow",), ("Christian McCaffrey",)),
    (("Brock Bowers", "KC Concepcion Jr.", "Aaron Jones Sr."), ("Malik Nabers", "Luther Burden III", "Dalton Kincaid")),
)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def table(c): return list(csv.DictReader(io.StringIO(c)))
B, A = table(BEFORE), table(AFTER)
bs, as_ = {r["sleeper_id"]: r for r in B}, {r["sleeper_id"]: r for r in A}
val = lambda r: int(r["value"])
ok(set(bs) == set(as_) and sorted(int(r["rank"]) for r in A) == list(range(1, len(A) + 1)), f"Fixtures: the same {len(A)} players, ranks 1..{len(A)}")
same = lambda cols: all(bs[s].get(c) == as_[s].get(c) for s in bs for c in cols)
ok(same(("player", "pos", "pos_rank", "tier", "tier_name", "source", "team")), "Position ranks, tiers, tier names and Manual / Auto unchanged for every player")
ok(all({k: v for k, v in bs[s].items() if k not in ("rank", "value")} == {k: v for k, v in as_[s].items() if k not in ("rank", "value")} for s in bs), "Only the rank and value columns differ")
chg = {s for s in bs if bs[s]["value"] != as_[s]["value"]}
mov = {s for s in bs if bs[s]["rank"] != as_[s]["rank"]}
ok(len(chg) == N_VALUES and len(mov) == N_RANKS, f"{len(chg)} values and {len(mov)} overall ranks differ (reviewed: {N_VALUES} and {N_RANKS})")
v = [val(r) for r in sorted(A, key=lambda r: int(r["rank"]))]
ok(all(x > y or x == y == 0 for x, y in zip(v, v[1:])), "Values strictly down the overall board (only 0s tie)")
tiers = {}
for r in sorted(A, key=lambda r: int(r["pos_rank"])): tiers.setdefault((r["pos"], int(r["tier"])), []).append(r)
fixed = {k for k, g in tiers.items() if k[1] >= 90 or len(g) == 1 or any(r["source"] == "auto" for r in g) or any(val(r) == 0 for r in g) or k == ("TE", 6)}
bad = sorted({as_[s]["player"] for s in chg if (as_[s]["pos"], int(as_[s]["tier"])) in fixed})
ok(not bad, f"Value-0, tag-tier and one-player tiers, tiers holding Auto players and TE Tier 6 unchanged ({sum(len(tiers[k]) for k in fixed)} players)" + (f"; changed: {bad[:5]}" if bad else ""))
ok(not any(as_[s]["source"] == "auto" for s in chg), "No Auto player's value changed")
smoothed = [k for k, g in tiers.items() if any(r["sleeper_id"] in chg for r in g)]
gm = lambda rows, src: math.exp(statistics.mean(math.log(val(src[r["sleeper_id"]])) for r in rows))
steps = lambda g: [math.log(val(a) / val(b)) for a, b in zip(g, g[1:])]
uneven = [(k, round(100 * (max(steps(tiers[k])) - min(steps(tiers[k]))), 2)) for k in smoothed if max(steps(tiers[k])) - min(steps(tiers[k])) > 0.006]
ok(not uneven, f"{len(smoothed)} smoothed tiers step evenly (inner steps within 0.6 points of each other, whole-number rounding)" + (f"; uneven: {uneven}" if uneven else ""))
drift = [(k, round(100 * (gm(tiers[k], as_) / gm(tiers[k], bs) - 1), 2)) for k in smoothed if abs(math.log(gm(tiers[k], as_) / gm(tiers[k], bs))) > 0.02]
ok(not drift, "Every smoothed tier keeps its level: geometric mean within 2% of before" + (f"; moved: {drift}" if drift else ""))
for pos in ("QB", "RB", "WR", "TE"):
    tb, ta = sum(val(r) for r in B if r["pos"] == pos), sum(val(r) for r in A if r["pos"] == pos)
    ok(abs(ta / tb - 1) <= 0.0025, f"{pos} total value {tb:,} -> {ta:,} ({100 * (ta / tb - 1):+.2f}%, within 0.25%)")
    ks = [k for k in tiers if k[0] == pos and k[1] < 90]
    for a, b in zip(ks, ks[1:]):
        if a not in smoothed and b not in smoothed: continue
        gap = math.log(val(tiers[a][-1]) / val(tiers[b][0]))
        need = max(-math.log(0.97), statistics.mean(steps(tiers[a])) + statistics.mean(steps(tiers[b]))) if a in smoothed and b in smoothed else -math.log(0.97)
        # 0.5 point of room: whole-number values, and a smoothed value nudged a point off an unchanged neighbour's
        if gap < need - 0.005: ok(False, f"{pos} Tier {a[1]} | Tier {b[1]} boundary {100 * (1 - math.exp(-gap)):.1f}% is under the rule (3% and twice the average inner step)")
ok(not any("boundary" in f for f in failures), "Every boundary beside a smoothed tier steps at least 3%, and at least twice the average inner step when both tiers are smoothed")
by_name = {r["player"]: r for r in A}
for a, b, want in ACCEPTED:
    got = 100 * (1 - val(by_name[b]) / val(by_name[a]))
    ok(abs(got - want) <= 0.1, f"Accepted boundary {a} -> {b}: {got:.1f}% (approved {want}%)")

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
errors = []

def page_with(csv_block):
    m = PPR_RE.search(SRC)
    src = SRC[:m.start(2)] + PPR + SRC[m.end(2):]
    m = CSV_RE.search(src)
    return src[:m.start(2)] + csv_block + src[m.end(2):]

TRADE_JS = """(T) => (async () => {
  const rows = await SPM.adjFor({ teams: 12, qb: 'sf', rec: 1, tep: 0.5 }, 'sf-tep');
  const by = Object.fromEntries(rows.map(r => [r.name, r.adj]));
  const top = rows.map(r => r.adj || 0).sort((a, b) => b - a).slice(0, 9 * 12);
  const floor = top.reduce((a, b) => a + b, 0) / top.length;   // an average starter in the format, as valueFloor
  return T.map(([A, B]) => {
    const side = ns => ns.map(n => { if (by[n] == null) throw new Error('no player ' + n); return { value: by[n] }; });
    const keep = LEAGUE_DEPTH; LEAGUE_DEPTH = 1;
    const vr = valueRead(tradeModel(side(A), side(B)), floor); LEAGUE_DEPTH = keep;
    return { raw: vr.raw, adj: vr.adj, kind: vr.kind };
  });
})()"""

def run(br, html, full=False):
    pg = br.new_page()
    pg.route(re.compile(r"https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    pg.add_init_script("window.__SPM_TEST_HOOKS = true; window.__SPM_ORDER_SYNC_OFF = true;")
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/"); pg.wait_for_function("() => window.SPM && SPM.adjFor", timeout=60000)
    out = {key(f): {r["sid"]: r for r in pg.evaluate("([f, b]) => SPM.adjFor(f, b)", [f, board_of(f)])} for f in FORMATS}
    nat = pg.evaluate("() => SPM.adjFor({ teams: 12, qb: 'sf', rec: 1, tep: 0.5 }, 'sf-tep')")
    trades = pg.evaluate(TRADE_JS, [list(map(list, t)) for t in TRADES])
    fc = pg.evaluate("async () => await SPM.formatCheck()") if full else None
    bc = pg.evaluate("async () => await SPM.boardCheck()") if full else None
    pg.close()
    return out, nat, trades, fc, bc

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    before, natb, tb, _, _ = run(br, page_with(BEFORE))
    after, nat, ta, fc, bc = run(br, page_with(AFTER), full=True)
    br.close()

sf = [f for f in FORMATS if f["qb"] != "1"]
for label, rows, src in (("before", natb, bs), ("after", nat, as_)):
    off = [r["name"] for r in rows if r["adj"] != val(src[r["sid"]])]
    ok(len(rows) == len(A) and not off, f"The SF board's own format (12-team Superflex, Full PPR, TE premium +0.5) gives exactly the saved values, {label}: {len(rows)} players" + (f"; differ: {off[:4]}" if off else ""))
one = [(key(f), r["name"]) for f in FORMATS if f["qb"] == "1" for s, r in after[key(f)].items() if r["adj"] != before[key(f)][s]["adj"]]
ok(not one, f"Every 1QB format (AM PPR) identical before and after: {sum(len(after[key(f)]) for f in FORMATS if f['qb'] == '1')} player-formats" + (f"; changed: {one[:4]}" if one else ""))
zero = [(k, r["name"], r["adj"]) for k, rows in after.items() for r in rows.values() if not (r["v"] > 0) and r["adj"] != 0]
ok(not zero, "Board-0 players read 0 in every format" + (f"; not 0: {zero[:4]}" if zero else ""))
inv = []
for f in sf:
    for pos in ("QB", "RB", "WR", "TE"):
        g = sorted((r for r in after[key(f)].values() if r["pos"] == pos), key=lambda r: r["pn"])
        inv += [(key(f), a["name"], a["adj"], b["name"], b["adj"]) for a, b in zip(g, g[1:]) if b["adj"] > a["adj"]]
ok(not inv, f"League-adjusted values never rise down a position: {len(sf)} Superflex / 2QB formats" + (f"; {inv[:3]}" if inv else ""))
# the smoothing moves value inside tiers, not between positions: each position's weekly starters are worth about the same
worst = (0, "")
for f in sf:
    for pos, n in (("QB", 2), ("RB", 2.5), ("WR", 3.5), ("TE", 1)):
        top = lambda res: sum(sorted((r["adj"] for r in res[key(f)].values() if r["pos"] == pos), reverse=True)[:round(n * f["teams"])])
        d = abs(top(after) / top(before) - 1)
        if d > worst[0]: worst = (d, f"{pos} in {key(f)}")
ok(worst[0] <= 0.015, f"Each position's starters keep their total league-adjusted value within 1.5% in every Superflex / 2QB format (largest {100 * worst[0]:.2f}%, {worst[1]})")
big = sorted(((abs(math.log(r["adj"] / before[key(f)][s]["adj"])), r["name"], key(f), before[key(f)][s]["adj"], r["adj"]) for f in sf for s, r in after[key(f)].items()
              if r["adj"] >= 300 and before[key(f)][s]["adj"] >= 300), reverse=True)[:5]
print("     largest league-adjusted changes (300+ points): " + "; ".join(f"{n} {a:,} -> {b:,} ({100 * (b / a - 1):+.1f}%) in {k}" for _, n, k, a, b in big))

fmt = lambda t: " + ".join(t[0]) + " for " + " + ".join(t[1])
print("     trades in the board's own format (raw %, + = first side ahead · verdict kind):")
for t, b, a in zip(TRADES, tb, ta): print(f"       {fmt(t)}: {b['raw']:+.1f}% {b['kind']} -> {a['raw']:+.1f}% {a['kind']}")
PINS = {0: (6.8, 0.9, "plain", "plain"), 1: (-6.2, -2.7, "plain", "plain"), 2: (0.8, -2.3, "plain", "plain"), 3: (-5.5, -8.7, "plain", "plain"),
        4: (5.3, 13.7, "split", "sensitive"), 5: (-5.3, -4.7, "plain", "plain"), 6: (-10.2, -10.8, "split", "split")}
for i, (rb, ra, kb, ka) in PINS.items():
    b, a = tb[i], ta[i]
    ok(abs(b["raw"] - rb) <= 0.1 and abs(a["raw"] - ra) <= 0.1 and (b["kind"], a["kind"]) == (kb, ka),
       f"{fmt(TRADES[i])}: {rb:+.1f}% {kb} -> {ra:+.1f}% {ka} (got {b['raw']:+.1f}% {b['kind']} -> {a['raw']:+.1f}% {a['kind']})")

# the FantasyCalc comparison reads today's market file: advisory here as in format_check (ci_policy.json, Alan, Oct 21)
LIVE_MKT = "TE7–TE12 near FantasyCalc"
for c in fc:
    if c["check"].startswith(LIVE_MKT) and not c.get("pass"):
        print(f"INVESTIGATE live market deviation (advisory, not blocking): {c['check']}: {'; '.join(map(str, c.get('values') or []))}")
bad = [c["check"] + ": " + "; ".join(map(str, c.get("values") or []))[:160] for c in fc if not c.get("pass") and not c["check"].startswith(LIVE_MKT)]
ok(not bad, f"SPM.formatCheck() passes on the after board ({len(fc)} checks)" + (f"; failing: {bad}" if bad else ""))
bad = [c["check"] + ": " + "; ".join(map(str, c.get("values") or []))[:160] for c in bc if not c.get("pass") and not c.get("info")]
ok(not bad, f"SPM.boardCheck() passes on the after board ({len(bc)} checks)" + (f"; failing: {bad}" if bad else ""))

ev = next((e for e in json.load(open(os.path.join(ROOT, "data", "rank_history.json")))["events"] if e["ts"] == EVENT_TS), None)
if ev:
    rk = {s for s in as_ if any(as_[s][c] != bs[s][c] for c in ("rank", "pos_rank", "tier"))}
    evr = {e[0] for e in ev["ranking"]}; evm = {e[0]: e for e in ev["manual"]}
    ok(evr == rk == mov, f"History event's ranking changes are exactly the fixtures' overall rank moves ({len(evr)} vs {len(mov)}; no position rank or tier changed)")
    ok(all((e[1], e[2], e[3], e[4]) == (int(bs[e[0]]["rank"]), int(as_[e[0]]["rank"]), int(bs[e[0]]["tier"]), int(as_[e[0]]["tier"])) for e in ev["ranking"]), "History event's from / to ranks and tiers match the fixtures")
    ok(set(evm) == chg and all(e[1:] == [bs[s]["value"], as_[s]["value"]] for s, e in evm.items()), f"History event's value edits are exactly the fixtures' changed values, from and to ({len(evm)} vs {len(chg)})")
    pl = json.load(open(os.path.join(ROOT, "data", "rank_history.json")))["players"]
    last = {s: next((l for l in pl[s] if l[0] == EVENT_TS), None) for s in chg | mov}
    ok(all(l and l[1:5] == [int(as_[s]["rank"]), int(as_[s]["pos_rank"]), int(as_[s]["tier"]), val(as_[s])] and l[5] == "M" and l[6] == ("RV" if s in chg and s in mov else "V" if s in chg else "R") for s, l in last.items()), f"Each changed player's history entry records his new rank, tier and value with the right kind ({len(last)} players)")
    ok(ev.get("src") == "M" and ev.get("repriced") == len(chg), f"History event is a publish (src M) with {ev.get('repriced')} values changed")
else: ok(False, f"History event of the smoothing publish ({EVENT_TS}) found")
ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
