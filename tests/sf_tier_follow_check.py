"""AM SF PPR TE+ RB and WR tiers follow AM PPR's (Alan, Nov 14): tiers and values of RBs and WRs only.

Every RB and WR that AM PPR ranks in its Tiers 1-12 is grouped on the SF board exactly as AM PPR groups him, by
positional rank; SF-only boundaries inside an AM PPR tier are gone and AM PPR's boundaries are added. Values are not
copied or converted from AM PPR: they are refitted from the SF board's own values (the Nov 14 smoothing method: one even
% step inside a tier, never larger than the step AM PPR's values have in that tier when priced in SF's format; every boundary at least 3% and twice the average
inner step of the two tiers beside it; the smallest total change), with tier levels free to shift so that no boundary
is wider than 1.5x AM PPR's gap at the same spot. That 1.5x limit is a guideline of this alignment, not a valuation
rule; Alan's exceptions: WR36 onward keeps the levels of the fit without the limit (Cooper -> McConkey stays about 50%
rather than lifting Downs and Lemon 57%), which leaves Waddle -> Bernard at 24.1%. QB and TE tiers and values, the
unranked deep tail (RB53+, WR61+), Manual / Auto, value-0 players, tag tiers and AM PPR are untouched.

This suite prices the board before (tests/fixtures/sf-tier-follow/before.csv) and after (after.csv) with today's code,
with AM PPR frozen as published that day (ppr.csv), so later ranking publishes never break it.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/sf_tier_follow_check.py

1. The fixtures: same players, position ranks, sources; only rank, tier, tier name and value differ, and tier / tier
   name / value only for RBs and WRs; QB, TE, Auto, value-0, tag-tier and deep-tail values unchanged; RB / WR tier
   boundaries equal AM PPR's through its Tier 12; tier names as approved; even steps; the boundary rule and the 1.5x
   guideline with Alan's exceptions; the approved
   boundaries and same-tier pairs; no value moves 40% or more; RB / WR totals within 2.5%.
2. Over 108 formats: the SF board's own format gives exactly the saved values; every 1QB format (AM PPR) is identical;
   every QB and TE league-adjusted value is the same in every Superflex / 2QB format (apart from a few rounding steps
   of a point or two); board-0 players read 0; values
   never rise down a position; RB / WR weekly starters keep their total within 3.5%.
3. Representative trades in the board's own format, pinned before and after.
4. SPM.formatCheck() and SPM.boardCheck() pass on the after board. The published history event equals the fixtures'
   differences. No page errors.
"""
import csv, functools, http.server, io, json, math, os, re, socketserver, statistics, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sf-tier-follow")
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
CSV_RE = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
PPR_RE = re.compile(r"(const RANKINGS_CSV_PPR = `\n)([\s\S]*?)(\n`;)")
PPR, BEFORE, AFTER = (open(os.path.join(FIX, n), encoding="utf-8").read().rstrip("\n") for n in ("ppr.csv", "before.csv", "after.csv"))
FORMATS = [dict(teams=t, qb=q, rec=r, tep=e) for t in (8, 10, 12, 14) for q in ("1", "sf", "2") for r in (0, 0.5, 1) for e in (0, 0.5, 1)]
key = lambda f: f"{f['teams']}-team {dict(zip(('1', 'sf', '2'), ('1QB', 'SF', '2QB')))[f['qb']]} {f['rec']} PPR TEP {f['tep']}"
board_of = lambda f: "ppr" if f["qb"] == "1" else "sf-tep"
EVENT_TS = "2026-11-14T09:30:00.000Z"
N_VALUES, N_RANKS, N_TIERS = 107, 135, 151
NAMES = {"RB": ["Elite RB1", "High RB1", "RB1", "Low RB1", "High RB2", "RB2", "Low RB2", "RB3/Flex", "Low RB3/Flex", "Flex depth", "Bench/Handcuff", "Bench Depth", "Deep bench"],
         "WR": ["Elite WR1", "High WR1", "WR1", "Low WR1", "High WR2", "WR2", "Low WR2", "WR3", "Low WR3", "Flex Play", "Shaky Flex", "Bench", "Deep bench"]}
