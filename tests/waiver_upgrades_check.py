"""Waiver upgrades (Alan, Oct 22): League → Waiver Wire opens with available players ranked above someone on your roster.

Two synthetic 12-team leagues (a Superflex TE premium one on AM SF PPR TE+ and a 1QB one on AM PPR); the visitor (u1)
owns roster 3. Every expected list is recomputed here in Python from the page's own league-adjusted numbers
(SPM.leagueRanks: value, position, position rank, overall rank by Sleeper ID) and the mocked rosters. Checks:
  1. Same position (default): the list, its order (value gain, then rank), the lowest-ranked rostered player each one
     outranks, the gains and rank gaps; the top three rows on screen; the tab's count
  2. players owned by another team never appear; an available player at value 0 never does; injured reserve and taxi
     players are never the comparison; a rostered player without an AM rank is counted in the note, never compared;
     open roster spots are named
  3. View all lists every upgrade; Any position compares by overall rank; Show top 3 goes back
  4. clicking the available player, and the rostered one, opens that player's drawer
  5. values follow the league's own board (1QB → AM PPR) and the numbers shown are its league-adjusted values
  6. switching leagues and a Sleeper refresh that changes ownership recalculate the list and the count
  7. both themes at 1440 and 390 render with no sideways scroll; no page errors
Screenshots go to SHOTS=dir when set. Run from the repo root:  python3 tests/waiver_upgrades_check.py
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("SHOTS")
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = [r for r in csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())) if r["sleeper_id"]]
rows.sort(key=lambda r: int(r["rank"]))
NAME = {r["sleeper_id"]: r["player"] for r in rows}
ZERO = [r["sleeper_id"] for r in rows if r["value"] in ("0", "0.0")]
POOL = [r["sleeper_id"] for r in rows if r["sleeper_id"] not in ZERO][:250]
FREE = set(POOL[18::8]) | set(ZERO)        # mid-board free agents, plus every board-0 player (never an upgrade)
DEALT = [s for s in POOL if s not in FREE]
MINE = 3

def league(lid, qb):
    teams = [DEALT[i::12][:17] for i in range(12)]
    if lid == "L2": teams = teams[4:] + teams[:4]
    me = teams[MINE - 1]
    me.extend(["KC", "9999999"])            # a defense and an id the board doesn't know: unranked, never compared
    ir, taxi = me[-3], me[-4]               # his two lowest-ranked board players
    rosters = [{"roster_id": i + 1, "owner_id": "u1" if i == MINE - 1 else f"o{i+1}", "co_owners": [], "players": list(t),
                "starters": list(t[:9]), "reserve": [ir] if i == MINE - 1 else [], "taxi": [taxi] if i == MINE - 1 else [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    users = [{"user_id": r["owner_id"], "display_name": r["owner_id"], "metadata": {"team_name": ("Mine " if r["owner_id"] == "u1" else "Team ") + lid + "-" + str(r["roster_id"])}, "avatar": ""} for r in rosters]
    pos = (["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] if qb == "sf" else ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "FLEX"]) + ["BN"] * 9 + ["IR", "TAXI"]
    lg = {"league_id": lid, "name": {"L1": "League One", "L2": "League Two"}[lid], "season": "2026", "status": "in_season", "total_rosters": 12,
          "roster_positions": pos,
          "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
          "settings": {"num_teams": 12, "type": 0, "reserve_slots": 1, "taxi_slots": 1}}
    return [lg, users, rosters]
DATA = {"L1": league("L1", "sf"), "L2": league("L2", "1qb")}

def expected(lid, R, mode="pos"):
    rosters = DATA[lid][2]
    owned = {s for r in rosters for s in r["players"]}
    me = next(r for r in rosters if r["owner_id"] == "u1")
    off = set(me["reserve"]) | set(me["taxi"])
    starters = set(me["starters"])
    ok = lambda s: s in R and R[s][1] in ("QB", "RB", "WR", "TE") and R[s][2] is not None and R[s][3] is not None
    mine = [s for s in me["players"] if s not in off and ok(s)]
    k = (lambda s: R[s][3]) if mode == "any" else (lambda s: R[s][2])
    out = []
    for s, v in R.items():
        if s in owned or not ok(s) or not v[0] > 0: continue
        beat = [m for m in mine if (mode == "any" or R[m][1] == v[1]) and k(m) > k(s) and R[m][0] < v[0]]
        if not beat: continue
        over = max(beat, key=k)
        out.append({"sid": s, "over": over, "gain": v[0] - R[over][0], "ranks": k(over) - k(s), "bench": over not in starters, "more": len(beat) - 1})
    out.sort(key=lambda x: (-x["gain"], k(x["sid"])))
    return out, mine, me

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
h = functools.partial(Quiet, directory=ROOT)
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
def shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []

    def page(theme="dark", width=1440, active="L1"):
        lg, us, ro = DATA[active]
        SL = {"source": "sleeper", "username": "u1", "userId": "u1", "displayName": "u1", "season": "2026",
              "leagues": [{"id": l, "name": DATA[l][0]["name"], "season": "2026", "status": "in_season", "format": ""} for l in ("L1", "L2")],
              "activeId": active, "data": {active: {"league": lg, "users": us, "rosters": ro}}, "view": "league"}
        def sleeper(route):
            path = route.request.url.split("/v1", 1)[-1].split("?")[0]
            body = []
            m = re.match(r"/league/(L\d)(/users|/rosters)?$", path)
            if m: body = DATA[m.group(1)][{None: 0, "/users": 1, "/rosters": 2}[m.group(2)]]
            elif path == "/state/nfl": body = {"season": "2026", "week": 5, "season_type": "regular"}
            elif path == "/user/u1/leagues/nfl/2026": body = [DATA[l][0] for l in ("L1", "L2")]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pg = br.new_page(viewport={"width": width, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_theme', '{theme}'); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#league"); pg.wait_for_timeout(2000)
        pg.click('[data-lsub="waivers"]'); pg.wait_for_timeout(600)
        return pg

    def state(pg):
        return pg.evaluate("""() => ({ R: SPM.leagueRanks(), pos: SPM.waiverUpgrades('pos'), any: SPM.waiverUpgrades('any'), board: SPM.leagueValues().board,
          rows: [...document.querySelectorAll('#fa-upg .wu-row')].map(r => ({ av: r.querySelector('.wu-av [data-player]').dataset.player, over: r.querySelector('.wu-mine [data-player]').dataset.player,
            gain: r.querySelector('.wu-gain b').textContent, vals: [...r.querySelectorAll('.wu-v')].map(x => x.textContent) })),
          cnt: (document.querySelector('[data-lsub="waivers"] .lg-cnt') || {}).textContent || '', n: (document.querySelector('#fa-upg .wu-n') || {}).textContent || '',
          notes: (document.querySelector('#fa-upg .wu-notes') || {}).textContent || '' })""")
    fmtn = lambda v: f"{round(v):,}"
    same = lambda a, b: [(x["sid"], x["over"], round(x["gain"]), x["ranks"], x["bench"], x["more"]) for x in a] == [(x["sid"], x["over"], round(x["gain"]), x["ranks"], x["bench"], x["more"]) for x in b]

    # 1–3: Superflex league on AM SF PPR TE+
    pg = page()
    base_board = pg.evaluate("() => SPM.leagueValues().board")
    S = state(pg)
    exp, mine, me = expected("L1", S["R"])
    ok(len(exp) >= 4, f"the synthetic league has more than three same-position upgrades ({len(exp)})")
    ok(same(S["pos"], exp), "Same position: the page's list equals the list recomputed from league-adjusted ranks and the rosters")
    ok([(r["av"], r["over"]) for r in S["rows"]] == [(x["sid"], x["over"]) for x in exp[:3]], "the top three rows on screen are the three strongest, each against the lowest-ranked player of yours he outranks")
    ok(all(r["gain"] == "+" + fmtn(x["gain"]) for r, x in zip(S["rows"], exp)), "each row shows the value difference")
    ok(all(r["vals"] == ["AM Value " + fmtn(S["R"][x["sid"]][0]), "AM Value " + fmtn(S["R"][x["over"]][0])] for r, x in zip(S["rows"], exp)), "both players show their league-adjusted AM value")
    ok(S["cnt"] == str(len(exp)), f"the Waiver Wire tab carries the count ({S['cnt']!r})")
    ok(S["n"].startswith(f"{len(exp)} potential upgrade"), f"the header names the count ({S['n']!r})")
    owned = {s for r in DATA["L1"][2] for s in r["players"]}
    ok(not any(x["sid"] in owned for x in S["pos"] + S["any"]), "no player owned by any team is listed as available")
    ok(not any(x["sid"] in ZERO for x in S["pos"] + S["any"]), "an available player at value 0 is never an upgrade")
    off = set(me["reserve"]) | set(me["taxi"])
    ok(not any(x["over"] in off for x in S["pos"] + S["any"]), "injured reserve and taxi players are never the comparison")
    irs = me["reserve"][0]
    ok(any(S["R"][x][1] == S["R"][irs][1] and S["R"][x][2] < S["R"][irs][2] for x in S["R"] if x not in owned and S["R"][x][0] > 0), "(the IR player would be outranked if he counted, so the exclusion matters)")
    ok("2 rostered players without an AM rank" in S["notes"], f"unranked rostered players are counted, not compared ({S['notes']!r})")
    ok("IR and taxi players aren't compared" in S["notes"], "the note says IR and taxi players aren't compared")
    ok("open roster spot" in S["notes"], "an open roster spot is named (17 active of 18)")
    shot(pg, "waiver-upgrades-desktop-dark")

    pg.click("#fa-upg [data-wu-all]"); pg.wait_for_timeout(300)
    n_all = pg.locator("#fa-upg .wu-row").count()
    ok(n_all == len(exp), f"View all lists every upgrade ({n_all} of {len(exp)})")
    ok(pg.locator("#fa-upg [data-wu-mode]").count() == 2, "the expanded view offers Same position / Any position")
    pg.click('#fa-upg [data-wu-mode="any"]'); pg.wait_for_timeout(300)
    exp_any, _, _ = expected("L1", S["R"], "any")
    ok(same(S["any"], exp_any), "Any position: the page's list equals the list recomputed by overall rank")
    rows_any = pg.eval_on_selector_all("#fa-upg .wu-row", "rs => rs.map(r => [r.querySelector('.wu-av [data-player]').dataset.player, r.querySelector('.wu-mine [data-player]').dataset.player])")
    ok(rows_any == [[x["sid"], x["over"]] for x in exp_any], f"Any position shows all {len(exp_any)} on screen")
    ok(len(exp_any) >= len(exp), "Any position finds at least as many as Same position")
    ok(pg.locator('[data-lsub="waivers"] .lg-cnt').text_content() == str(len(exp)), "the tab count stays the same-position count")
    shot(pg, "waiver-upgrades-any-position-dark")
    pg.click("#fa-upg [data-wu-all]"); pg.wait_for_timeout(300)
    ok(pg.locator("#fa-upg .wu-row").count() == min(3, len(exp)) and pg.locator("#fa-upg [data-wu-mode]").count() == 0, "Show top 3 goes back to the same-position top three")

    # 4: the drawer
    first = exp[0]
    pg.click(f'#fa-upg .wu-av [data-player="{first["sid"]}"]'); pg.wait_for_timeout(700)
    ok(pg.evaluate("() => document.getElementById('player-modal').open") and NAME[first["sid"]] in pg.locator("#player-modal").inner_text(), "clicking the available player opens his drawer")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.click(f'#fa-upg .wu-mine [data-player="{first["over"]}"]'); pg.wait_for_timeout(700)
    ok(pg.evaluate("() => document.getElementById('player-modal').open") and NAME[first["over"]] in pg.locator("#player-modal").inner_text(), "clicking the rostered player opens his drawer")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # 6a: a Sleeper refresh that changes ownership: another team picks up the top available upgrade
    top = first["sid"]
    other = DATA["L1"][2][0]; other["players"].append(top)
    pg.click("#league-chip"); pg.wait_for_timeout(200); pg.click('#league-menu [data-act="refresh"]'); pg.wait_for_timeout(1500)
    S2 = state(pg)
    exp2, _, _ = expected("L1", S2["R"])
    ok(same(S2["pos"], exp2) and not any(x["sid"] == top for x in S2["pos"]), "after a Sleeper refresh the newly rostered player drops out and the list is recomputed")
    ok(S2["cnt"] == str(len(exp2)) and len(exp2) == len(exp) - 1, f"the tab count follows the refresh ({S2['cnt']})")
    other["players"].remove(top)

    # 6b + 5: switch to the 1QB league (AM PPR)
    pg.click("#league-chip"); pg.wait_for_timeout(200); pg.click('#league-menu [data-league="L2"]'); pg.wait_for_timeout(1800)
    if not pg.locator("#fa-upg .wu").count(): pg.click('[data-lsub="waivers"]'); pg.wait_for_timeout(500)
    S3 = state(pg)
    exp3, _, _ = expected("L2", S3["R"])
    ok(S3["board"] == "ppr" and base_board != "ppr", f"the 1QB league reads AM PPR ({base_board} → {S3['board']})")
    ok(same(S3["pos"], exp3), "after switching leagues the list is recomputed on the new league's rosters and values")
    ok([(r["av"], r["over"]) for r in S3["rows"]] == [(x["sid"], x["over"]) for x in exp3[:3]], "the rows on screen follow the switch")
    ok(all(r["vals"][0] == "AM Value " + fmtn(S3["R"][x["sid"]][0]) for r, x in zip(S3["rows"], exp3)), "values shown are the 1QB league's league-adjusted AM PPR values")
    ok(S3["cnt"] == (str(len(exp3)) if exp3 else ""), "the tab count follows the switch")
    pg.close()

    # 7: board untouched, themes and widths
    for theme in ("dark", "light"):
        for width in (1440, 390):
            pg = page(theme, width)
            sw = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            ok(sw <= 0, f"{theme} {width}px: no sideways scroll ({sw}px)")
            box = pg.evaluate("() => { const w = document.querySelector('#fa-upg .wu'); const r = w.getBoundingClientRect(); return [r.left, r.right, innerWidth, [...w.querySelectorAll('*')].filter(e => { const q = e.getBoundingClientRect(); return q.width && (q.right > r.right + 1 || q.left < r.left - 1); }).length]; }")
            ok(box[0] >= 0 and box[1] <= box[2] and box[3] == 0, f"{theme} {width}px: the section and everything in it fits the screen ({box})")
            if width == 390:
                pg.evaluate("() => document.querySelector('#fa-upg').scrollIntoView()")
                shot(pg, f"waiver-upgrades-phone-{theme}")
            elif theme == "light":
                shot(pg, "waiver-upgrades-desktop-light")
            pg.close()
    ok(not errs, "no page errors" + (f": {errs[:3]}" if errs else ""))
    br.close()

srv.shutdown()
print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
sys.exit(1 if failures else 0)
