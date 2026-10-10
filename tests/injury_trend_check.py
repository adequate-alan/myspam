"""Injury vs performance trend (Alan, Oct 10): injury and availability are judged separately from performance trends.
Every trend label the site shows (Recent form's Hot / Steady / Cooling on My Team and the Waiver Wire, the drawer's
Season trend Up / Steady / Down, the weekly chart's poor-week tone, Compare's "recent scoring" lead) is checked on a
fully synthetic league and synthetic stats (nothing real: made-up game lines on real board players so they render):

  - games missed because of injury (OUT weeks) never count as declining performance;
  - games cut short by injury never trigger Cooling / Down on their own;
  - a player trending upward before he got hurt is not labeled as declining;
  - Questionable / Out / IR / returning-from-injury statuses change no trend label by themselves;
  - a player who is genuinely declining AND injured still reads as declining (completed games support it);
  - too little healthy-game data gives a neutral / no-trend read, never a misleading label.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/injury_trend_check.py
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
board = [r for r in rows if r["sleeper_id"] and r["team"]]
sids = [r["sleeper_id"] for r in board]
COLS = ["w", "tm", "opp", "pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int", "pass_2pt", "pass_sack", "pass_fd", "rush_att", "rush_yd", "rush_td", "rush_2pt", "rush_fd",
        "rec_tgt", "rec", "rec_yd", "rec_td", "rec_2pt", "rec_fd", "fum_lost", "tgt_share", "snap", "rz_tgt", "rz_rush", "gl_rush", "air_yd", "air_share", "scr"]
SCHED_COLS = ["w", "opp", "home", "date", "pf", "pa", "time", "spread", "total", "roof", "stadium"]
TEAMS = sorted({r["team"] for r in board})
PLAYED = 5            # weeks 1-5 final, week 6 upcoming
BYE_TEAM_WEEK = 3     # the first scenario player's team had its bye in week 3

# Scenario players: the first WRs on the board whose teams differ (one per NFL team, so each team's schedule is simple)
wrs, seen = [], set()
for r in board:
    if r["pos"] == "WR" and r["team"] not in seen:
        wrs.append(r); seen.add(r["team"])
S = {k: wrs[i] for i, k in enumerate(["up_hurt", "cut_short", "decline_hurt", "no_healthy", "returning", "status_only", "one_game", "decline", "steady", "control"])}
NAME = {k: r["player"] for k, r in S.items()}

def line(w, tm, pts=None, short=False):
    """A receiving line worth `pts` in Full PPR (1 per catch + 0.1 per yard); None = didn't play (no line)."""
    g = {c: 0 for c in COLS}; g.update({"w": w, "tm": tm, "opp": "ZZZ"})
    rec = 1 if short else 5
    g.update({"rec_tgt": rec + 2, "rec": rec, "rec_yd": round((pts - rec) * 10), "snap": 0.2 if short else 0.9, "tgt_share": 0.2, "air_yd": 0, "air_share": 0.0})
    return [g[c] for c in COLS]

# weekly points per scenario (None = out, "s" suffix = injury-shortened); 2025 PPG for the prior-season baseline
SCEN = {
    "up_hurt":      ([10, 14, 18, 22, None], None),        # improving, then hurt: OUT in week 5
    "cut_short":    ([20, 20, 20, 20, (3, "s")], None),    # steady, left week 5 early
    "decline_hurt": ([24, 22, 14, 8, (6, "s")], None),     # genuinely declining, then hurt (Questionable this week)
    "no_healthy":   ([(2, "s"), None, None, None, None], 15.0),   # hurt in week 1, out since; 10 games at 15 PPG last season
    "returning":    ([15, 15, None, None, 18], 16.0),      # back from two weeks out
    "status_only":  ([16, 16, 16, 16, 16], None),          # steady, listed Out this week and on IR
    "one_game":     ([20, (4, "s"), None, None, None], 20.0),   # one healthy game, then hurt
    "decline":      ([24, 20, 14, 10, 8], None),           # genuine decline, fully healthy (control)
    "steady":       ([18, 18, 18, 18, 18], None),          # Compare partner
    "control":      ([12, 12, 12, 12, 12], None),
}
def season(year, pts_of):
    players, schedule, short = {}, {}, {}
    for tm in TEAMS:
        schedule[tm] = []
        for w in range(1, 7):
            if year == 2026 and tm == S["up_hurt"]["team"] and w == BYE_TEAM_WEEK: continue
            done = w <= PLAYED
            schedule[tm].append([w, "ZZZ", 1, f"{year}-09-{6 + 7 * w:02d}" if w <= 3 else f"{year}-10-{7 * w - 17:02d}", 24 if done else None, 20 if done else None, "13:00", -3.0, 45.5, "outdoors", "Stadium"])
    for k, r in S.items():
        pts = pts_of(k)
        if pts is None: continue
        g = []
        for w, v in enumerate(pts, 1):
            if v is None: continue
            p, s = (v if isinstance(v, tuple) else (v, ""))
            g.append(line(w, r["team"], p, bool(s)))
            if s: short.setdefault(r["sleeper_id"], []).append([w, 0.2, 0.9, "Ankle", 20.0])
        players[r["sleeper_id"]] = {"n": r["player"], "p": r["pos"], "g": g}
    inj = {"week": 6, "cols": ["name", "pos", "sid", "status", "practice", "injury", "wed", "thu", "fri"], "teams": {}}
    for k, st in (("decline_hurt", "Questionable"), ("status_only", "Out"), ("no_healthy", "Out"), ("one_game", "Out")):
        r = S[k]; inj["teams"].setdefault(r["team"], []).append([r["player"], "WR", r["sleeper_id"], st, "DNP", "Ankle", "DNP", "DNP", "DNP"])
    return {"season": year, "through_week": PLAYED if year == 2026 else 18, "updated": f"{year}-10-15T12:00Z", "cols": COLS, "players": players,
            "schedule_cols": SCHED_COLS, "schedule": schedule, "defense": {}, "injuries": inj if year == 2026 else None, "short": short}