# tier boundaries Alan reviewed (upper player, lower player, gap %) and pairs AM PPR keeps in one tier
BOUNDARIES = (("Josh Jacobs", "Cam Skattebo", 19.6), ("Jaylen Waddle", "Germie Bernard", 24.1), ("Omar Cooper Jr.", "Ladd McConkey", 50.0), ("Tyler Allgeier", "TreVeyon Henderson", 47.2))
PAIRS = (("CeeDee Lamb", "Ja'Marr Chase", 2.4), ("Bijan Robinson", "Christian McCaffrey", 6.0), ("Malik Nabers", "Tee Higgins", 4.5), ("Zay Flowers", "Nico Collins", 2.2),
         ("Rhamondre Stevenson", "Quinshon Judkins", 4.7), ("Keenan Allen", "Josh Downs", 3.6), ("TreVeyon Henderson", "Corey Kiner", 2.1))
CAP_EXEMPT = {("WR", 35), ("WR", 38), ("WR", 42)}   # Alan, Nov 14: WR36 onward keeps the uncapped fit's levels
TRADES = (
    (("CeeDee Lamb",), ("Ja'Marr Chase",)),
    (("Bijan Robinson",), ("Christian McCaffrey",)),
    (("Malik Nabers",), ("Tee Higgins",)),
    (("Brock Bowers",), ("Trey Mcbride",)),
    (("Christian McCaffrey",), ("Joe Burrow",)),
    (("Josh Jacobs",), ("Bo Nix",)),
    (("Nico Collins",), ("George Kittle",)),
    (("Cam Skattebo",), ("Dalton Kincaid",)),
    (("Brock Bowers", "KC Concepcion Jr.", "Aaron Jones Sr."), ("Malik Nabers", "Luther Burden III", "Dalton Kincaid")),
    (("Malik Willis", "Blake Corum"), ("Geno Smith",)),
)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def table(c): return list(csv.DictReader(io.StringIO(c)))
B, A, P = table(BEFORE), table(AFTER), {r["sleeper_id"]: r for r in table(PPR)}
bs, as_ = {r["sleeper_id"]: r for r in B}, {r["sleeper_id"]: r for r in A}
val = lambda r: int(r["value"])
pct = lambda a, b: 100 * (1 - val(b) / val(a))
ok(set(bs) == set(as_) and sorted(int(r["rank"]) for r in A) == list(range(1, len(A) + 1)), f"Fixtures: the same {len(A)} players, ranks 1..{len(A)}")
FREE = ("rank", "value", "tier", "tier_name")
ok(all({k: v for k, v in bs[s].items() if k not in FREE} == {k: v for k, v in as_[s].items() if k not in FREE} for s in bs), "Only rank, tier, tier name and value differ (position ranks, Manual / Auto, teams unchanged)")
chg = {s for s in bs if bs[s]["value"] != as_[s]["value"]}
mov = {s for s in bs if bs[s]["rank"] != as_[s]["rank"]}
tch = {s for s in bs if bs[s]["tier"] != as_[s]["tier"]}
ok((len(chg), len(mov), len(tch)) == (N_VALUES, N_RANKS, N_TIERS), f"{len(chg)} values, {len(mov)} overall ranks and {len(tch)} tier numbers differ (reviewed: {N_VALUES}, {N_RANKS}, {N_TIERS})")
qt = [as_[s]["player"] for s in bs if bs[s]["pos"] in ("QB", "TE") and any(bs[s][c] != as_[s][c] for c in ("value", "tier", "tier_name"))]
ok(not qt, f"Every QB and TE keeps his value, tier and tier name ({sum(r['pos'] in ('QB', 'TE') for r in A)} players)" + (f"; changed: {qt[:5]}" if qt else ""))
ranked = lambda s: s in P and P[s]["source"] == "manual" and int(P[s]["tier"]) <= 12 and bs[s]["source"] == "manual" and val(bs[s]) > 0 and int(bs[s]["tier"]) < 90
bad = sorted(as_[s]["player"] for s in chg if not ranked(s) or as_[s]["source"] == "auto")
ok(not bad, "No value changed for an Auto player, a value-0 or tag-tier player, or the deep tail AM PPR does not rank" + (f"; changed: {bad[:5]}" if bad else ""))
ok(all(val(as_[s]) == 0 for s in bs if val(bs[s]) == 0) and all(as_[s]["tier"] == bs[s]["tier"] for s in bs if int(bs[s]["tier"]) >= 90), "Value-0 players stay 0 and tag tiers (Out for season) keep their players")
v = [val(r) for r in sorted(A, key=lambda r: int(r["rank"]))]
ok(all(x > y or x == y == 0 for x, y in zip(v, v[1:])), "Values strictly down the overall board (only 0s tie)")
srt = sorted(A, key=lambda r: int(r["rank"]))
tight = [(x["player"], y["player"]) for x, y in zip(srt, srt[1:]) if val(y) >= 400 and val(x) - val(y) < 2]
ok(not tight, "No two neighbours worth 400+ sit one point apart" + (f"; {tight}" if tight else ""))
by_name = {r["player"]: r for r in A}
steps = lambda g: [math.log(val(a) / val(b)) for a, b in zip(g, g[1:])]
for pos in ("RB", "WR"):
    g = sorted((r for r in A if r["pos"] == pos and int(r["tier"]) < 90), key=lambda r: int(r["pos_rank"]))
    rk = [r for r in g if ranked(r["sleeper_id"])]
    ok(rk == g[:len(rk)], f"{pos}: the players AM PPR ranks in Tiers 1-12 are {pos}1-{pos}{len(rk)}, the tail after them is untouched")
    sfb = {int(a["pos_rank"]) for a, b in zip(g, g[1:]) if a["tier"] != b["tier"]}
    pb = {int(a["pos_rank"]) for a, b in zip(rk, rk[1:]) if P[a["sleeper_id"]]["tier"] != P[b["sleeper_id"]]["tier"]} | {len(rk)}
    ok(sfb == pb, f"{pos} tier boundaries equal AM PPR's through its Tier 12, then the deep tail: after {', '.join(pos + str(k) for k in sorted(sfb))}")
    ts = []
    for r in g:
        if ts and ts[-1][0]["tier"] == r["tier"]: ts[-1].append(r)
        else: ts.append([r])
    ok([int(t[0]["tier"]) for t in ts] == list(range(1, len(ts) + 1)) and all({r["tier_name"] for r in t} == {NAMES[pos][i]} for i, t in enumerate(ts)), f"{pos} tiers numbered 1-{len(ts)} with the approved names ({', '.join(NAMES[pos])})")
    al = [t for t in ts if ranked(t[0]["sleeper_id"])]
    uneven = [(t[0]["tier"], round(100 * (max(steps(t)) - min(steps(t))), 2)) for t in al if len(t) > 1 and max(steps(t)) - min(steps(t)) > 0.01]
    ok(not uneven, f"{pos}: {len(al)} aligned tiers step evenly (inner steps within 1 point of each other, whole-number rounding)" + (f"; uneven: {uneven}" if uneven else ""))
    short, over = [], []
    for a, b in zip(ts, ts[1:]):
        gap = math.log(val(a[-1]) / val(b[0]))
        inner = [statistics.mean(steps(t)) for t in (a, b) if len(t) > 1 and ranked(t[0]["sleeper_id"])]
        need = max(-math.log(0.97), 2 * statistics.mean(inner) if inner else 0)
        if gap < need - 0.005: short.append((a[-1]["player"], round(100 * (1 - math.exp(-gap)), 1)))
        if ranked(b[0]["sleeper_id"]) and (pos, int(a[-1]["pos_rank"])) not in CAP_EXEMPT:
            cap = max(need, 1.5 * math.log(int(P[a[-1]["sleeper_id"]]["value"]) / int(P[b[0]["sleeper_id"]]["value"])))
            if gap > cap + 0.005: over.append((a[-1]["player"], round(100 * (1 - math.exp(-gap)), 1)))
    ok(not short, f"{pos}: every tier boundary steps at least 3% and twice the average inner step of the aligned tiers beside it" + (f"; short: {short}" if short else ""))
    ok(not over, f"{pos}: no boundary is wider than 1.5x AM PPR's gap there (or the minimum), except the WR36+ boundaries Alan kept" + (f"; over: {over}" if over else ""))
    tb, ta = sum(val(r) for r in B if r["pos"] == pos), sum(val(r) for r in A if r["pos"] == pos)
    ok(abs(ta / tb - 1) <= 0.025, f"{pos} total value {tb:,} -> {ta:,} ({100 * (ta / tb - 1):+.2f}%, within 2.5%)")
