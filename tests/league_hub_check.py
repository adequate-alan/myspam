"""League hub check: every League tab renders from the selected (mock) Sleeper league, and switching leagues
refreshes them. All league data here is synthetic; no real league data belongs in the repo.

Run from the repo root:  python3 tests/league_hub_check.py   (CHROMIUM=/path/to/chromium if needed)
Optional: SHOTS=/some/dir saves screenshots of each tab.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("SHOTS")
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sids = [r["sleeper_id"] for r in rows if r["sleeper_id"]]
name_of = {r["sleeper_id"]: r["player"] for r in rows}
NOW = int(time.time() * 1000)

def make_league(lid, name, teams, positions, scoring, divisions=None):
    pool = [x for x in sids if x != "7600"][:teams * 12]   # Pat Freiermuth (PIT, played Thursday of week 4) stays available
    rosters = [{"roster_id": i + 1, "owner_id": f"{lid}u{i+1}", "co_owners": [], "players": pool[i::teams], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": (i * 7) % 4, "losses": 3 - (i * 7) % 4, "ties": 0, "fpts": 380 + 9 * i, "fpts_against": 400 - 5 * i}, "metadata": {"streak": "2W" if i % 2 else "1L"}} for i in range(teams)]
    users = [{"user_id": f"{lid}u{i+1}", "display_name": f"manager{i+1}", "metadata": {"team_name": f"{name} Team {i+1}"}} for i in range(teams)]
    league = {"league_id": lid, "name": name, "season": "2026", "status": "in_season", "total_rosters": teams, "roster_positions": positions,
              "scoring_settings": scoring, "settings": {"num_teams": teams, "type": 0, "waiver_type": 2, "waiver_clear_days": 2, "waiver_budget": 100, "leg": 4}}
    slots = [p for p in positions if p not in ("BN", "IR", "TAXI")]
    for r in rosters: r["starters"] = r["players"][:len(slots)]
    free = sids[teams * 12: teams * 12 + 6]
    tx = {1: [{"transaction_id": f"{lid}t1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 1, "status_updated": NOW - 20 * 86400e3,
               "adds": {rosters[1]["players"][3]: 1, rosters[0]["players"][4]: 2}, "drops": {rosters[1]["players"][3]: 2, rosters[0]["players"][4]: 1}, "draft_picks": [], "waiver_budget": []}],
          4: [{"transaction_id": f"{lid}w1", "type": "waiver", "status": "complete", "roster_ids": [3], "leg": 4, "status_updated": NOW - 86400e3,
               "adds": {free[0]: 3}, "drops": {rosters[2]["players"][11]: 3}, "settings": {"waiver_bid": 12}},
              {"transaction_id": f"{lid}w2", "type": "waiver", "status": "failed", "roster_ids": [4], "leg": 4, "status_updated": NOW - 86400e3, "adds": {free[0]: 4}, "drops": None, "settings": {"waiver_bid": 9}},
              {"transaction_id": f"{lid}w3", "type": "waiver", "status": "failed", "roster_ids": [5], "leg": 4, "status_updated": NOW - 86400e3 - 5 * 3600e3, "adds": {free[0]: 5}, "drops": None, "settings": {"waiver_bid": 3}},
              {"transaction_id": f"{lid}w4", "type": "waiver", "status": "failed", "roster_ids": [6], "leg": 4, "status_updated": NOW - 86400e3, "adds": {free[0]: 6}, "drops": None, "settings": {"waiver_bid": 12}, "metadata": {"notes": "Lost on waiver priority."}},
              # Sleeper stamps losing claims at other times than the winner (Oct 4 report): a higher bid that failed on roster size, 9 h earlier
              {"transaction_id": f"{lid}w5", "type": "waiver", "status": "failed", "roster_ids": [7], "leg": 4, "status_updated": NOW - 86400e3 - 9 * 3600e3, "adds": {free[0]: 7}, "drops": None, "settings": {"waiver_bid": 20}, "metadata": {"notes": "Unfortunately, your roster will have too many players after this transaction."}},
              {"transaction_id": f"{lid}f1", "type": "free_agent", "status": "complete", "roster_ids": [1], "leg": 4, "status_updated": NOW - 3600e3, "adds": {free[1]: 1}, "drops": None},
              {"transaction_id": f"{lid}d1", "type": "free_agent", "status": "complete", "roster_ids": [6], "leg": 4, "status_updated": NOW - 7200e3, "adds": None, "drops": {rosters[5]["players"][11]: 6}}]}
    # rosters as they are after these moves: team 3 claimed free[0] and dropped its last player, team 1 added free[1]
    rosters[2]["players"] = rosters[2]["players"][:11] + [free[0]]
    rosters[0]["players"] = rosters[0]["players"] + [free[1]]
    rosters[5]["players"] = rosters[5]["players"][:11]   # team 6 dropped its last player
    rosters[0]["settings"]["waiver_budget_used"] = 40      # Sleeper's own FAAB used for team 1
    # team 5 has two players on IR (still on the roster, as on Sleeper)
    rosters[4]["reserve"] = rosters[4]["players"][2:4]
    if divisions:   # Sleeper divisions: league metadata names them, each roster's settings.division points to one
        league["settings"].update({"divisions": len(divisions), "playoff_teams": 6, "playoff_week_start": 15})
        league["metadata"] = {f"division_{k + 1}": nm for k, nm in enumerate(divisions)}
        for i, r in enumerate(rosters): r["settings"]["division"] = 1 + i * len(divisions) // teams
    mx = []
    for i, r in enumerate(rosters):
        pts = {s: round(3 + (j * 1.7 + i * 2.3) % 20, 2) for j, s in enumerate(r["starters"])}
        mx.append({"roster_id": r["roster_id"], "matchup_id": i // 2 + 1, "points": round(sum(pts.values()), 2), "starters": r["starters"],
                   "starters_points": list(pts.values()), "players": r["players"], "players_points": pts})
    return {"league": league, "users": users, "rosters": rosters, "tx": tx, "mx": mx, "free": free}

SF = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6
L1 = make_league("L1", "Alpha League", 12, SF, {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2, "bonus_rec_te": 0.5}, divisions=["North Shore", "South Side"])
L2 = make_league("L2", "Beta League", 10, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"] + ["BN"] * 6, {"rec": 0.5, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2})
LEAGUES = {"L1": L1, "L2": L2}
TRENDING = sids[200]   # on no roster in either league: Sleeper-wide trending adds

def mx_week(L, w):
    """Weeks 3 and 4 as built above; other weeks pair teams in a rotation (circle method), scored only before week 4"""
    if w in (3, 4): return L["mx"]
    if w > 18: return []
    rs = L["rosters"]; n = len(rs); rest = rs[1:]; k = w % (n - 1)
    order = [rs[0]] + rest[k:] + rest[:k]
    out = []
    for i in range(n // 2):
        for j, r in enumerate((order[i], order[n - 1 - i])):
            pts = round(85 + (i * 13 + w * 7 + j * 29 + r["roster_id"] * 3) % 60, 2) if w < 4 else 0
            out.append({"roster_id": r["roster_id"], "matchup_id": i + 1, "points": pts, "starters": r["starters"], "players": r["players"], "players_points": {}, "starters_points": []})
    return out

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    body = []
    m = re.match(r"/league/(\w+)(/.*)?$", path)
    if path.startswith("/players/nfl/trending/add"): body = [{"player_id": TRENDING, "count": 4200}, {"player_id": sids[201], "count": 75}]
    elif path == "/state/nfl": body = {"season": "2026", "league_season": "2026", "week": 4, "display_week": 4, "season_type": "regular"}
    elif path.startswith("/user/") and "/leagues/" in path: body = [x["league"] for x in LEAGUES.values()]
    elif path.startswith("/user/"): body = {"user_id": "L1u1", "username": "tester", "display_name": "tester"}
    elif m and m.group(1) in LEAGUES:
        L, rest = LEAGUES[m.group(1)], m.group(2) or ""
        if rest == "": body = L["league"]
        elif rest == "/users": body = L["users"]
        elif rest == "/rosters": body = L["rosters"]
        elif rest.startswith("/transactions/"): body = L["tx"].get(int(rest.rsplit("/", 1)[1]), [])
        elif rest.startswith("/matchups/"): body = mx_week(L, int(rest.rsplit("/", 1)[1]))
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    h.log_message = lambda *a: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(2000)
    base_board = pg.evaluate("() => SPM.rankingSnapshot ? JSON.stringify(SPM.rankingSnapshot()) : ''")
    # connect through the UI: username -> pick league
    pg.wait_for_timeout(2500)   # the update check may reload the page once
    # open the Sleeper connect dialog through the league menu's own "account" action
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    ok("tester" in pg.evaluate("() => localStorage.getItem('spm_sleeper') || ''"), "League data is kept in this browser's localStorage")

    # Superflex league vs a saved 1QB custom format (the Oct 4 "QB values collapsed" report)
    def qb_values():
        pg.click("#tab-rankings"); pg.wait_for_timeout(500)
        return pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#rank-body tr.player')].map(tr => [(tr.querySelector('.pos-col .pos') || {}).textContent, tr.querySelector('.val .num, .val .num-btn').textContent.replace(/\\D/g, '')]).filter(([k]) => k && k.startsWith('QB')).map(([k, v]) => [k, Number(v)]))""")
    sf = qb_values()
    # Rankings polish (Alan, Oct 5): your players get a thin gold edge + dot, not a selected-looking row
    mine_rows = pg.locator("#rank-body tr.player.mine")
    ok(mine_rows.count() > 0 and mine_rows.first.locator(".own-tag.mine").count() == 1 and pg.locator("#rank-body tr.player:not(.mine) .own-tag.mine").count() == 0, f"My players are marked on the board ({mine_rows.count()})")
    geo = pg.evaluate("""() => { const rows = [...document.querySelectorAll('#rank-body tr.player')].slice(0, 40);
      const mid = e => { if (!e) return null; const r = e.getBoundingClientRect(); return r.height ? r.top + r.height / 2 : null; };
      let off = 0; rows.forEach(r => { const ref = mid(r.querySelector('td.rk'));
        [r.querySelector('.face'), r.querySelector('.pos-col .pos'), r.querySelector('.valbar .track'), r.querySelector('.valbar .num')].forEach(e => { const v = mid(e); if (v != null && Math.abs(v - ref) > 1.5) off++; }); });
      const hs = rows.map(r => r.getBoundingClientRect().height);
      const tall = rows.filter(r => r.getBoundingClientRect().height > Math.min(...hs) + 1).map(r => r.querySelector('td.rk').innerText.replace(/\\s+/g, ' '));
      return { tall, face: rows[0].querySelector('.face').getBoundingClientRect().width, min: Math.min(...hs), max: Math.max(...hs), off }; }""")
    ok(geo["face"] == 46 and geo["max"] <= 60 and geo["max"] - geo["min"] < 1 and geo["off"] == 0, f"Rankings headshots 46px (Oct 8 redesign), rows compact and even, rank/photo/badge/bar centered: {geo}")
    if SHOTS:
        mine_rows.first.scroll_into_view_if_needed(); pg.wait_for_timeout(200)
        pg.screenshot(path=f"{SHOTS}/rankings_league.png")
    ok(pg.locator("#fmt-override").is_hidden() and "custom" not in pg.inner_text("#lc-format").lower(), "Superflex league on its own settings: no custom-format notice")
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.openFmt = ''; document.body.append(b); b.click(); b.remove(); }"); pg.wait_for_timeout(300)
    pg.click("[data-fmt-src=custom]"); pg.click("button[data-fmt=qb][data-v='1']"); pg.click("#fmt-apply"); pg.wait_for_timeout(800)
    one = qb_values()
    ok("custom" in pg.inner_text("#lc-format").lower() and pg.locator("#fmt-override").is_visible(), "A custom 1QB format shows in the league chip and as a notice on every tab")
    ok(sf["QB12"] > 2 * one["QB12"] and sf["QB20"] > 3 * one["QB20"], f"Superflex QB values are far above the custom 1QB ones: QB12 {sf['QB12']} vs {one['QB12']}, QB20 {sf['QB20']} vs {one['QB20']}")
    pg.click("[data-use-league]"); pg.wait_for_timeout(800)
    back = qb_values()
    ok(back == sf and pg.locator("#fmt-override").is_hidden(), "One click goes back to the league's own Superflex values")
    checks = pg.evaluate("() => SPM.formatCheck()")
    for c in checks:
        ok(c["pass"], "formatCheck: " + c["check"] + " " + str(c["values"])[:160])

    pg.click("#tab-league"); pg.wait_for_timeout(600)
    tabs = pg.locator("[data-lsub]").all_inner_texts()
    ok(tabs == ["Power Rankings", "Standings", "Matchups", "Rosters", "Transactions", "Waiver Wire"], f"League sub-tabs: {tabs}")
    ok(pg.locator("[data-lsub=power][aria-pressed=true]").count() == 1, "Power Rankings is the default")
    nav = [t.strip() for t in pg.locator(".tabs [role=tab]").all_inner_texts() if t.strip()]
    ok(nav == ["Rankings", "My Team", "League", "Trade Finder", "Trade Calculator"], f"Main nav: {nav}")
    ok(pg.locator(".pr-item").count() == 12, "Power rankings list all 12 teams")
    pg.locator(".pr-item .pr-row").nth(2).click(); pg.wait_for_timeout(400)
    ok(pg.locator(".pr-item.open .tx-board").count() == 1, "Clicking a team row expands its roster inline")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_power.png", full_page=False)
    # IR players count toward team strength (Alan, Oct 5): listed in their position columns with an IR tag, never as starters
    ir_names = [name_of[x] for x in L1["rosters"][4]["reserve"]]
    row5 = pg.locator(".pr-item", has=pg.locator(".pr-name", has_text="Alpha League Team 5"))
    score_before = row5.locator(".pr-score").inner_text()
    if "open" not in (row5.get_attribute("class") or ""):   # it may already be the row opened above
        row5.locator(".pr-row").click(); pg.wait_for_timeout(400)
    ir_rows = row5.locator(".tx-col .tx-pl.ir")
    ok(ir_rows.count() == 2 and all(n in " ".join(ir_rows.all_inner_texts()) for n in ir_names), f"IR players sit in their position columns: {ir_names} (found {ir_rows.all_inner_texts()})")
    ok(all(t.strip() == "IR" for t in ir_rows.locator(".tx-role").all_inner_texts()), "IR players carry an IR tag, not a starter slot")
    ok("Injured reserve counts as if healthy" in pg.inner_text(".method-note"), "Power Rankings note says IR counts")
    # Position lens (Alan, Oct 5): a position rank re-sorts the Power Rankings list in place, selected team highlighted
    rb_place = row5.locator('.tx-sum[data-pos-board="RB"] b').inner_text()
    row5.locator('.tx-sum[data-pos-board="RB"]').click(); pg.wait_for_timeout(500)
    ranks = [int(x) for x in pg.locator(".pr-item .pr-rank").all_inner_texts()]
    sel = pg.locator(".pr-item.sel")
    ok(pg.locator("#pos-board").count() == 0 and "RB ROOM" in pg.inner_text(".pr-head").upper() and ranks == list(range(1, 13)), f"RB lens re-sorts the same list 1-12: {ranks}")
    ok(sel.count() == 1 and "Alpha League Team 5" in sel.inner_text() and sel.locator(".pr-rank").inner_text() == str(int(re.sub(r'\D', '', rb_place))), f"Team 5 highlighted at its RB place ({rb_place})")
    ok("RB " + rb_place in pg.inner_text(".pb-ctx") and "vs league average" in pg.inner_text(".pb-ctx"), "Context line: place, vs average, gaps")
    scores = [int(x.replace(",", "")) for x in pg.locator(".pr-item .pr-score").all_inner_texts()]
    ok(scores == sorted(scores, reverse=True), "Best -> Worst order by RB room")
    pg.click("[data-pb-pos=WR]"); pg.wait_for_timeout(400)
    names = pg.locator(".pr-item").first.locator(".pr-star-names").inner_text()
    ok("WR ROOM" in pg.inner_text(".pr-head").upper() and len(names.split(" · ")) == 3, f"3-WR league: the WR lens shows each team's top 3 WRs ({names})")
    pg.click("[data-pb-dir=asc]"); pg.wait_for_timeout(300)
    ok([int(x) for x in pg.locator(".pr-item .pr-rank").all_inner_texts()] == list(range(12, 0, -1)), "Worst -> Best flips to 12 ... 1")
    pg.click("[data-pb-pos=QB]"); pg.wait_for_timeout(300)
    ok(len(pg.locator(".pr-item").first.locator(".pr-star-names").inner_text().split(" · ")) == 2, "Superflex: the QB lens shows the top 2 QBs")
    pg.click("[data-pb-pos=TE]"); pg.wait_for_timeout(300)
    ok(all(len(t.split(" · ")) == 1 for t in pg.locator(".pr-item .pr-star-names").all_inner_texts()), "1-TE league: one TE shown")
    pg.click("[data-pb-pos=DEPTH]"); pg.wait_for_timeout(300)
    ok("DEPTH SCORE" in pg.inner_text(".pr-head").upper(), "Depth lens")
    pg.click("[data-pb-pos=OVERALL]"); pg.wait_for_timeout(300)
    ok(pg.locator(".pb-ctx").count() == 0 and "TEAM SCORE" in pg.inner_text(".pr-head").upper(), "Overall restores the normal Power Rankings")
    # Switching lens never scrolls by itself (Alan, Oct 5): same scroll position, no focus on the team row
    pg.set_viewport_size({"width": 1280, "height": 500})
    pg.evaluate("window.scrollTo(0, document.querySelector('.pb-modes').getBoundingClientRect().top + window.scrollY - 120)")
    pg.wait_for_timeout(200)
    y0 = pg.evaluate("window.scrollY")
    ys = []
    for k in ["RB", "WR", "QB", "TE", "DEPTH", "OVERALL"]:
        pg.evaluate(f"document.querySelector('[data-pb-pos={k}]').click()"); pg.wait_for_timeout(250)
        ys.append(pg.evaluate("window.scrollY"))
    pg.evaluate("document.querySelector('.pr-item .tx-sum[data-pos-board], .pr-item .pr-pos-item[data-pos-board]').click()"); pg.wait_for_timeout(250)
    ys.append(pg.evaluate("window.scrollY"))
    pg.evaluate("document.querySelector('[data-pb-dir=asc]').click()"); pg.wait_for_timeout(250)
    ys.append(pg.evaluate("window.scrollY"))
    ok(all(abs(y - y0) < 1 for y in ys) and not pg.evaluate("!!document.activeElement.closest('.pr-item.sel')"), f"Switching lens keeps the scroll position ({y0} -> {ys})")
    pg.evaluate("document.querySelector('[data-pb-dir=desc]').click()"); pg.wait_for_timeout(200)
    jump = pg.locator(".pb-jump")
    ok(jump.count() == 1, "Jump to team button in the context line")
    jump.click(); pg.wait_for_timeout(900)
    box = pg.locator(".pr-item.sel").bounding_box()
    ok(box and 0 <= box["y"] and box["y"] + box["height"] <= 500, "Jump to team scrolls the highlighted team into view")
    pg.set_viewport_size({"width": 1440, "height": 1000})
    pg.click("[data-pb-pos=OVERALL]"); pg.wait_for_timeout(300)
    pg.locator(".pr-item .pr-pos-item[data-pos-board]").first.click(); pg.wait_for_timeout(400)
    ok(pg.locator(".pr-item.sel").count() == 1 and pg.locator(".pb-ctx").count() == 1, "A collapsed row's Best/Weakest switches the lens for that team")
    pg.click("[data-pb-pos=OVERALL]"); pg.wait_for_timeout(300)
    row5 = pg.locator(".pr-item", has=pg.locator(".pr-name", has_text="Alpha League Team 5"))
    ok(row5.locator(".pr-score").inner_text() == score_before, "Team score is the same with the team expanded")
    if SHOTS: row5.screenshot(path=f"{SHOTS}/hub_ir.png")

    pg.click("[data-lsub=standings]"); pg.wait_for_timeout(400)
    st = pg.inner_text(".st-table thead")
    ok("AM POWER RANK" in st.upper() and "MANAGER" in st.upper() and "DIFFERENCE" in st.upper(), "Standings show manager, AM Power Rank and the difference")
    ok(pg.locator(".st-table tbody tr.st-row").count() == 12, "Standings list all teams")
    # Sleeper divisions: grouped under their names, ranked inside each division (wins, then PF)
    pg.wait_for_timeout(1500)
    divs = pg.locator(".st-table tr.st-div").all_inner_texts()
    ok([x.strip() for x in divs] == ["North Shore", "South Side"], f"Standings are grouped by the league's division names: {divs}")
    groups = pg.evaluate("""() => { const out = []; let cur = null; document.querySelectorAll('.st-table tbody tr').forEach(tr => {
        if (tr.classList.contains('st-div')) { cur = []; out.push(cur); return; }
        const c = tr.querySelectorAll('td'); cur.push([c[0].textContent.trim(), c[3].textContent.trim(), Number(c[4].textContent.replace(/,/g, '')) || 0, tr.dataset.standingTeam]); }); return out; }""")
    def wins(rec): return int(rec.split("-")[0])
    ordered = all([g[i][0] for i in range(len(g))] == [str(i + 1) for i in range(len(g))] and all((wins(g[i][1]), g[i][2]) >= (wins(g[i + 1][1]), g[i + 1][2]) for i in range(len(g) - 1)) for g in groups)
    ok(len(groups) == 2 and all(len(g) == 6 for g in groups) and ordered, f"Each division has its 6 teams ranked 1-6 by wins, then PF")
    ok(set(r[3] for r in groups[0]) == {str(i) for i in range(1, 7)}, "Teams sit in their Sleeper division")
    # playoff odds: far right column, a percentage per team, summing to the 6 playoff spots
    head = pg.locator(".st-table thead th").all_inner_texts()
    ok(head[-1].strip().upper().startswith("PLAYOFF ODDS"), f"Playoff odds is the last column: {head[-1]}")
    odds = pg.evaluate("() => [...document.querySelectorAll('.st-table td.st-odds')].map(td => (td.querySelector('b') || td).textContent.trim())")
    nums = [100.0 if o == ">99%" else 0.5 if o == "<1%" else float(o.rstrip("%")) for o in odds if o.endswith("%")]
    ok(len(nums) == 12 and abs(sum(nums) - 600) < 25, f"Playoff odds for all 12 teams add up to ~6 spots: {odds}")
    tip = pg.locator(".st-table td.st-odds").first.get_attribute("title") or ""
    ok("projected" in tip and "remaining schedule" in tip, f"Odds tooltip: projected wins and remaining schedule ({tip[:90]})")
    po = pg.evaluate("""() => { const r = {}; document.querySelectorAll('.st-table tr.st-row').forEach(tr => { r[tr.dataset.standingTeam] = (tr.querySelector('.st-odds b') || {}).textContent; }); return r; }""")
    pg.click("[data-st-view=league]"); pg.wait_for_timeout(300)
    ok(pg.locator(".st-table tr.st-div").count() == 0 and pg.locator(".st-table tr.st-row").count() == 12, "League view: one table, no division headers")
    po2 = pg.evaluate("""() => { const r = {}; document.querySelectorAll('.st-table tr.st-row').forEach(tr => { r[tr.dataset.standingTeam] = (tr.querySelector('.st-odds b') || {}).textContent; }); return r; }""")
    ok(po == po2, "Odds are stable between redraws (seeded simulation)")
    pg.click("[data-st-view=div]"); pg.wait_for_timeout(300)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_standings.png")

    pg.click("[data-lsub=matchups]"); pg.wait_for_timeout(1500)
    ok(pg.locator(".mx-card").count() == 6, f"Week 4 shows 6 matchups ({pg.locator('.mx-card').count()})")
    card = pg.locator(".mx-card").first
    ok(card.locator(".mx-pr").count() == 2 and card.locator(".mx-score").count() == 2, "Each side: AM PR badge and a big score")
    projs = card.locator(".mx-proj").all_inner_texts()
    ok(len(projs) == 2 and all(re.search(r"^LIVE PROJ\s+\d+\.\d", t.upper().strip()) for t in projs), f"Live proj under each score before kickoff: {projs}")
    ok(all(t.upper().strip().startswith("LIVE PROJ") for t in pg.locator(".mx-proj").all_inner_texts()) and "APPROX" not in pg.inner_text("#league-body").upper(), "One label everywhere: Live proj")
    full_cards = partial_cards = 0
    for c in pg.locator(".mx-card").all():
        pj = c.locator(".mx-proj").all_inner_texts()
        if c.locator(".mx-bar").count():
            pcts = [float(t.rstrip('%')) for t in c.locator(".mx-pct").all_inner_texts()]
            tot = [float(re.search(r"(\d+\.\d)", t).group(1)) for t in pj]
            ok(abs(sum(pcts) - 100) < 0.2 and abs(pcts[0] - 100 * tot[0] / sum(tot)) < 0.2 and not any("*" in t for t in pj), f"Projected matchup bar = share of the two totals: {pcts} from {tot}")
            full_cards += 1
        else:
            ok(c.locator(".mx-partial").count() == 1 and any("*" in t for t in pj), "A partial projection hides the bar and says so")
            partial_cards += 1
    ok(full_cards >= 1, f"Fully projected matchups show the bar ({full_cards} full, {partial_cards} partial)")
    ok("WIN PROBABILITY" not in pg.inner_text("#league-body").upper() and "TOP PLAYERS" not in pg.inner_text("#league-body").upper(), "No win probability label and no top-players clutter")
    ok("PROJECTIONS: AM" in pg.inner_text(".mx-source").upper(), "Data source line: Scores Sleeper · Projections AM")
    card.locator(".mx-show").click(); pg.wait_for_timeout(400)
    ok(pg.locator(".mx-card.open .mx-lineup").count() == 2, "Show lineups expands both starting lineups side by side")
    ok(pg.locator(".mx-card.open .mx-table tr").count() >= 16, "Lineups list every starter")
    # by game state (the test runs against the real clock): upcoming = projection, live = points + Live proj, final = points
    ok(pg.locator(".mx-card.open .mx-pts.up b, .mx-card.open .mx-pts.live b, .mx-card.open .mx-pts.final b").count() >= 10, "Every starter shows his projection or points")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_matchups.png", full_page=True)
    pg.evaluate("() => { const s = document.getElementById('mx-week'); s.value = '3'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(1200)
    ok(pg.locator(".mx-card.final").count() == 6 and pg.locator(".mx-res.win").count() >= 5 and pg.locator(".mx-bar").count() == 0, "A past week: final scores, the winner marked, no projection bar")
    pg.click("[data-mx-week='4']"); pg.wait_for_timeout(800)

    # Trade Calculator: roster strips, auto-picked teams, before -> after impact, balance + Undo
    pg.click("#tab-trade"); pg.wait_for_timeout(600); pg.click("#clear-btn")
    pg.evaluate("() => { for (const s of ['A','B']) { const x = document.getElementById('team-'+s); x.value=''; x.dispatchEvent(new Event('change', {bubbles:true})); } }"); pg.wait_for_timeout(300)
    pg.fill("#search-A", name_of[L1["rosters"][2]["players"][0]]); pg.wait_for_timeout(300); pg.locator("#results-A li, #results-A button").first.click(); pg.wait_for_timeout(300)
    pg.fill("#search-B", name_of[L1["rosters"][0]["players"][1]]); pg.wait_for_timeout(300); pg.locator("#results-B li, #results-B button").first.click(); pg.wait_for_timeout(500)
    ok(pg.input_value("#team-A") == "1" and pg.input_value("#team-B") == "3", "Calculator: empty team pickers fill from the owners of the players each side sends")
    ok("Alpha League Team 1" in pg.inner_text("#side-title-A") and "Alpha League Team 3" in pg.inner_text("#side-title-B"), "Cards are headed with the real team names")
    ok(pg.locator("#teamroster-A .rs-card").count() >= 10 and pg.locator("#teamroster-B .rs-card").count() >= 10 and pg.locator(".rs-card.on").count() == 2, "Each side shows the partner's roster as a strip; players in the deal are selected")
    ba = pg.inner_text("#tc-ba").upper()
    ok(pg.locator("#tc-ba").is_visible() and "POWER RANK" in ba and ba.count("→") >= 10, "Before -> after: Power rank and QB/RB/WR/TE ranks for both teams")
    n0 = pg.locator(".rs-card.on").count()
    pg.locator("#teamroster-A button.rs-card:not(.on)").first.click(); pg.wait_for_timeout(300)
    n1 = pg.locator(".rs-card.on").count()
    pg.locator("#teamroster-A button.rs-card.on").last.click(); pg.wait_for_timeout(300)
    ok(n1 == n0 + 1 and pg.locator(".rs-card.on").count() == n0, "Clicking a roster card adds him; clicking again removes him")
    if pg.locator("#balance-btn").is_visible():
        pg.click("#balance-btn"); pg.wait_for_timeout(300)
        if pg.locator("#balance-list button").count():
            c0 = pg.locator(".roster li").count(); pg.locator("#balance-list button").first.click(); pg.wait_for_timeout(400)
            c1 = pg.locator(".roster li").count(); pg.click("#bal-undo"); pg.wait_for_timeout(400)
            ok(c1 > c0 and pg.locator(".roster li").count() == c0, "A balance suggestion adds itself to the trade, and Undo takes it back")
    ok("HOW AM CALCULATED THIS" in pg.inner_text("#tc-breakdown summary").upper(), "Technical math sits in one collapsed 'How AM calculated this' section")
    pg.click("#clear-btn")

    # My Team (Oct 4 follow-up): clean roster page: compact header with Trade with, full-width roster, one weekly state per row,
    # side rail: Team insights (with Trade with at its bottom) + Hot lately; dense rows (Oct 5)
    pg.click("#tab-myteam"); pg.wait_for_timeout(1200)
    ok(pg.locator(".mt-summary .mt-pr").count() == 1 and pg.locator(".mt-side [data-trade-with]").count() == 1, "My Team: compact header; Trade with in the side rail")
    ok(pg.locator(".mt-take, .nb-row").count() == 0, "No takeaway block or repeated position ranks")
    ok("TEAM INSIGHTS" in pg.inner_text(".mt-side").upper() and "HOT LATELY" in pg.inner_text(".mt-side").upper(), "Side rail: Team insights, Hot lately, Trade with")
    ok(pg.locator(".mt-side .mt-ctx [data-trade-with]").count() == 1 and pg.locator(".mt-side .mt-card").count() <= 2, "Trade with sits inside the Team insights card (no third card)")
    rh = pg.evaluate("() => Math.max(...[...document.querySelectorAll('.mt-table tr.mt-row')].map(r => r.getBoundingClientRect().height))")
    ok(rh <= 52, f"Dense roster rows: tallest {rh:.0f}px")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_myteam.png", full_page=True)
    wk = [t.upper() for t in pg.locator("td.mt-wk").all_inner_texts()]
    ok(len(wk) >= 9 and "THIS WEEK" in pg.inner_text(".mt-table thead").upper() and not any("LIVE · LIVE PROJ" in t or "FINAL ·" in t for t in wk), f"One weekly state per row: {wk[:4]}")
    # Trade Finder goals: Slight edge / Best value ideas favor you within their range and are labelled as such (never "steal")
    pg.click("#tab-finder"); pg.wait_for_timeout(1200)
    pv = pg.evaluate("() => [...document.getElementById('tf-player').options].map(o => o.value)")[:6]
    for goal, lo, hi, word in (("edge", 3, 10, "SLIGHT EDGE TO YOU"), ("value", 8, 15, "GOOD VALUE FOR YOU")):
        pg.evaluate(f"() => {{ const s = document.getElementById('tf-goal'); s.value = '{goal}'; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}"); pg.wait_for_timeout(300)
        seen, good = 0, True
        for v in pv:
            pg.evaluate(f"() => {{ const s = document.getElementById('tf-player'); s.value = '{v}'; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}"); pg.wait_for_timeout(300)
            for c in pg.locator(".tf-card:not(.tf3)").all():
                seen += 1
                vt, df = c.locator(".tf-verdict-big").inner_text().upper(), float(c.locator(".tf-diff").inner_text().split("%")[0])
                good = good and vt.startswith(word) and "STEAL" not in vt and lo - 0.05 <= df <= hi + 0.05
        ok(seen > 0 and good, f"Trade goal '{goal}': {seen} ideas, all {lo}-{hi}% in your favor and labelled '{word.title()}'")
    pg.evaluate("() => { const s = document.getElementById('tf-goal'); s.value = 'fair'; s.dispatchEvent(new Event('change', {bubbles:true})); }")
    # Trade types: 1-for-1, 1-for-2, 2-for-1, All packages (counted from the starting team's side)
    labels = pg.locator("#tf-size button").all_inner_texts()
    ok(labels == ["1-for-1", "1-for-2", "2-for-1", "All packages"], f"Trade type buttons: {labels}")
    def shapes(kind):
        pg.click(f"#tf-size [data-size='{kind}']"); pg.wait_for_timeout(250)
        out = set()
        for v in pv[:4]:
            pg.evaluate(f"() => {{ const s = document.getElementById('tf-player'); s.value = '{v}'; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}"); pg.wait_for_timeout(250)
            out |= set(t.strip().lower() for t in pg.locator(".tf-card:not(.tf3) .tf-size").all_inner_texts())
        return out
    for kind, want in (("11", {"1-for-1"}), ("12", {"1-for-2"}), ("21", {"2-for-1"})):
        got = shapes(kind)
        ok(got == want, f"Trade type {want.pop()}: only that shape ({got})")
    got = shapes("all")
    ok(len(got) >= 2 and got <= {"1-for-1", "1-for-2", "2-for-1", "2-for-2"}, f"All packages mixes shapes ({got})")
    pg.click("#tab-league"); pg.wait_for_timeout(500)

    # Rosters: team picker, header, week nav, dense table by section, season schedule
    pg.click("[data-lsub=rosters]"); pg.wait_for_timeout(2500)
    ok(pg.locator(".ro-pick").count() == 12 and "You" in pg.locator(".ro-pick.on").inner_text(), "Rosters: a picker with every team, your team selected first")
    hd = pg.inner_text(".ro-head").upper()
    ok(all(k in hd for k in ("AM PR", "RECORD", "PF", "PA", "FAAB")) and "$60" in hd, f"Team header: AM PR, record, PF, PA and FAAB left ($100 − $40): {hd[:160]}")
    th = [t.strip().upper() for t in pg.locator(".ro-table thead th").all_inner_texts()]
    ok(th == ["SLOT", "PLAYER", "WK 4", "SZN RK", "AM RK", "GP", "FPTS", "PPG"], f"Roster columns: {th}")
    secs = [t.split("\n")[0].upper() for t in pg.locator(".ro-sec .ro-sec-t").all_inner_texts()]
    ok(secs[:2] == ["STARTERS9", "BENCH4"] or (secs[0].startswith("STARTERS") and secs[1].startswith("BENCH")), f"Starters and Bench sections: {secs}")
    slots = [t.strip() for t in pg.locator(".ro-row:not(.bn):not(.inactive) .ro-sl").all_inner_texts()]
    ok(slots == ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SF"], f"Starter slots in league order with AM slot colors: {slots}")
    ok(pg.locator(".ro-row:not(.bn) td.ro-wk").count() >= 9 and pg.locator(".ro-row .ro-g").count() >= 9, "Each starter shows his week and the matchup under his name")
    ok(pg.locator(".ro-sw").count() == 14 and "3 played" in pg.inner_text(".ro-sched .rail-title"), f"Season schedule lists every regular-season week (playoffs start week 15) with 3 played ({pg.locator('.ro-sw').count()})")
    ok(pg.locator(".ro-res.w, .ro-res.l, .ro-res.t").count() == 3, "Played weeks show W/L")
    pg.locator(".ro-row:not(.bn)").first.click(); pg.wait_for_timeout(300)
    ok("AM VALUE" in pg.inner_text(".ro-detail").upper(), "A player row expands to show his AM value")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_rosters.png", full_page=True)
    pg.click("[data-ro-week='3']"); pg.wait_for_timeout(1200)
    ok(pg.locator(".ro-wk.final").count() >= 9 and "WK 3" in pg.inner_text(".ro-table thead").upper(), "Week 3: Sleeper's recorded lineup with final points")
    pg.locator(".ro-pick").nth(3).click(); pg.wait_for_timeout(500)
    ok("You" not in pg.inner_text(".ro-name"), "Picking another team shows its roster")
    pg.locator(".ro-sw-btn").nth(1).click(); pg.wait_for_timeout(1500)
    ok(pg.locator("[data-lsub=matchups][aria-pressed=true]").count() == 1 and pg.locator(".mx-card.open").count() == 1 and pg.input_value("#mx-week") == "2", "Clicking a schedule week opens that matchup")
    pg.click("[data-mx-week='4']"); pg.wait_for_timeout(800)

    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(1500)
    items = lambda: pg.locator(".tx-feed .mv-row, .tx-feed .tx-trade-card").count()
    weeks = [h.strip() for h in pg.locator(".tx-week-head h3").all_inner_texts()]
    ok(weeks == ["Week 4"] and items() == 3, f"Grouped by week, newest week first by default: {weeks}, {items()} moves")
    wsum = pg.inner_text(".tx-week-sum")
    ok(wsum == "1 claim · 2 adds/drops · $12 FAAB spent", f"Week summary from real data: {wsum}")
    ok(pg.locator(".tx-feed .mv-list .mv-row").count() == 3 and pg.locator(".tx-feed .mv-row").first.bounding_box()["height"] < 60, "Waiver claims, adds and drops are dense rows, not cards")
    pg.click("[data-tx-older]"); pg.wait_for_timeout(400)
    weeks = [h.strip() for h in pg.locator(".tx-week-head h3").all_inner_texts()]
    ok(weeks == ["Week 4", "Week 1"] and items() == 4 and pg.locator("[data-tx-older]").count() == 0, f"Load older transactions adds the next week: {weeks}")
    ok(pg.locator(".tx-trade-card .mv-tag.trade").count() == 1, "Trades are their own highlighted cards with a TRADE badge")
    tx_filters = pg.locator("[data-tx-type]").all_inner_texts()
    ok(tx_filters == ["All", "Trades", "Waiver Wire"], f"Transaction filters: {tx_filters}")
    tags = sorted(t.strip().lower() for t in pg.locator(".mv-row .mv-tag").all_inner_texts())
    ok(tags == ["drop", "free agent", "waiver claim"], f"Each move card says what it was: {tags}")
    ok(pg.locator(".mv-bidders").first.inner_text().strip().lower() == "5 bidders", "Waiver claim counts all 5 bidders, incl. failed claims stamped hours apart")
    ok(pg.locator(".mv-row.waiver .mv-kind .mv-bidders").count() == 1 and pg.locator(".mv-row.waiver .mv-acts .mv-bidders").count() == 0, "Bidder count sits beside WAIVER CLAIM, FAAB stays with the claim")
    ok(pg.evaluate("() => getComputedStyle(document.querySelector('.tx-rail')).position") == "sticky", "The League Activity rail is sticky on desktop")
    rail = pg.locator(".tx-rail")
    ok(rail.is_visible() and pg.evaluate("() => document.querySelector('.tx-rail').getBoundingClientRect().left > document.querySelector('.tx-feed').getBoundingClientRect().right"), "League Activity rail sits beside the feed on desktop")
    faab = [" ".join(x.split()) for x in rail.locator(".rail-card").first.locator("li").all_inner_texts()]
    left = [int(re.search(r"\$(\d+)", x).group(1)) for x in faab]
    ok(len(faab) == 12 and left == sorted(left, reverse=True), f"FAAB remaining for all 12 teams, highest first: {faab[:3]} … {faab[-2:]}")
    ok(any("Team 1" in x and "$60" in x for x in faab) and any("Team 3" in x and "$88" in x for x in faab), "FAAB uses Sleeper's budget used, else winning bids in the log")
    ok(rail.locator("li.mine").count() >= 1, "Your team is highlighted in the rail")
    act = rail.locator(".rail-card").nth(1).inner_text()
    ok("WEEK 4" in act.upper() and "1 move" in act, f"Most active this week: {' '.join(act.split())[:90]}")
    top = rail.locator(".rail-card").nth(2).inner_text()
    ok("$12" in top and name_of[L1["free"][0]] in top, "Top waiver claims for the week")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(300)
    ok(pg.locator("#bids-dialog").is_visible(), "Clicking the bidder count opens the bids")
    bids = [" | ".join(x.split()) for x in pg.locator("#bids-dialog .bids-list li").all_inner_texts()]
    print("   bids:", bids)
    ok(len(bids) == 5 and bids[0].startswith("$12") and "WON" in bids[0].upper() and "Team | 3" in bids[0], "Winner first, even when a failed claim bid more")
    ok(bids[1].startswith("$20") and "NOT | AWARDED" in bids[1].upper() and "too | many | players" in bids[1], "A higher bid that failed shows Sleeper's reason (roster too full)")
    ok("TIE-BREAK" in bids[2].upper() and "$12" in bids[2] and "OUTBID" in bids[3].upper() and bids[3].startswith("$9") and bids[4].startswith("$3"), "Tie shown as lost tie-break, then outbid bids high to low")
    ok("tie at $12" in pg.inner_text("#bids-dialog").lower(), "The tie is explained, without inventing a waiver priority")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "Escape closes the bids")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(200); pg.mouse.click(10, 10); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "Clicking outside closes the bids")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(200); pg.click("#bids-close"); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "The X closes the bids")
    fw = pg.evaluate("() => document.querySelector('.tx-feed').getBoundingClientRect().width")
    ok(fw <= 960, f"Transactions feed stays compact on desktop ({fw:.0f}px)")
    ok(pg.locator(".mv-row.free_agent .mv-p.drop").count() == 0 and pg.locator(".mv-row.drop .mv-p.add").count() == 0, "Only what exists is shown: no empty adds or drops")
    ok("$12" in pg.inner_text(".mv-row.waiver") and pg.locator(".mv-row.waiver .mv-faab-amt.big").count() == 1, "Waiver claim shows the FAAB bid, emphasized when it's big")
    ok(pg.locator(".mv-row.waiver .mv-p.drop").count() == 1, "Waiver claim shows the drop")
    ok(pg.locator(".th-tag.pre").count() == 1, "An old trade is labeled Pre-AM")
    pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
    ok(items() == 1 and pg.locator("[data-th-analyze]").count() == 1, "Trades filter shows the trade with Analyze trade")
    pg.click("[data-tx-type=moves]"); pg.wait_for_timeout(300)
    ok(pg.locator(".tx-feed .mv-row").count() == 3 and items() == 3, "Waiver Wire filter shows the claim, the add and the drop (no trades)")
    pg.click("[data-tx-type=all]"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('tx-week'); s.value = '1'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    ok(items() == 1, "Week filter")
    pg.evaluate("() => { const s = document.getElementById('tx-week'); s.value = 'all'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('tx-team'); s.value = '3'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    ok(items() == 1, "Team filter")
    pg.evaluate("() => { const s = document.getElementById('tx-team'); s.value = 'all'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    if SHOTS: pg.click("[data-tx-older]"); pg.wait_for_timeout(300); pg.screenshot(path=f"{SHOTS}/hub_tx.png")

    pg.click("[data-lsub=waivers]"); pg.wait_for_timeout(800)
    n_fa = pg.locator("#fa-body tr.player").count()
    ok(n_fa > 20, f"Waiver Wire lists available players ({n_fa})")
    names = pg.locator("#fa-body tr.player .pl-name").all_inner_texts()
    ok(name_of.get(L1["free"][0]) not in names, "A player claimed on waivers isn't listed as available")
    ok(pg.locator(".fa-fit-t").count() == n_fa, "Each available player shows where he'd fit on your team")
    ok(pg.locator(".fa-avail.waivers").count() >= 1, "A recently dropped player shows as on waivers")
    head = [h.strip().upper() for h in pg.locator("#fa-head th").all_inner_texts()]
    ok(head == ["RK", "PLAYER", "POS", "WK 4", "RECENT FORM", "MATCHUP", "SZN RK", "FPTS", "PPG", "FIT"], f"Waiver Wire columns: {head}")
    ok(pg.locator("#fa-body .val, #fa-body .valbar").count() == 0, "No AM value column or value bar on Waiver Wire")
    projs = [t.strip().split("\n")[0] for t in pg.locator("#fa-body td.fa-proj").all_inner_texts()]
    ok(all(re.fullmatch(r"\d+\.\d|—|Bye|Out|DNP", t) for t in projs) and "0.0" not in projs[:5] and sum(bool(re.fullmatch(r"\d+\.\d", t)) for t in projs) > 10, f"Weekly projections shown (— when missing, never a fake zero): {projs[:8]}")
    ranks = [int(t) for t in pg.locator("#fa-body td.rk").all_inner_texts() if t.strip().isdigit()]
    ok(ranks == sorted(ranks), "Sorted by AM rank by default")
    fw = pg.evaluate("() => document.getElementById('fa-wrap').getBoundingClientRect().width")
    ok(fw <= 1180, f"Waiver table stays compact on desktop ({fw:.0f}px)")
    for opt in ["proj", "form", "ppg", "matchup", "posrank"]:
        pg.evaluate(f"() => {{ const s = document.getElementById('fa-sort'); s.value = '{opt}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }}"); pg.wait_for_timeout(250)
        ok(pg.locator("#fa-body tr.player").count() == n_fa, f"Sort by {opt}")
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'proj'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(250)
    pv = [float(t.split("\n")[0]) for t in pg.locator("#fa-body td.fa-proj").all_inner_texts() if re.fullmatch(r"\d+\.\d", t.strip().split("\n")[0])]
    ok(pv == sorted(pv, reverse=True), "Projection sort is highest first")
    # a player whose team already played this week (Thursday) shows Final + his points, never Bye
    import json as _j
    stats = _j.load(open(os.path.join(ROOT, "data/stats/2026.json")))
    played = sorted(t for t, rows in stats["schedule"].items() if any(r[0] == stats["through_week"] and r[4] is not None for r in rows))
    early = next((r for r in pg.locator("#fa-body tr.player").all() if r.locator(".pl-head").inner_text().split()[-1] in played), None)
    if early is None:
        print("   (no available player from a team that already played this week; skipped)")
    else:
        cell, mx = early.locator("td.fa-proj").inner_text().upper(), early.locator("td.fa-wk").inner_text().upper()
        ok("FINAL" in cell and "BYE" not in cell and "FINAL" in mx and "BYE" not in mx, f"Already played this week: Final, not Bye ({early.locator('.pl-name').inner_text()}: {' '.join(cell.split())} | {' '.join(mx.split())})")
        early.locator(".pl-name").click(); pg.wait_for_timeout(1500)
        tw = pg.locator(".pm-right .tw-card").inner_text().upper()
        ok("FINAL" in tw and "BYE" not in tw, f"Player modal This week shows the played game as Final: {' '.join(tw.split())[:80]}")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'rank'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(250)
    pg.locator("#fa-fitsort").check(force=True); pg.wait_for_timeout(300)
    ranks2 = [int(t) for t in pg.locator("#fa-body td.rk").all_inner_texts() if t.strip().isdigit()]
    ok(sorted(ranks2) == sorted(ranks) and ranks2 != ranks and abs(ranks2.index(ranks[0])) <= 3, "My team fit nudges starters up without reshuffling the list")
    pg.locator("#fa-fitsort").uncheck(force=True); pg.wait_for_timeout(300)
    fits = pg.locator(".fa-fit-t").all_inner_texts()
    ok(not any(t.startswith("Your ") for t in fits) and any(t.startswith("Would be ") or t in ("Bench depth",) or t.startswith("Starts at") or t.endswith("upgrade") for t in fits), f"Fit reads 'Would be WR5' / Starts at / Bench depth: {sorted(set(fits))[:6]}")
    ok("4.2k adds" in pg.inner_text("#fa-body"), "Sleeper's trending adds (24h) show under the availability line")
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'trend'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    ok(name_of[TRENDING] in pg.locator("#fa-body tr.player").first.inner_text(), "Sort by trending adds puts the most-added player first")
    pg.locator("#fa-body tr.player").first.locator("td.fa-num").first.click(); pg.wait_for_timeout(600)
    ok(pg.locator("#player-modal[open]").count() == 1 and name_of[TRENDING] in pg.inner_text("#player-modal"), "Clicking anywhere on a row opens the player page")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'rank'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(250)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_waivers.png")

    # switch league: every League tab follows
    pg.evaluate("() => { const b = document.querySelector('#league-menu [data-league=\"L2\"]') || (() => { const x = document.createElement('button'); x.dataset.league = 'L2'; document.getElementById('league-menu').append(x); return x; })(); b.click(); }")
    pg.wait_for_timeout(2000)
    ok("beta league" in pg.inner_text(".lg-eyebrow").lower(), "Switching leagues updates the League hub without a reload")
    pg.click("[data-lsub=power]"); pg.wait_for_timeout(400)
    ok(pg.locator(".pr-item").count() == 10, "Power Rankings now show the other league's 10 teams")
    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(1500)
    ok("Beta League Team" in pg.inner_text("#league-body"), "Transactions now come from the other league")
    pg.reload(); pg.wait_for_timeout(2000)
    ok(json.loads(pg.evaluate("() => localStorage.getItem('spm_sleeper')"))["activeId"] == "L2", "The selected league persists across refreshes")
    after = pg.evaluate("() => SPM.rankingSnapshot ? JSON.stringify(SPM.rankingSnapshot()) : ''")
    ok(after == base_board, "Base AM Board unchanged by any league data")
    # live matchups: the browser clock at Sunday 2:30 PM ET of week 4 (1:00 PM games in progress)
    saved = pg.evaluate("() => localStorage.getItem('spm_sleeper')")
    pg2 = br.new_page(viewport={"width": 1440, "height": 1000})
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.clock.install(time="2026-10-04T18:30:00Z")
    pg2.route("https://api.sleeper.app/**", sleeper)
    pg2.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.abort())
    pg2.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.setItem('spm_sleeper', {json.dumps(saved)}); }}")
    pg2.goto(f"http://127.0.0.1:{port}/#league"); pg2.wait_for_timeout(2500)
    pg2.evaluate("() => { const x = document.createElement('button'); x.dataset.league = 'L1'; document.getElementById('league-menu').append(x); x.click(); }"); pg2.wait_for_timeout(2000)
    pg2.click("#tab-league"); pg2.wait_for_timeout(300); pg2.click("[data-lsub=matchups]"); pg2.wait_for_timeout(1800)
    ok(pg2.locator(".mx-card.live").count() >= 1 and pg2.locator(".mx-state.live").count() >= 1, f"Sunday afternoon: matchups are live ({pg2.locator('.mx-card.live').count()})")
    lp = pg2.locator(".mx-card.live .mx-proj").first.inner_text().upper()
    ok(lp.strip().startswith("LIVE PROJ") and "approximate" not in lp.lower(), f"During games the total still reads Live proj: {lp}")
    tip = pg2.locator(".mx-card.live .mx-proj").first.get_attribute("title") or ""
    ok("estimate" in tip.lower(), "Its tooltip explains it's an estimate")
    ok(re.search(r"\d+ played · \d+ active · \d+ remaining", pg2.inner_text(".mx-card.live .mx-left-row")) is not None, "Players played / active / remaining")
    pg2.locator(".mx-card.live .mx-show").first.click(); pg2.wait_for_timeout(400)
    ok(pg2.locator(".mx-card.open .mx-pts.live").count() >= 1 and pg2.locator(".mx-card.open .mx-livetag").count() >= 1, "Live starters show LIVE points with their projection")
    if SHOTS: pg2.screenshot(path=f"{SHOTS}/hub_matchups_live.png", full_page=True)
    # phones (Steven, Oct 4): nothing in a matchup card, incl. the open lineups' points and projections, is cut off
    for w in (360, 320):
        pg2.set_viewport_size({"width": w, "height": 800}); pg2.wait_for_timeout(300)
        clipped = pg2.evaluate("""() => [...document.querySelectorAll('.mx-card *')].filter(el => { const r = el.getBoundingClientRect(), c = el.closest('.mx-card').getBoundingClientRect();
            return r.width && (r.right > c.right + 1 || r.left < c.left - 1); }).map(el => el.className).slice(0, 5)""")
        ok(not clipped and pg2.locator(".mx-card.open .mx-pts").first.is_visible(), f"Matchups at {w}px: nothing clipped ({clipped})")
    if SHOTS: pg2.screenshot(path=f"{SHOTS}/hub_matchups_phone.png", full_page=True)
    # Depth Chart tab in the player modal (synthetic depth chart file: no network)
    qb = next(r for r in rows if r["pos"] == "QB" and r["sleeper_id"] and r["team"])
    wr = next(r for r in rows if r["pos"] == "WR" and r["sleeper_id"] and r["team"] == qb["team"]) if any(r["pos"] == "WR" and r["team"] == qb["team"] and r["sleeper_id"] for r in rows) else None
    chart = {"QB": [["900001", "Backup Starter", "QB", ""], [qb["sleeper_id"], qb["player"], "QB", "Questionable"]], "RB": [["900002", "Some Back", "RB", ""]],
             "LWR": [[wr["sleeper_id"], wr["player"], "WR", ""]] if wr else [["900003", "Some Receiver", "WR", ""]], "TE": [["900004", "Some End", "TE", "Out"]],
             "LT": [["900005", "Big Tackle", "OT", ""]], "LCB": [["900006", "Corner One", "CB", ""]], "K": [["900007", "Leg Man", "K", ""]]}
    dc = {"updated": "2026-10-04T12:00Z", "source": "Sleeper", "teams": {qb["team"]: chart}}
    pg.route("**/data/depth_charts.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(dc)))
    pg.click("#tab-rankings"); pg.wait_for_timeout(400)
    pg.evaluate(f"() => document.querySelector('[data-player=\"{qb['sleeper_id']}\"]').click()"); pg.wait_for_timeout(800)
    tabs_pm = [t.strip() for t in pg.locator("#player-modal [data-pp-tab], #player-modal .pp-tabs button").all_inner_texts()]
    ok("Depth Chart" in tabs_pm and tabs_pm.index("Depth Chart") == tabs_pm.index("Practice Report") - 1, f"Player modal has a Depth Chart tab before Practice Report: {tabs_pm}")
    pg.locator("#player-modal button", has_text="Depth Chart").first.click(); pg.wait_for_timeout(800)
    body = pg.inner_text("#player-modal")
    ok("2nd on the depth chart" in body and "Behind Backup Starter" in body, "Depth chart: his slot and who's ahead of him")
    ok(pg.locator("#player-modal .dc-me").count() == 1 and "Big Tackle" not in body and "Corner One" not in body, "Offense by default with him highlighted; line and defense hidden")
    ok(pg.locator("#player-modal .dc-row-me .st-badge").count() == 1, "Injury status badge from Sleeper")
    pg.click("[data-dc-full]"); pg.wait_for_timeout(300)
    body = pg.inner_text("#player-modal")
    ok("Big Tackle" in body and "Corner One" in body and "Leg Man" in body, "Full depth chart adds the line, defense and special teams")
    ok("Depth chart from Sleeper" in body, "Source line names Sleeper")
    if SHOTS: pg.locator("#player-modal").screenshot(path=f"{SHOTS}/depth_chart.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    # Player modal fantasy points follow the selected league's scoring (Alan, Oct 5): one raw stat line, scored per league
    stats26 = json.load(open(os.path.join(ROOT, "data", "stats", "2026.json")))
    te_sid = next((r["sleeper_id"] for r in rows if r["pos"] == "TE" and r["sleeper_id"] and stats26["players"].get(r["sleeper_id"], {}).get("g")), None)
    if te_sid:
        g0 = dict(zip(stats26["cols"], stats26["players"][te_sid]["g"][0]))
        def expect(sc): return round(sum(float(sc.get(k, 0)) * float(g0.get(k) or 0) for k in sc if k in g0) + float(sc.get("bonus_rec_te", 0)) * g0["rec"], 1)
        def switch(lid):
            pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }"); pg.wait_for_timeout(400)
            pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
            pg.locator(f"#sd-leagues [data-league='{lid}']").click(); pg.wait_for_timeout(1500)
        def log_pts():
            pg.click("#tab-rankings"); pg.wait_for_timeout(400)
            pg.evaluate(f"() => document.querySelector('[data-player=\"{te_sid}\"]').click()"); pg.wait_for_timeout(900)
            label = pg.inner_text("#player-modal .pm-scoring")
            pg.locator("#player-modal button", has_text="Game Log").first.click(); pg.wait_for_timeout(500)
            pts = pg.evaluate(f"""() => {{ const r = [...document.querySelectorAll('#player-modal tbody tr')].find(tr => tr.cells[0] && tr.cells[0].textContent.trim() === '{g0["w"]}');
                return r ? Number(r.querySelector('.gl-pts').textContent) : null; }}""")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
            return pts, label
        switch("L1"); p1, lab1 = log_pts()
        switch("L2"); p2, lab2 = log_pts()
        e1, e2 = expect(L1["league"]["scoring_settings"]), expect(L2["league"]["scoring_settings"])
        ok(p1 == e1 and p2 == e2 and p1 != p2, f"Game Log points follow each league's scoring: {name_of[te_sid]} Wk {g0['w']} {p1} (Alpha, expected {e1}) vs {p2} (Beta, expected {e2})")
        ok("Alpha League scoring" in lab1 and "TE Premium +" in lab1 and "Beta League scoring" in lab2 and "Half PPR" in lab2 and "TE Premium" not in lab2, f"Player modal names the scoring: '{lab1}' / '{lab2}'")
        switch("L1")
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All league hub checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
