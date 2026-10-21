"""Trade history: AM value at the time vs AM value today (Alan, Oct 8). Synthetic league and synthetic ranking
history only; no real league data belongs in the repo.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/trade_history_check.py   (SHOTS=/dir for screenshots)

Checks:
1. A trade after AM values existed shows both snapshots: "AM at trade" from the latest entry at or before the trade
   (an update published an hour after it is never used; the card labels it "Then · <date> AM values") and "Now · Current AM values" from today's base AM values, plus a
   how-it-aged line.
2. The breakdown lists each player's rank, position rank, tier and value at the time, today's value and the change.
3. A trade before any AM value says "No AM value existed at the time of this trade" and only shows today.
4. A trade where only some players had a value then gives no at-the-time verdict (never today's value labeled as then).
5. Draft picks and FAAB stay listed, unvalued. Three-team trades show each team's net in both snapshots. No page errors.
7. Then and Now are priced in the league's format (Oct 20: MONEY LEAGUE 2K27, a 1QB TE premium league on the no-TEP AM
   PPR board, read base values, so a TE counted as if there were no TE premium). Now = the league-adjusted value of each
   player; Then = the board as published then, priced in the league's format; the board's current snapshot priced that
   way reproduces the league layer exactly; a TE in a 1QB TE+ league is worth more than on the AM PPR board itself.
6. A trade with a player AM doesn't value (a team defense, a kicker, a player off the board) whose other players all had
   a value then still shows its Then / Now verdict, with that player listed as not valued (Oct 20: it crashed the whole
   Transactions view with "Cannot read properties of null (reading 'v')").
"""
import os, re, sys, json
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
SHOTS = os.environ.get("SHOTS")
iso = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
DAY = 86400e3