STATS = {2026: season(2026, lambda k: SCEN[k][0]),
         2025: season(2025, lambda k: [SCEN[k][1]] * 10 if SCEN[k][1] else None),
         2024: season(2024, lambda k: None)}
# the prior season needs its own schedule weeks scored (ten games) so last season's PPG counts as the baseline
for tm, rows_ in STATS[2025]["schedule"].items():
    rows_[:] = [[w, "ZZZ", 1, f"2025-10-{w:02d}", 24, 20, "13:00", -3.0, 45.5, "outdoors", "Stadium"] for w in range(1, 11)]

# ---------- synthetic Sleeper league: 12 teams, mine first; cut_short is a free agent ----------
mine = [S[k]["sleeper_id"] for k in S if k != "cut_short"]
pool = [x for x in sids if x not in {r["sleeper_id"] for r in S.values()}]
POS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6 + ["IR"]
rosters = []
for i in range(12):
    pl = (mine if i == 0 else []) + pool[i::12][:14 - (len(mine) if i == 0 else 0)]
    rosters.append({"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": pl, "starters": pl[:9], "reserve": [], "taxi": [],
                    "settings": {"wins": 3, "losses": 2, "ties": 0, "fpts": 500 + i, "fpts_against": 480}, "metadata": {}})
rosters[0]["reserve"] = [S["status_only"]["sleeper_id"]]
rosters[0]["starters"] = [x for x in rosters[0]["players"] if x != S["status_only"]["sleeper_id"]][:9]
LEAGUE = {"league_id": "L9", "name": "Trend League", "season": "2026", "status": "in_season", "total_rosters": 12, "roster_positions": POS,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2, "bonus_rec_te": 0.5},
          "settings": {"num_teams": 12, "type": 0, "waiver_type": 2, "waiver_clear_days": 2, "waiver_budget": 100, "leg": 6, "playoff_week_start": 15}}