for a, b, want in BOUNDARIES:
    ok(abs(pct(by_name[a], by_name[b]) - want) <= 0.1, f"Reviewed boundary {a} -> {b}: {pct(by_name[a], by_name[b]):.1f}% (approved {want}%)")
for a, b, want in PAIRS:
    ok(as_[by_name[a]["sleeper_id"]]["tier"] == by_name[b]["tier"] and abs(pct(by_name[a], by_name[b]) - want) <= 0.1, f"Same tier as on AM PPR, {a} -> {b}: {pct(by_name[a], by_name[b]):.1f}% (reviewed {want}%)")
ok(val(by_name["Josh Downs"]) == 511 and val(by_name["Makai Lemon"]) == 490, "Josh Downs 511 and Makai Lemon 490 (Alan: not the 57% lift)")
swing = max(abs(math.log(val(as_[s]) / val(bs[s]))) for s in chg)
big = max(chg, key=lambda s: abs(math.log(val(as_[s]) / val(bs[s]))))
ok(100 * (math.exp(swing) - 1) < 66 and 100 * (1 - math.exp(-swing)) < 40, f"No value doubles or halves: the largest move is {as_[big]['player']} {val(bs[big]):,} -> {val(as_[big]):,} ({100 * (val(as_[big]) / val(bs[big]) - 1):+.1f}%)")

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
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
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
# QB and TE values aren't inputs of the change, but the league layer rounds to whole points after pricing every position
# together, so a deep QB or TE can land a point or two away (CI, Nov 14: AJ Barner 579 -> 580 and Eli Raridon 577 -> 579
# in 14-team 0 PPR TE premium +1.0; none on other browser builds). Allowed: at most 2 points and 0.5% (1 point under
# 100), in at most 12 player-formats; anything bigger is a real QB / TE change and fails.
qtd = [(key(f), r["name"], before[key(f)][s]["adj"], r["adj"]) for f in sf for s, r in after[key(f)].items() if r["pos"] in ("QB", "TE") and r["adj"] != before[key(f)][s]["adj"]]
qtm = [d for d in qtd if abs(d[3] - d[2]) > (1 if d[2] < 100 else min(2, 0.005 * d[2]))]
ok(not qtm and len(qtd) <= 12, f"Every QB and TE league-adjusted value the same before and after in {len(sf)} Superflex / 2QB formats ({len(qtd)} rounding steps of a point or two)" + (f"; changed: {len(qtm)}, e.g. {qtm[:3]}" if qtm else ""))
zero = [(k, r["name"], r["adj"]) for k, rows in after.items() for r in rows.values() if not (r["v"] > 0) and r["adj"] != 0]
ok(not zero, "Board-0 players read 0 in every format" + (f"; not 0: {zero[:4]}" if zero else ""))
inv = []
for f in sf:
    for pos in ("QB", "RB", "WR", "TE"):
        g = sorted((r for r in after[key(f)].values() if r["pos"] == pos), key=lambda r: r["pn"])
        inv += [(key(f), a["name"], a["adj"], b["name"], b["adj"]) for a, b in zip(g, g[1:]) if b["adj"] > a["adj"]]
