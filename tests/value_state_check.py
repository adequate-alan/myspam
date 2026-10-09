"""Values as state (Alan, Oct 12; Architecture C, value model "state-baseline-v1").

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/value_state_check.py

The board's values are stored in RANKINGS_CSV and never re-derived on load. An edit changes only the players it acts on
(the one you move, re-tier, give a value or recalculate); everyone who only shifts keeps his value, except whole-point
steps deep in the tail when there is no integer room. Checks, all in the page's real editor code (no publishing):
1. Migration identity: every stored value is what the page shows (all players), no typed/custom state, and changing
   every projection column changes no base value.
2. Moves: CeeDee #7 → #8, Bowers #6 → #9, a large Bijan move, Burrow one spot, Pickens / Tuten, an RB/WR, a QB/WR and
   a TE/WR swap. Only the mover's value changes (plus at most whole-point tail steps), it lands strictly between his
   new neighbours, values stay strictly down the board and tiers stay in one piece. Known values from the approved
   preview: CeeDee 8,815 → 8,295, Bowers 9,710 → 7,770, Bijan 9,950 → 7,770.
3. Tiers: a same-rank tier change keeps his rank and explains where Tier 2 pricing would place him (suggested rank);
   a rank + tier change; tiers stay in one piece after every move.
4. Value edits: a value that fits is kept exactly and moves nobody else; one that doesn't fit changes nothing until a
   choice (also in tests/editor_check.py through the value box).
5. Deep tail: a move near the bottom changes untouched players by whole points only (≤ 5, under 1,000).
6. Round trips return the board exactly (0 drift); two edit orders reaching the same state give the same values.
7. A formula preview (SPM.formulaPreview) and Recalculate Auto players (until saved) never change the stored board
   by themselves; the preview lists proposed values.
8. Pre-publish checks (SPM.validateRankings) stop: a split tier, a value out of order, a missing value, and an
   untouched player whose value changed.
9. Auto players: they still exist with source "auto"; Review panel → Recalculate Auto players is there for a signed-in
   editor (?debug here) and revalues only Auto players (plus whole-point tail steps) as unsaved changes Cancel undoes;
   moving an Auto player makes him Manual while one who only shifted stays Auto; a scheduled snapshot of an unchanged
   board records nothing; the tail logic (autoValues) is only used by the position curve, never by the typed path.
10. No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
M = re.search(r"(const RANKINGS_CSV = `\n)(.*?)(\n`;)", SRC, re.S)
ROWS = list(csv.DictReader(io.StringIO(M.group(2))))
STORED = {r["player"]: int(r["value"]) for r in ROWS}

def with_proj(scale):   # the same page with every projection column changed (a weekly projection refresh)
    rows = list(csv.reader(io.StringIO(M.group(2)))); h = rows[0]
    for r in rows[1:]:
        for c in ("proj_ppg", "proj_score"):
            i = h.index(c)
            if r[i]: r[i] = f"{float(r[i]) * scale:.2f}"
        r[h.index("games")] = "9"
    cell = lambda v: '"' + v.replace('"', '""') + '"' if re.search(r'[",\n]', v) else v
    return SRC[:M.start(2)] + "\n".join(",".join(cell(c) for c in r) for r in rows) + SRC[M.end(2):]

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

HELP = """() => {
  const E = SPM.edit;
  window.__B = () => E.board().sort((a, b) => a.rank - b.rank);
  window.__id = n => E.board().find(p => p.name === n).id;
  window.__p = n => E.board().find(p => p.name === n);
  window.__run = (ops) => {
    E.cancel(); const before = __B(); const bm = new Map(before.map(p => [p.name, p]));
    ops.forEach(o => { const id = __id(o[1]);
      if (o[0] === 'rank') E.moveOverall(id, o[2]);
      else if (o[0] === 'pos') E.movePlayer(id, o[2], o.length > 3 ? o[3] : null);
      else if (o[0] === 'value') E.setValue(id, o[2]);
      else if (o[0] === 'out') E.sendOut(id); });
    const after = __B(), touched = new Set(E.touched());
    const key = p => (p.name + '|' + p.pos).toLowerCase();
    const changed = after.filter(p => p.value !== bm.get(p.name).value).map(p => ({ name: p.name, from: bm.get(p.name).value, to: p.value, rank: p.rank, touched: touched.has(key(p)) }));
    const desc = after.every((p, i) => i === 0 || p.value < after[i - 1].value || p.value === 0);
    const tiers = {}; let split = null;
    after.slice().sort((a, b) => a.pos.localeCompare(b.pos) || a.posNum - b.posNum).forEach(p => { const t = Number(p.tier); if (t >= 90) return; if (tiers[p.pos] != null && t < tiers[p.pos]) split = split || p.name; tiers[p.pos] = t; });
    const nb = n => { const i = after.findIndex(p => p.name === n); return [after[i - 1] && after[i - 1].value, after[i].value, after[i + 1] && after[i + 1].value]; };
    const out = { changed, desc, split, warn: document.getElementById('ed-warn').hidden ? '' : document.getElementById('ed-warn').innerText,
      movers: Object.fromEntries(ops.map(o => [o[1], { from: bm.get(o[1]), to: __p(o[1]), nb: nb(o[1]) }])), board: after.map(p => [p.name, p.rank, p.tier, p.value]) };
    return out;
  };
}"""

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")   # the editor's functions (SPM.edit) are test-only
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    pg.evaluate(HELP)

    # 1. migration identity
    shown = {x[0]: x[3] for x in pg.evaluate("() => __B().map(p => [p.name, p.rank, p.tier, p.value])")}
    same = [n for n in STORED if shown.get(n) == STORED[n]]
    ok(len(same) == len(STORED) == len(shown), f"Migration identity: {len(same)}/{len(STORED)} stored values shown exactly")
    ok(all(r["value"].strip() for r in ROWS), "Every player has a stored value (no blank = model, no typed state)")
    ok(not re.search(r"calibrateToAnchors|anchorFade|shadowOf|custom-pill|auto-btn|bendCheck|typedMoveNotice|\bp\.custom\b|modelValued|Typed values win", SRC),
       "The typed / anchor code path is gone (calibrateToAnchors, anchorFade, shadow run, custom pill, Auto/Reset, bend warning, p.custom, modelValued)")
    pg2 = br.new_page(); pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.add_init_script("window.__SPM_TEST_HOOKS = true;")   # the editor's functions (SPM.edit) are test-only
    pg2.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|api\.github\.com)/.*"), lambda r: r.abort())
    pg2.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=with_proj(1.37)))
    pg2.goto(BASE + "/#rankings"); pg2.wait_for_selector("#rank-body tr.player"); pg2.wait_for_timeout(800)
    shown2 = {x[0]: x[1] for x in pg2.evaluate("() => SPM.edit.board().map(p => [p.name, p.value])")}
    ok(shown2 == shown, f"A projection refresh (every projection ×1.37, 9 games) changes no base value ({sum(shown2[n] != shown[n] for n in shown)} changed)")
    pg2.close()

    TAIL = lambda c: [x for x in c if not x["touched"]]
    def tail_ok(c): return all(abs(x["to"] - x["from"]) <= 5 and max(x["to"], x["from"]) < 1000 for x in TAIL(c))
    def move_case(label, ops, expect=None):
        r = pg.evaluate("ops => __run(ops)", ops)
        mv = r["movers"]; names = list(mv)
        lines = [f"{n} #{mv[n]['from']['rank']} → #{mv[n]['to']['rank']} {mv[n]['from']['value']:,} → {mv[n]['to']['value']:,}" for n in names]
        between = all((mv[n]["nb"][0] is None or mv[n]["nb"][1] < mv[n]["nb"][0]) and (mv[n]["nb"][2] is None or mv[n]["nb"][1] > mv[n]["nb"][2] or mv[n]["nb"][1] == 0) for n in names)
        ok(r["desc"] and not r["split"] and between and tail_ok(r["changed"]),
           f"{label}: {'; '.join(lines)}; untouched changed {len(TAIL(r['changed']))}, strictly down the board, tiers in one piece")
        if expect and expect != "tail":
            for n, v in expect.items(): ok(mv[n]["to"]["value"] == v, f"   {n} = {v:,} (approved preview) → {mv[n]['to']['value']:,}")
        return r

    # 2. moves
    b0 = {x[0]: x for x in pg.evaluate("() => __B().map(p => [p.name, p.rank, p.tier, p.value, p.pos, p.posNum])")}
    move_case("CeeDee #7 → #8", [["rank", "CeeDee Lamb", 8]], {"CeeDee Lamb": 8295})
    move_case("Bowers #6 → #9", [["rank", "Brock Bowers", 9]], {"Brock Bowers": 7770})
    move_case("Bijan #3 → #9 (large move)", [["rank", "Bijan Robinson", 9]], {"Bijan Robinson": 7770})
    move_case("Bijan #3 → #40 (very large move)", [["rank", "Bijan Robinson", 40]])
    move_case("Burrow one spot down", [["rank", "Joe Burrow", b0["Joe Burrow"][1] + 1]])
    move_case("Pickens below Tuten", [["rank", "George Pickens", b0["Bhaysul Tuten"][1]]])
    move_case("Tuten above Pickens", [["rank", "Bhaysul Tuten", b0["George Pickens"][1]]])
    board = pg.evaluate("() => __B().map(p => [p.name, p.rank, p.pos])")
    def swap(a, b):
        for i in range(1, 80):
            if board[i - 1][2] == a and board[i][2] == b: return board[i - 1][0], board[i][1]
    for a, b in (("RB", "WR"), ("QB", "WR"), ("TE", "WR")):
        n, rk = swap(a, b); move_case(f"{a}/{b} swap: {n} one spot down past a {b}", [["rank", n, rk]])

    # 3. tiers
    ch = b0["Ja'Marr Chase"]
    r = pg.evaluate("ops => __run(ops)", [["pos", "Ja'Marr Chase", ch[5], 2]])
    to = r["movers"]["Ja'Marr Chase"]["to"]
    ok(to["rank"] == ch[1] and to["tier"] == "2" and "Tier 2 pricing would place Ja'Marr Chase" in r["warn"] and "Suggested rank: #" in r["warn"] and not TAIL(r["changed"]),
       f"Same-rank tier change: Chase stays #{to['rank']} in Tier 2, explained: {r['warn'][:130]!r}")
    pg.click('#ed-warn [data-ed="move-rank"]'); pg.wait_for_timeout(300)
    rk = pg.evaluate("() => __p(\"Ja'Marr Chase\").rank"); sug = int(re.search(r"Suggested rank: #(\d+)", r["warn"]).group(1))
    ok(rk == sug, f"Move to the suggested rank: #{rk}")
    fl = b0["Zay Flowers"] if "Zay Flowers" in b0 else None
    if fl:
        r = move_case("Rank + tier change: Zay Flowers down into the next WR tier", [["pos", "Zay Flowers", fl[5] + 3]])
    ok(all(not pg.evaluate("ops => __run(ops)", [["rank", n, k]])["split"] for n, k in (("Tyler Warren", 30), ("Trey Mcbride", 60), ("Josh Allen", 40), ("Bucky Irving", 5))),
       "Tiers stay in one piece after cross-position moves (Warren, McBride, Allen, Irving)")

    # 4. value edits
    pk = b0["Puka Nacua"]
    r = pg.evaluate("ops => __run(ops)", [["value", "Puka Nacua", pk[3] - 5]])
    ok([(x["name"], x["to"]) for x in r["changed"]] == [("Puka Nacua", pk[3] - 5)] and not r["warn"], f"A value that fits: Puka {pk[3]:,} → {pk[3] - 5:,}, nobody else changes")
    r = pg.evaluate("ops => __run(ops)", [["value", "Puka Nacua", 9000]])
    ok(not r["changed"] and "9,000 does not fit at #9" in r["warn"] and "This value fits around #7" in r["warn"], f"9,000 for Puka: nothing changes, explained: {r['warn'][:110]!r}")
    pg.click('#ed-warn [data-ed="close"]')

    # 5. deep tail
    last = [x for x in board if x[2] == "WR"][-1][0]
    r = pg.evaluate("ops => __run(ops)", [["rank", last, b0[last][1] - 1]])
    ok(r["desc"] and tail_ok(r["changed"]), f"Deep tail: {last} up one spot; untouched changes are whole points only ({[(x['name'], x['from'], x['to']) for x in TAIL(r['changed'])][:6]})")

    # 6. round trips and edit order
    base = pg.evaluate("() => { SPM.edit.cancel(); return __B().map(p => [p.name, p.rank, p.tier, p.value]); }")
    for label, ops in (("CeeDee #7 → #8 → #7", [["rank", "CeeDee Lamb", 8], ["rank", "CeeDee Lamb", 7]]),
                       ("Bowers #6 → #9 → #6", [["rank", "Brock Bowers", 9], ["rank", "Brock Bowers", 6]]),
                       ("Chase T1 → T2 → T1", [["pos", "Ja'Marr Chase", ch[5], 2], ["pos", "Ja'Marr Chase", ch[5], 1]]),
                       ("Pickens one down and back", [["rank", "George Pickens", b0["George Pickens"][1] + 1], ["rank", "George Pickens", b0["George Pickens"][1]]]),
                       ("Three moves, then all undone", [["rank", "CeeDee Lamb", 10], ["rank", "Brock Purdy", 20], ["pos", "Ja'Marr Chase", ch[5], 2], ["pos", "Ja'Marr Chase", ch[5], 1],
                                                         ["rank", "Brock Purdy", b0["Brock Purdy"][1]], ["rank", "CeeDee Lamb", 7]])):
        r = pg.evaluate("ops => __run(ops)", ops)
        ok(r["board"] == base, f"Round trip {label}: board back exactly ({sum(1 for a, b in zip(r['board'], base) if a != b)} rows differ)")
    a = pg.evaluate("ops => __run(ops)", [["rank", "CeeDee Lamb", 10], ["rank", "Brock Purdy", 20]])["board"]
    b = pg.evaluate("ops => __run(ops)", [["rank", "Brock Purdy", 20], ["rank", "CeeDee Lamb", 10]])["board"]
    ok(sorted(a) == sorted(b), "Two edit orders reaching the same ranks give the same values")

    # 7. formula preview, auto recalculation
    pg.evaluate("() => SPM.edit.cancel()")
    fp = pg.evaluate("() => SPM.formulaPreview({ tierBlend: 0.45 })")
    after = pg.evaluate("() => __B().map(p => [p.name, p.rank, p.tier, p.value])")
    ok(after == base and sum(1 for x in fp if x["proposed"] != x["current"]) > 0, f"Formula preview: {sum(1 for x in fp if x['proposed'] != x['current'])} proposed changes listed, board unchanged")
    n = pg.evaluate("() => SPM.edit.recalcAuto()")
    unsaved = pg.inner_text("#eb-count")
    pg.evaluate("() => SPM.edit.cancel()")
    ok(pg.evaluate("() => __B().map(p => [p.name, p.rank, p.tier, p.value])") == base, f"Recalculate Auto players: {n} values as unsaved changes ({unsaved}); Cancel restores the board")

    # 8. pre-publish checks
    def broken(fn):
        t = [r.copy() for r in ROWS]; fn(t)
        out = io.StringIO(); w = csv.DictWriter(out, fieldnames=list(ROWS[0].keys()), lineterminator="\n"); w.writeheader(); w.writerows(t)
        return out.getvalue().strip()
    def tier_split(t):
        wr = sorted([r for r in t if r["pos"] == "WR"], key=lambda r: int(r["rank"]))
        wr[1]["tier"] = str(int(wr[1]["tier"]) + 1)
    cases = {
        "a split tier": (broken(tier_split), "is split"),
        "a value out of order": (broken(lambda t: next(r for r in t if r["rank"] == "2").__setitem__("value", str(int(next(r for r in t if r["rank"] == "1")["value"]) + 1))), "worth"),
        "a missing value": (broken(lambda t: t[5].__setitem__("value", "")), "no value"),
    }
    for label, (csvtext, needle) in cases.items():
        errs_v = pg.evaluate("c => SPM.validateRankings(c, null)", csvtext)
        ok(any(needle in e for e in errs_v), f"Pre-publish check stops {label}: {[e for e in errs_v if needle in e][:1]}")
    ok(pg.evaluate("c => SPM.validateRankings(c, null)", M.group(2)) == [], "The migrated rankings pass every pre-publish check")
    def bump(t):
        r = next(r for r in t if r["rank"] == "40"); r["value"] = str(int(r["value"]) - 20)
    errs_v = pg.evaluate("([c, l]) => SPM.validateRankings(c, l, new Map())", [broken(bump), M.group(2)])
    ok(any("nobody edited" in e for e in errs_v), f"Pre-publish check stops an untouched player's value change: {[e for e in errs_v if 'nobody' in e][:1]}")

    # 9. the Auto workflow
    autos = [r["player"] for r in ROWS if r["source"] == "auto"]
    on_page = pg.evaluate("() => SPM.edit.board().filter(p => p.source === 'auto').map(p => p.name)")
    ok(len(autos) > 0 and sorted(on_page) == sorted(autos), f"Auto players exist: {len(autos)} with source auto, the same on the page")
    ok(len(re.findall(r"autoValues\(", SRC)) == 2 and "function positionCurve" in SRC, "The Auto tail (autoValues) is defined once and called only from the position curve")
    pd = br.new_page(viewport={"width": 1440, "height": 1000}); pd.on("pageerror", lambda e: errs.append(str(e)))
    pd.add_init_script("window.__SPM_TEST_HOOKS = true;")   # the editor's functions (SPM.edit) are test-only
    pd.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|api\.github\.com)/.*"), lambda r: r.abort())
    pd.goto(BASE + "/?debug=1#rankings"); pd.wait_for_selector("#rank-body tr.player"); pd.wait_for_timeout(1200)
    b1 = {x["name"]: x for x in pd.evaluate("() => SPM.edit.board()")}
    pd.click("#eb-vcheck"); pd.wait_for_timeout(300)
    btn = pd.locator("[data-rv-recalc-auto]")
    ok(btn.count() == 1 and btn.is_visible(), "Review panel → Value warnings shows 'Recalculate Auto players' to an editor")
    btn.click(); pd.wait_for_timeout(600)
    b2 = {x["name"]: x for x in pd.evaluate("() => SPM.edit.board()")}
    ch = [n for n in b2 if b2[n]["value"] != b1[n]["value"]]
    other = [(n, b1[n]["value"], b2[n]["value"]) for n in ch if b1[n]["source"] != "auto"]
    ok(any(b1[n]["source"] == "auto" for n in ch) and all(abs(a - b) <= 5 and max(a, b) < 1000 for _, a, b in other) and pd.inner_text("#eb-count") != "All saved"
       and all(b2[n]["rank"] == b1[n]["rank"] for n in b2),
       f"Recalculate Auto players: {sum(b1[n]['source'] == 'auto' for n in ch)} Auto values change as unsaved edits, ranks untouched, {len(other)} non-Auto whole-point tail steps")
    # the deep tail (Oct 12: the first version priced it from per-position neighbours, collapsing ~12 Auto values to 0 and
    # pushing Manual players in the tail down 8–13 points): Auto values move a few points, never to 0, nothing collapses
    autoch = [(n, b1[n]["value"], b2[n]["value"]) for n in ch if b1[n]["source"] == "auto"]
    ok(all(abs(b - a) <= max(10, 0.1 * a) for _, a, b in autoch) and not [x for x in autoch if x[2] == 0 and x[1] > 0],
       f"Deep tail: every Auto value moves at most max(10 pts, 10%), none drops to 0 ({autoch[:6]})")
    pd.evaluate("() => SPM.edit.cancel()"); pd.wait_for_timeout(300)
    ok({x["name"]: x["value"] for x in pd.evaluate("() => SPM.edit.board()")} == {n: b1[n]["value"] for n in b1}, "Cancel undoes the recalculation")
    first = min((x for x in b1.values() if x["source"] == "auto"), key=lambda x: x["rank"])
    above = next(x for x in b1.values() if x["rank"] == first["rank"] - 1)
    pd.evaluate("([id, r]) => SPM.edit.moveOverall(id, r)", [first["id"], first["rank"] - 1]); pd.wait_for_timeout(300)
    b3 = {x["name"]: x for x in pd.evaluate("() => SPM.edit.board()")}
    ok(b3[first["name"]]["source"] == "manual" and b3[above["name"]]["source"] == above["source"],
       f"Moving Auto {first['name']} up makes him Manual; {above['name']} who only shifted stays {above['source']}")
    pd.evaluate("() => SPM.edit.cancel()")
    rec = pd.evaluate("""() => { const s = SPM.rankingSnapshot(), h = SPM.normalizeHistory({ version: 2, players: {}, events: [] }), f = { version: 1, snapshots: [] };
      SPM.recordPublish(h, f, null, s, '2026-10-12T10:00:00.000Z', 'B', 'baseline', null);   // the board as published
      return SPM.recordPublish(h, f, f.snapshots[f.snapshots.length - 1], SPM.rankingSnapshot(), '2026-10-13T14:00:00.000Z', 'S', 'scheduled', null).changed; }""")
    ok(rec is False, "A scheduled snapshot of an unchanged board records nothing (no hidden weekly repricing)")
    pd.close()

    ok(not errs, f"No page errors {errs[:2]}")
    br.close()

print("\n" + ("All value-state checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