LONG = "Alpha League Team 1 The Supercalifragilisticexpialidocious Dynasty"   # a long name must wrap, never clip
L1["users"][0]["metadata"]["team_name"] = LONG
R = L1["rosters"]
a1, a2 = R[0]["players"][4], R[0]["players"][6]      # team 1 sends
b1 = R[1]["players"][3]                              # team 2 sends
c1, d1 = R[2]["players"][5], R[3]["players"][5]
e1, f1 = R[4]["players"][5], R[5]["players"][5]
g1, g2, g3 = R[6]["players"][5], R[7]["players"][5], R[8]["players"][5]
k1, k2 = R[9]["players"][5], R[10]["players"][5]
UNV = "KC"                                           # a team defense: never on an AM board, no history
T_HIST, T_PRE, T_PART, T_3 = NOW - 10 * DAY, NOW - 40 * DAY, NOW - 12 * DAY, NOW - 9 * DAY
# synthetic history: everyone first valued 30 days ago; a1/a2/b1 re-valued 2 days before the trade, and b1 again an hour AFTER it
first = NOW - 30 * DAY
hist = {"note": "synthetic", "version": 2, "players": {}}
def add(sid, ms, rank, pr, tier, v): hist["players"].setdefault(sid, []).append([iso(ms), rank, pr, tier, v, "M"])
for sid, rk in [(a1, 20), (a2, 60), (b1, 15), (c1, 40), (e1, 50), (f1, 55), (g1, 70), (g2, 75), (g3, 80), (k1, 65), (k2, 66)]: add(sid, first, rk, 9, 3, 3000 - rk * 10)
add(a1, T_HIST - 2 * DAY, 18, 7, 2, 6100); add(a2, T_HIST - 2 * DAY, 58, 22, 4, 2400); add(b1, T_HIST - 2 * DAY, 12, 5, 2, 8500)
add(b1, T_HIST + 3600e3, 30, 11, 3, 4000)   # published after the trade: must never count as "at the time"
# d1 has no history: the partial trade
L1["tx"] = {2: [
    {"transaction_id": "th1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 2, "status_updated": T_HIST,
     "adds": {b1: 1, a1: 2, a2: 2}, "drops": {b1: 2, a1: 1, a2: 1}, "draft_picks": [{"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2, "previous_owner_id": 1}],
     "waiver_budget": [{"sender": 2, "receiver": 1, "amount": 15}]},
    {"transaction_id": "th3", "type": "trade", "status": "complete", "roster_ids": [7, 8, 9], "leg": 2, "status_updated": T_3,
     "adds": {g1: 8, g2: 9, g3: 7}, "drops": {g1: 7, g2: 8, g3: 9}, "draft_picks": [], "waiver_budget": []},
    {"transaction_id": "thk", "type": "trade", "status": "complete", "roster_ids": [10, 11], "leg": 2, "status_updated": T_3 + 3600e3,
     "adds": {k1: 11, k2: 10, UNV: 10}, "drops": {k1: 10, k2: 11, UNV: 11}, "draft_picks": [], "waiver_budget": []}],
  1: [{"transaction_id": "thp", "type": "trade", "status": "complete", "roster_ids": [3, 4], "leg": 1, "status_updated": T_PART,
       "adds": {c1: 4, d1: 3}, "drops": {c1: 3, d1: 4}, "draft_picks": [], "waiver_budget": []},
      {"transaction_id": "th0", "type": "trade", "status": "complete", "roster_ids": [5, 6], "leg": 1, "status_updated": T_PRE,
       "adds": {e1: 6, f1: 5}, "drops": {e1: 5, f1: 6}, "draft_picks": [], "waiver_budget": []}]}

# 7. a 1QB TE premium league (valued on AM PPR, which has no TE premium) with a trade after AM PPR's first snapshot:
# a TE for two WRs, picked from that snapshot by position rank so the test doesn't depend on who they are
_ps = json.load(open(os.path.join(ROOT, "data", "boards", "ppr", "rank_snapshots", "2026-10.json")))["snapshots"][0]
_by = lambda pos, pr: next(sid for sid, a in _ps["players"].items() if a[1] == pr and pos == next((r_["pos"] for r_ in rows if r_["sleeper_id"] == sid), None))
TE4, WRA, WRB = _by("TE", 4), _by("WR", 31), _by("WR", 43)
T_TEP = int(datetime.fromisoformat(_ps["ts"].replace("Z", "+00:00")).timestamp() * 1000 + DAY)
L3 = make_league("L3", "Gamma League", 12, ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"] + ["BN"] * 6,
                 {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2, "bonus_rec_te": 0.5})
L3["tx"] = {6: [{"transaction_id": "tep1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 6, "status_updated": T_TEP,
                 "adds": {TE4: 2, WRA: 1, WRB: 1}, "drops": {TE4: 1, WRA: 2, WRB: 2}, "draft_picks": [], "waiver_budget": []}]}
LEAGUES["L3"] = L3

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    for theme in ("dark", "light"):
        errs = []
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route("**/data/rank_history.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(hist)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.add_init_script(f"window.__SPM_TEST_HOOKS = true; try {{ localStorage.setItem('spm_theme', '{theme}'); }} catch (e) {{}}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
        today = pg.evaluate("() => SPM.rankingSnapshot()")
        pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
        pg.wait_for_timeout(400)
        pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
        pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
        pg.click("#tab-league"); pg.wait_for_timeout(500)
        pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2000)
        pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
        while pg.locator("[data-tx-older]").count(): pg.click("[data-tx-older]"); pg.wait_for_timeout(300)
        cards = pg.locator(".th-card")
        def idx(team):
            for i in range(cards.count()):
                if f"Alpha League Team {team} " in " ".join(cards.nth(i).inner_text().split()) + " ": return i
            return 0
        I = {"hist": idx(2), "three": idx(7), "part": idx(4), "pre": idx(6), "unv": idx(10)}
        txt = lambda k: " ".join(cards.nth(I[k]).inner_text().split())
        ok(cards.count() == 5, f"[{theme}] five trades listed ({cards.count()})")
        ok(not pg.locator(".lg-error").count() and "Something went wrong" not in pg.inner_text("#panel-league"), f"[{theme}] the Transactions view renders (no 'Something went wrong')")
        if theme == "dark":
            # 1. the two-team trade after AM existed: Team 1 got b1 (8,500 then), Team 2 got a1 + a2 (6,100 + 2,400 then)
            c = txt("hist")
            print("   card:", c[:400])
            ok("THEN" in c.upper() and "NOW" in c.upper() and "AM VALUES" in c.upper() and "CURRENT AM VALUES" in c.upper(), "Both snapshots shown on the compact card as Then / Now with the values they use")
            ev = pg.evaluate("() => SPM.tradeEval('th1')")
            V = {x["sid"]: x for x in ev["items"]}
            ok(ev["adjusted"] and V[b1]["thenBase"] == 8500 and V[a1]["thenBase"] == 6100 and V[a2]["thenBase"] == 2400, "At the time = the entry before the trade, never the update an hour after it (base 8,500 · 6,100 · 2,400)")
            ok(all(f"{round(V[s_]['thenV']):,}" in c for s_ in (b1, a1, a2)), "The card shows each player's value then in the league's format")
            ok(all(x["now"] == x["adj"] for x in ev["items"]), "Now = each player's league-adjusted value")
            # Then vs Now (Alan, Oct 12): two equal blocks (verdict, who had the edge and by how much, the values used),
            # a headline labeled Then → Now naming how it aged, and one sentence covering both states
            hc = cards.nth(I["hist"])
            ok(hc.locator(".th-verdict small").inner_text().upper() == "THEN → NOW", "The headline is labeled Then → Now (a comparison, not only the historical verdict)")
            label = hc.locator(".th-verdict").inner_text().split("\n")[-1].strip().upper()
            ok(label in {"EDGE WIDENED", "EDGE NARROWED", "EDGE HELD", "WINNER FLIPPED", "EDGE EMERGED", "EVENED OUT", "EVEN THEN AND NOW", "SPLIT AT THE TIME", "SPLIT TODAY", "SPLIT THEN AND NOW"}, f"Headline names how the trade aged: {label}")
            bt, bn = (" ".join(hc.locator(f".th-age.{k}").inner_text().split()) for k in ("then", "now"))
            print("   then:", bt, "| now:", bn)
            ok(bt.upper().startswith("THEN") and "AM values" in bt and bn.upper().startswith("NOW") and "Current AM values" in bn, "Then and Now blocks each name the values they use")
            ok(all(hc.locator(f".th-age.{k} .th-age-v").count() == 1 for k in ("then", "now")), "Each block carries its own verdict")
            whoT, whoN = (hc.locator(f".th-age.{k} .th-edge").inner_text() for k in ("then", "now"))
            ok(all(re.search(r"Team \d+ \+[\d,]+$", w.strip()) or w.strip() == "Even" or "Team" in w for w in (whoT, whoN)), f"Each block says who had the edge and by how much ({whoT} / {whoN})")
            tT, tN = (re.search(r"Team (\d+) \+", w) for w in (whoT, whoN))
            if tT and tN and tT.group(1) != tN.group(1): ok(label == "WINNER FLIPPED", "A different winner reads Winner flipped")
            aged = hc.locator(".th-aged").inner_text()
            ok("at the time" in aged and "today" in aged, f"How it aged covers both states: {aged}")
            ok(hc.locator(".th-age-v.win, .th-age-v.even").count() == 2 and hc.locator(".th-ages [class*=red], .th-ages .mine").count() == 0, "Then / Now markers are neutral (filled dot or hollow ring), never red per side")
            ok("$15 FAAB" in c and "2027 Round 1" in c, "Draft pick and FAAB stay listed")
            cards.nth(I["hist"]).locator("[data-th-full]").click(); pg.wait_for_timeout(300)
            full = " ".join(cards.nth(I["hist"]).locator(".th-full").inner_text().split())
            print("   history:", full[:600])
            tb1, nb1 = round(V[b1]["thenV"]), round(V[b1]["now"])
            ok(f"#12 · " in full and "Tier 2 at trade" in full and f"{tb1:,} → {nb1:,}" in full, "Breakdown: rank, position rank, tier and value at the time → today")
            d = nb1 - tb1
            ok(("+" if d > 0 else "−" if d < 0 else "±") + f"{abs(d):,}" in full, f"Per-player change shown ({d:+,})")
            ok("Not valued" in full and "published at or before the trade" in full, "Picks not valued; snapshot rule spelled out")
            ok("At the time:" in full and "Today:" in full, "Both verdicts in the breakdown")
            # 3-team
            c3 = txt("three")
            ok("THEN" in c3.upper() and c3.count("Team 7") >= 3 and ("+" in c3 and "−" in c3 or "Basically" in c3), "Three-team trade: each team's net in both snapshots")
            # partial and pre-AM
            cp, c0 = txt("part"), txt("pre")
            ok("Not every player had an AM value at the time" in cp and "NOW" in cp.upper() and cards.nth(I["part"]).locator(".th-verdict small").inner_text().upper() == "NOW", "Partial history: no at-the-time verdict")
            ok("No AM value existed at the time of this trade" in c0 and cards.nth(I["pre"]).locator(".th-tag.pre").count() == 1, "Pre-AM trade says no AM value existed, shows today only")
            ok(cards.nth(I["pre"]).locator(".th-verdict small").inner_text().upper() == "NOW", "Pre-AM headline verdict is labeled Now")
            ok(cards.nth(I["three"]).locator(".th-verdict small").inner_text().upper() == "THEN → NOW" and cards.nth(I["three"]).locator(".th-age.then .th-edge-sub").count() == 1, "Three-team trade: Then → Now headline, each team's net in the Then block")
            # 6. an unvalued player (team defense) beside players who all had a value then
            cu = txt("unv"); uc = cards.nth(I["unv"])
            print("   unvalued:", cu[:300])
            ok(uc.locator(".th-age.then .th-age-v").count() == 1 and uc.locator(".th-verdict small").inner_text().upper() == "THEN → NOW", "A trade with a team defense still gets its Then → Now verdict from the valued players")
            ok(UNV in cu or "–" in cu, "The team defense stays listed, unvalued")
            uc.locator("[data-th-full]").click(); pg.wait_for_timeout(300)
            ok("Not valued by AM" in uc.locator(".th-full").inner_text(), "Breakdown lists the team defense as not valued by AM")
            n_err = len(errs); uc.locator("[data-th-analyze]").click(); pg.wait_for_timeout(1200)
            ok(len(errs) == n_err and pg.locator("#panel-trade").is_visible(), f"Analyze trade opens it in the calculator without an error {errs[n_err:][:1]}")
            pg.click("#tab-league"); pg.wait_for_timeout(500)
            cards = pg.locator(".th-card")
        if SHOTS:
            cards.nth(I["hist"]).scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(SHOTS, f"trade_history_{theme}.png"), full_page=False)
            cards.nth(I["hist"]).screenshot(path=os.path.join(SHOTS, f"card_{theme}_1440.png"))
            pg.set_viewport_size({"width": 390, "height": 900}); pg.wait_for_timeout(400)
            cards.nth(I["hist"]).scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(SHOTS, f"trade_history_{theme}_phone.png"), full_page=False)
            cards.nth(I["hist"]).screenshot(path=os.path.join(SHOTS, f"card_{theme}_390.png"))
        pg.set_viewport_size({"width": 375, "height": 900}); pg.wait_for_timeout(400)
        if pg.locator(".th-age.then").count():
            tb, nb = (cards.nth(I["hist"]).locator(f".th-age.{k}").bounding_box() for k in ("then", "now"))
            ok(tb and nb and abs(tb["y"] - nb["y"]) < 2 and nb["x"] >= tb["x"] + tb["width"] - 1, f"[{theme}] Then and Now stay side by side at 375px without overlapping")
            clip = pg.evaluate("""() => [...document.querySelectorAll('.th-ages, .th-age, .th-age > *')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className)""")
            ok(not clip, f"[{theme}] long team names wrap inside the Then / Now blocks, nothing clipped at 375px {clip[:3]}")
        if theme == "dark":
            # how the trade aged, every case (agedText from the page source, run on synthetic snapshots)
            src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
            fn = re.search(r"  function agedText\(r\) \{.*?\n  \}\n", src, re.S).group(0)
            cases = pg.evaluate("""fn => { const aged = new Function('fmt', fn + '; return agedText;')(n => Math.round(n).toLocaleString('en-US'));
              const P = [{ team: { name: 'A' } }, { team: { name: 'B' } }], S = (ahead, diff, fair = false, split = false) => ({ ahead, diff, fair, split });
              const run = (t, n) => aged({ parts: P, then: t, now: n });
              return { widened: run(S(0, 138), S(0, 437)), narrowed: run(S(0, 900), S(0, 200)), held: run(S(0, 500), S(0, 510)), flipped: run(S(0, 300), S(1, 300)),
                emerged: run(S(0, 5, true), S(1, 800)), evened: run(S(1, 800), S(0, 5, true)), even: run(S(0, 5, true), S(1, 3, true)),
                split: run(S(0, 0, false, true), S(0, 400)), missing: run(null, S(0, 400)) }; }""", fn)
            exp = {"widened": ("Edge widened", "A won at the time and is still ahead today; the gap widened from +138 to +437."),
                   "narrowed": ("Edge narrowed", "A won at the time and is still ahead today; the gap narrowed from +900 to +200."),
                   "held": ("Edge held", "A won at the time and is still ahead today by about the same margin."),
                   "flipped": ("Winner flipped", "A won at the time, but B is ahead today."),
                   "emerged": ("Edge emerged", "Even at the time; B is ahead today."),
                   "evened": ("Evened out", "B won at the time; it's basically even today."),
                   "even": ("Even then and now", "Basically even at the time and still basically even today."),
                   "split": ("Split at the time", "Split verdict at the time; A is ahead today.")}
            for k, (lab, txt_) in exp.items():
                got = cases[k] or {}
                ok(got.get("label") == lab and got.get("text") == txt_, f"How it aged, {k}: {got}")
            ok(cases["missing"] is None, "No at-the-time values: no Then → Now trend (today's verdict labeled Now)")
        wide = pg.evaluate("() => [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1 && getComputedStyle(e).position !== 'fixed').slice(-4).map(e => e.tagName + '.' + e.className + ' ' + (e.textContent || '').slice(0, 40))")
        ok(pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"[{theme}] no horizontal page scroll {wide}")
        ok(not errs, f"[{theme}] no page errors {errs[:2]}")
        pg.close()
    # 7. the TE premium league
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L3']").click(); pg.wait_for_timeout(1500)
    pg.click("#tab-league"); pg.wait_for_timeout(500)
    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2500)
    pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
    while pg.locator("[data-tx-older]").count(): pg.click("[data-tx-older]"); pg.wait_for_timeout(300)
    ev = pg.evaluate("() => SPM.tradeEval('tep1')")
    V = {x["sid"]: x for x in ev["items"]}
    print("   TE premium league:", ev)
    ok(ev["board"] == "ppr" and ev["adjusted"] and ev["thenAll"], "The 1QB TE premium league reads AM PPR, in its own format, with values then")
    ok(all(x["now"] == x["adj"] for x in ev["items"]), "Now = each player's league-adjusted value (TE premium applied)")
    ok(V[TE4]["now"] > V[TE4]["nowBase"] * 1.05 and V[TE4]["thenV"] > V[TE4]["thenBase"] * 1.05, f"The TE is worth more with TE premium than on AM PPR itself (then {V[TE4]['thenBase']} → {V[TE4]['thenV']}, now {V[TE4]['nowBase']} → {V[TE4]['now']})")
    same = pg.evaluate("() => SPM.adjAt(Date.now())")
    lv = pg.evaluate("() => SPM.leagueSidValues()")
    diff = [sid for sid, v in lv.items() if sid in same and same[sid] != v]
    ok(same and len(same) >= 200 and not diff, f"AM PPR's current snapshot priced in the league's format = the league layer for every player ({len(same or {})} players, {len(diff)} differ {diff[:3]})")
    if all(x["thenBase"] == x["nowBase"] for x in ev["items"]):
        ok(ev["thenDiff"] == ev["nowDiff"], f"Unchanged values for these players then and now give the same edge in points ({ev['thenDiff']} / {ev['nowDiff']})")
    else:   # a later publish moved them (e.g. the Oct 21 rankings update): the check needs values that stood still
        print(f"INFO these players' AM PPR values changed since the trade ({[(x['thenBase'], x['nowBase']) for x in ev['items']]}), so the same-edge check doesn't apply")
    card = pg.locator(".th-card").first
    ct = " ".join(card.inner_text().split())
    ok(f"{round(V[TE4]['thenV']):,}" in ct and "league format" in ct, "The card shows the TE's value in the league's format and says so")
    card.locator("[data-th-full]").click(); pg.wait_for_timeout(300)
    full = " ".join(card.locator(".th-full").inner_text().split())
    ok("before this league's format" in full and f"{round(V[TE4]['thenBase']):,}" in full, "The breakdown keeps the AM PPR board's own totals as a muted reference")
    if SHOTS:
        card.screenshot(path=os.path.join(SHOTS, "card_tep_dark_1440.png"))
    ok(not errs, f"[TE premium league] no page errors {errs[:2]}")
    pg.close()
    br.close()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