ok(not inv, f"League-adjusted values never rise down a position: {len(sf)} Superflex / 2QB formats" + (f"; {inv[:3]}" if inv else ""))
worst = (0, "")
for f in sf:
    for pos, n in (("RB", 2.5), ("WR", 3.5)):
        top = lambda res: sum(sorted((r["adj"] for r in res[key(f)].values() if r["pos"] == pos), reverse=True)[:round(n * f["teams"])])
        d = abs(top(after) / top(before) - 1)
        if d > worst[0]: worst = (d, f"{pos} in {key(f)}")
ok(worst[0] <= 0.035, f"RB and WR weekly starters keep their total league-adjusted value within 3.5% in every Superflex / 2QB format (largest {100 * worst[0]:.2f}%, {worst[1]})")
big = sorted(((abs(math.log(r["adj"] / before[key(f)][s]["adj"])), r["name"], key(f), before[key(f)][s]["adj"], r["adj"]) for f in sf for s, r in after[key(f)].items()
              if r["adj"] >= 300 and before[key(f)][s]["adj"] >= 300), reverse=True)[:5]
print("     largest league-adjusted changes (300+ points): " + "; ".join(f"{n} {a:,} -> {b:,} ({100 * (b / a - 1):+.1f}%) in {k}" for _, n, k, a, b in big))