USERS = [{"user_id": f"u{i+1}", "display_name": f"manager{i+1}", "metadata": {"team_name": f"Team {i+1}"}} for i in range(12)]

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    body = []
    if path == "/state/nfl": body = {"season": "2026", "league_season": "2026", "week": 6, "display_week": 6, "season_type": "regular"}
    elif path.startswith("/user/") and "/leagues/" in path: body = [LEAGUE]
    elif path.startswith("/user/"): body = {"user_id": "u1", "username": "tester", "display_name": "tester"}
    elif path == "/league/L9": body = LEAGUE
    elif path == "/league/L9/users": body = USERS
    elif path == "/league/L9/rosters": body = rosters
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.clock.install(time="2026-10-15T16:00:00Z")   # Thursday of week 6, before any game
    for y, d in STATS.items():
        pg.route(f"**/data/stats/{y}.json", (lambda d: (lambda r, *_: r.fulfill(status=200, content_type="application/json", body=json.dumps(d))))(d))
    pg.route(re.compile(r".*/data/(injury_overrides|projections|depth_charts|market/.*)\.json$"), lambda r, *_: r.fulfill(status=404, body=""))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|use\.typekit\.net)/.*"), lambda r, *_: r.abort())
    pg.add_init_script("if (!sessionStorage.getItem('t')) { sessionStorage.setItem('t', '1'); localStorage.clear(); }")
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L9']").click(); pg.wait_for_timeout(2000)

    # ---------- Recent form on My Team ----------
    pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    def form_of(k, scope="#panel-myteam"):
        row = pg.locator(f"{scope} tr:has([data-player='{S[k]['sleeper_id']}'])").first
        if not row.count(): return None
        rf = row.locator(".rf").first
        if not rf.count(): return {"text": row.inner_text(), "trend": "", "tags": []}
        t = rf.locator(".rf-trend")
        return {"text": re.sub(r"\s+", " ", rf.inner_text()), "trend": re.sub(r"^[▲▼→]\s*", "", t.inner_text()) if t.count() else "",
                "tags": [x.inner_text() for x in rf.locator(".rf-tag").all()], "stars": rf.locator(".inj-star").count()}
    f = form_of("up_hurt")
    ok(f and f["trend"] == "Hot" and f["tags"] == ["OUT"], f"Improving then hurt (10 → 22, OUT in week 5): Recent form reads Hot, the missed game is OUT, not a decline: {f}")
    f = form_of("cut_short")
    ok(f is None, "cut_short is a free agent, not on my roster")
    f = form_of("decline_hurt")
    ok(f and f["trend"] == "Cooling" and f["stars"] == 1, f"Declining AND hurt (24 → 8, left week 5 early, Questionable): still Cooling, the injury doesn't hide it: {f}")
    f = form_of("no_healthy")
    ok(f and f["trend"] == "" and f["tags"] == ["OUT", "OUT", "OUT"], f"No healthy game (hurt in week 1, out since): no trend, three OUT weeks: {f}")
    f = form_of("returning")
    ok(f and f["trend"] == "" and f["tags"] == ["OUT", "OUT"], f"Returning from injury (one game back): no trend yet, not Cooling: {f}")
    f = form_of("status_only")
    ok(f and f["trend"] == "Steady", f"Steady player listed Out this week and on IR: Steady, the status changes nothing: {f}")
    f = form_of("one_game")
    ok(f and f["trend"] == "", f"One healthy game then hurt: no trend: {f}")
    f = form_of("decline")
    ok(f and f["trend"] == "Cooling" and f["stars"] == 0, f"Control, healthy decline (24 → 8): Cooling: {f}")
    f = form_of("steady")
    ok(f and f["trend"] == "Steady", f"Control, steady 18s: Steady: {f}")

    # ---------- Recent form on the Waiver Wire (free agent cut short last week) ----------
    pg.click("#tab-league"); pg.wait_for_timeout(1200)
    pg.click("[data-lsub=waivers]"); pg.wait_for_timeout(1500)
    f = form_of("cut_short", "#fa-wrap")
    ok(f and f["trend"] == "Steady" and f["stars"] == 1, f"Waiver Wire, steady player who left week 5 early (20, 20, 3*): Steady, not Cooling: {f}")

    # ---------- the drawer's Season trend and weekly chart ----------
    def open_player(k):
        pg.click("#tab-rankings"); pg.wait_for_timeout(400)
        pg.evaluate(f"document.querySelector('#rank-body [data-player=\"{S[k]['sleeper_id']}\"]').click()"); pg.wait_for_timeout(1500)
    def season_trend():
        c = pg.locator("#player-modal .ov-cell:has(.ov-label:text-is('Season trend'))").first
        if not c.count(): return None
        return {"v": c.locator(".ov-val").inner_text().strip(), "sub": c.locator(".ov-sub").inner_text().strip() if c.locator(".ov-sub").count() else ""}
    open_player("up_hurt"); t = season_trend()
    ok(t and t["v"] == "Up", f"Drawer, improving then hurt: Season trend Up: {t}")
    open_player("cut_short"); t = season_trend()
    ok(t and t["v"] == "Steady", f"Drawer, steady player who left week 5 early: Season trend Steady: {t}")
    ok(pg.locator("#player-modal .wk-chart .wk-pt.poor").count() == 0, "Weekly chart: the injury-shortened 3-point game is not styled as a poor week")
    open_player("decline_hurt"); t = season_trend()
    ok(t and t["v"] == "Down", f"Drawer, declining AND hurt: Season trend Down (the completed games support it): {t}")
    open_player("no_healthy"); t = season_trend()
    ok(t and t["v"] not in ("Down", "Up"), f"Drawer, no healthy game this season (2 points in an injury exit, 15 PPG last season): no Up / Down label: {t}")
    open_player("one_game"); t = season_trend()
    ok(t and t["v"] != "Down", f"Drawer, one healthy 20-point game then hurt (20 PPG last season): not Down: {t}")
    open_player("returning"); t = season_trend()
    ok(t and t["v"] != "Down", f"Drawer, returning from injury (15, 15, out, out, 18 vs 16 last season): not Down: {t}")
    open_player("status_only"); t = season_trend()
    ok(t and t["v"] == "Steady", f"Drawer, steady player listed Out: Steady: {t}")
    open_player("decline"); t = season_trend()
    ok(t and t["v"] == "Down", f"Drawer, control healthy decline: Down: {t}")

    # ---------- Compare: an injury-shortened game must not hand the other player the 'recent scoring' edge ----------
    open_player("cut_short")
    pg.locator("#player-modal .pp-tabs button", has_text=re.compile(r"^Compare$")).first.click(); pg.wait_for_timeout(600)
    pg.fill("#pm-pick", NAME["steady"]); pg.wait_for_timeout(500)
    pg.locator(f"#player-modal [data-pm-pick='{S['steady']['sleeper_id']}']").first.click(); pg.wait_for_timeout(1200)
    summ = pg.locator("#player-modal .cmp-sum").inner_text() if pg.locator("#player-modal .cmp-sum").count() else ""
    last = NAME["steady"].split()[-1]   # the summary uses compact names
    claims_b = any(last in para and "recent scoring" in para for para in summ.split("\n\n"))
    ok(not claims_b, f"Compare (20, 20, 20, 20, 3* vs steady 18s): the summary doesn't give the steady player the 'recent scoring' edge from an injury exit: {summ!r}")

    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
