"""Trade Calculator: Team 1 is you (Alan, Oct 21). Whenever the calculator opens fresh or the active league changes,
Team 1 is the visitor's own team in the active league; a stale Team 1 from another league never carries over, Team 2 / 3
start unpicked, players that don't fit the new league's rosters are removed, and a Team 1 picked by hand on the open
calculator stands.

Two synthetic 12-team leagues; the visitor (u1) owns roster 3 in "League One" and roster 7 in "League Two", so a kept
roster id would land on someone else's team. Checks:
  1. opening the calculator from another page: Team 1 = my team (also after a hand pick, left and reopened empty)
  2. switching leagues (header menu) before opening it: Team 1 = my team in the new league, Team 2 unpicked
  3. switching leagues while the calculator is open (header menu and the calculator's own league picker): Team 1
     follows, Team 2 / 3 cleared, players not on the new rosters removed (one I still own is kept)
  4. a manual Team 1 on the open calculator isn't snapped back (a re-render, a same-league refresh)
Also: both themes and a 390px phone render the setup bar with Team 1 = my team, no page errors.
Run from the repo root:  python3 tests/tc_team1_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = [r for r in csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())) if r["sleeper_id"]]
rows.sort(key=lambda r: int(r["rank"]))
POOL = [r["sleeper_id"] for r in rows[:192]]
NAME = {r["sleeper_id"]: r["player"] for r in rows}
MINE = {"L1": 3, "L2": 7}
# League Two deals the same players in a different order, so my League One players sit on other teams there,
# except the first one, who is mine in both
def league(lid):
    teams = [POOL[i::12] for i in range(12)]
    keep = teams[MINE["L1"] - 1][0]                   # my best League One player is mine in League Two too
    if lid == "L2": teams = teams[5:] + teams[:5]     # everyone else's rosters rotate five places
    me = MINE[lid] - 1
    if lid == "L2":
        for t in teams:
            if keep in t: t.remove(keep)
        teams[me].insert(0, keep)
    rosters = [{"roster_id": i + 1, "owner_id": f"o{i+1}" if i != me else "u1", "co_owners": [], "players": t, "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    owners = [r["owner_id"] for r in rosters]
    users = [{"user_id": o, "display_name": o, "metadata": {"team_name": ("Mine " if o == "u1" else "Team ") + lid + "-" + str(i + 1)}, "avatar": ""} for i, o in enumerate(owners)]
    lg = {"league_id": lid, "name": {"L1": "League One", "L2": "League Two"}[lid], "season": "2026", "status": "in_season", "total_rosters": 12,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
          "settings": {"num_teams": 12, "type": 0}}
    return lg, users, rosters
DATA = {lid: league(lid) for lid in ("L1", "L2")}
def owner(lid, sid):
    return next(r["roster_id"] for r in DATA[lid][2] if sid in r["players"])

h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []

    def page(hash="#rankings", theme="dark", width=1400):
        lg1, us1, ro1 = DATA["L1"]
        SL = {"source": "sleeper", "username": "u1", "userId": "u1", "displayName": "u1", "season": "2026",
              "leagues": [{"id": l, "name": DATA[l][0]["name"], "season": "2026", "status": "in_season", "format": ""} for l in ("L1", "L2")],
              "activeId": "L1", "data": {"L1": {"league": lg1, "users": us1, "rosters": ro1}}, "view": "league"}
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
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_tc_mode', 'league'); localStorage.setItem('spm_theme', '{theme}'); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/{hash}"); pg.wait_for_timeout(2500)
        return pg

    def go(pg, name):
        pg.evaluate(f"location.hash = '#{name}'"); pg.wait_for_timeout(500)
    def teams(pg): return pg.evaluate("() => ['A','B','C'].map(s => document.getElementById('team-' + s).value)")
    def setsel(pg, id, v):
        pg.evaluate("""([id, v]) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }""", [id, v]); pg.wait_for_timeout(1200)
    def menu_switch(pg, lid):
        pg.click("#league-chip"); pg.wait_for_timeout(200); pg.click(f"#league-menu [data-league='{lid}']"); pg.wait_for_timeout(1500)
    def add(pg, side, sid):
        pg.fill(f"#search-{side}", NAME[sid]); pg.wait_for_timeout(250); pg.keyboard.press("Enter"); pg.wait_for_timeout(350)

    # 1. opening the calculator from another page
    pg = page("#rankings")
    go(pg, "trade")
    ok(teams(pg)[0] == str(MINE["L1"]) and teams(pg)[1] == "", f"1. opened from Rankings: Team 1 = my team (roster {MINE['L1']}), Team 2 unpicked ({teams(pg)})")
    setsel(pg, "team-A", "5"); go(pg, "rankings"); go(pg, "trade")
    ok(teams(pg)[0] == str(MINE["L1"]), f"1. a hand-picked Team 1 on an empty calculator, left and reopened fresh: my team again ({teams(pg)[0]})")
    pg.close()

    # 2. switching leagues before opening it
    pg = page("#rankings")
    go(pg, "trade"); setsel(pg, "team-B", "4"); go(pg, "rankings")
    menu_switch(pg, "L2")
    ok("League Two" in pg.inner_text("#lc-name"), "2. switched to League Two")
    go(pg, "trade")
    t = teams(pg)
    ok(t[0] == str(MINE["L2"]), f"2. after a league switch elsewhere: Team 1 = my League Two team (roster {MINE['L2']}), not League One's {MINE['L1']} ({t[0]})")
    ok(t[1] == "", f"2. Team 2 from League One isn't kept ({t[1]!r})")
    lbl = pg.evaluate("() => { const s = document.getElementById('team-A'); return s.options[s.selectedIndex].textContent; }")
    ok(lbl.startswith("My Team"), f"2. Team 1's label reads as mine ({lbl!r})")
    pg.close()

    # 3. switching leagues while the calculator is open
    pg = page("#trade")
    ok(teams(pg)[0] == str(MINE["L1"]), f"3. fresh load on the calculator: Team 1 = my team ({teams(pg)})")
    mine1 = [s for s in DATA["L1"][2][MINE["L1"] - 1]["players"]]
    keep, lose = mine1[0], mine1[1]                         # keep: mine in both leagues; lose: someone else's in League Two
    other = DATA["L1"][2][0]["players"][0]                  # roster 1's player in League One
    ok(owner("L2", keep) == MINE["L2"] and owner("L2", lose) != MINE["L2"], "3. fixture: one of my players stays mine in League Two, one doesn't")
    setsel(pg, "team-B", "1")
    add(pg, "B", keep); add(pg, "B", lose); add(pg, "A", other)
    menu_switch(pg, "L2")
    t = teams(pg)
    ok(t[0] == str(MINE["L2"]) and t[1] in ("", str(owner("L2", other))) and t[1] != "1" and t[2] == "", f"3. header switch with the calculator open: Team 1 = my League Two team, League One's Team 2 not kept ({t})")
    html = pg.inner_html(".trade-grid")
    ok(NAME[keep] in html, f"3. {NAME[keep]} (still mine in League Two, Team 1 sends him) stays in the trade")
    ok(NAME[lose] not in html, f"3. {NAME[lose]} (not mine in League Two) was removed")
    a_kept = owner("L2", other) != MINE["L2"]
    ok((NAME[other] in html) == a_kept, f"3. {NAME[other]} (Team 1 gets him; League Two owner roster {owner('L2', other)}) {'kept' if a_kept else 'removed'}")
    # Team 2 refills from the owner of what Team 1 gets (autoPickTeams), never from League One's roster id
    if a_kept: ok(teams(pg)[1] == str(owner("L2", other)), f"3. Team 2 picked from his League Two owner ({teams(pg)[1]})")
    # the calculator's own league picker, back to League One
    setsel(pg, "tc-league", "L1"); pg.wait_for_timeout(800)
    t = teams(pg)
    ok(t[0] == str(MINE["L1"]), f"3. calculator league picker: Team 1 = my League One team ({t})")

    # 4. manual Team 1 override after initialization
    setsel(pg, "team-A", "9")
    pg.click("#clear-btn"); pg.wait_for_timeout(300)
    ok(teams(pg)[0] == "9", f"4. manual Team 1 survives a re-render (Clear) on the open calculator ({teams(pg)[0]})")
    pg.click("#league-chip"); pg.wait_for_timeout(200); pg.click("#league-menu [data-act='refresh']"); pg.wait_for_timeout(1800)
    ok(teams(pg)[0] == "9", f"4. manual Team 1 survives a same-league refresh ({teams(pg)[0]})")
    pg.close()

    # themes and phone
    for theme in ("light", "dark"):
        for w in (1400, 390):
            pg = page("#rankings", theme, w)
            go(pg, "trade")
            ok(teams(pg)[0] == str(MINE["L1"]) and pg.is_visible("#team-A"), f"render {theme} {w}px: Team 1 = my team, picker visible")
            if os.environ.get("SHOTS"): pg.screenshot(path=os.path.join(os.environ["SHOTS"], f"tc_team1_{theme}_{w}.png"))
            pg.close()

    ok(not errs, f"no page errors ({errs[:3]})")
    br.close()
srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