fmt = lambda t: " + ".join(t[0]) + " for " + " + ".join(t[1])
print("     trades in the board's own format (raw %, + = first side ahead · verdict kind):")
for t, b, a in zip(TRADES, tb, ta): print(f"       {fmt(t)}: {b['raw']:+.1f}% {b['kind']} -> {a['raw']:+.1f}% {a['kind']}")
PINS = {0: (21.9, 2.5, "plain", "plain"), 1: (26.0, 6.4, "plain", "plain"), 2: (18.4, 4.7, "plain", "plain"), 3: (12.3, 12.3, "plain", "plain"), 4: (4.7, 15.7, "plain", "plain"),
        5: (0.9, 0.5, "plain", "plain"), 6: (-13.2, -4.7, "plain", "plain"), 7: (-8.8, -16.6, "plain", "plain"), 8: (-10.8, -13.8, "split", "split"), 9: (13.7, 20.1, "sensitive", "tempered")}
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

hist = json.load(open(os.path.join(ROOT, "data", "rank_history.json")))
ev = next((e for e in hist["events"] if e["ts"] == EVENT_TS), None)
if ev:
    rk = {s for s in as_ if any(as_[s][c] != bs[s][c] for c in ("rank", "pos_rank", "tier"))}
    evr = {e[0] for e in ev["ranking"]}; evm = {e[0]: e for e in ev["manual"]}
    ok(evr == rk == mov | tch, f"History event's ranking changes are exactly the fixtures' overall rank moves and tier changes ({len(evr)} vs {len(mov | tch)})")
    ok(all((e[1], e[2], e[3], e[4]) == (int(bs[e[0]]["rank"]), int(as_[e[0]]["rank"]), int(bs[e[0]]["tier"]), int(as_[e[0]]["tier"])) for e in ev["ranking"]), "History event's from / to ranks and tiers match the fixtures")
    ok(set(evm) == chg and all(e[1:] == [bs[s]["value"], as_[s]["value"]] for s, e in evm.items()), f"History event's value edits are exactly the fixtures' changed values, from and to ({len(evm)} vs {len(chg)})")
    last = {s: next((l for l in hist["players"][s] if l[0] == EVENT_TS), None) for s in chg | rk}
    ok(all(l and l[1:5] == [int(as_[s]["rank"]), int(as_[s]["pos_rank"]), int(as_[s]["tier"]), val(as_[s])] and l[5] == "M" and l[6] == ("RV" if s in chg and s in rk else "V" if s in chg else "R") for s, l in last.items()),
       f"Each changed player's history entry records his new rank, tier and value with the right kind ({len(last)} players)")
    ok(ev.get("src") == "M" and ev.get("repriced") == len(chg), f"History event is a publish (src M) with {ev.get('repriced')} values changed")
    ok(not any(e["ts"] == EVENT_TS for e in json.load(open(os.path.join(ROOT, "data", "boards", "ppr", "rank_history.json")))["events"]), "No AM PPR history event at that time")
else: ok(False, f"History event of the alignment publish ({EVENT_TS}) found")
ok(not errors, "No page errors" + (": " + "; ".join(errors[:3]) if errors else ""))
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
