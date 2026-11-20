"""Recent PPG check: the Rankings board's "Recent PPG" sort and its game-count selector (Alan, Nov 18).

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/recent_ppg_check.py

Recent PPG replaced the Last 3 / Last 5 PPG sorts: one Sort option plus a compact "LAST [- 5 games +]" control, any
count from 1 to 18 (default 5). It averages a player's last N games actually played, counted back from the selected
week: byes and weeks he missed never use up a game, a genuine zero-point game does, and a past week's view never reads
later games.

Fixture (nothing real about it is asserted): the live stats file, served with Weeks 1-11 marked as played and five
board WRs given synthetic game logs in a synthetic Full PPR league (points = receptions):
  EVERY   plays Weeks 1-11, scoring the week's number
  MISSED  plays Weeks 1-4, 6, 9, 10, 11 (bye in Week 5, never entered the game in Weeks 7 and 8)
  ZERO    plays Weeks 7-11: 10 points each, then a real 0-point game in Week 11 (snaps, no stats)
  TWO     plays Weeks 10 and 11 only
  NONE    no game
Every other player keeps his real log, and every row on screen is recomputed in Python from the served file.
Checks: the menu and the control, game counts 1 / 2 / 5 / 7 / 10 / 18 through the buttons, the keyboard and typed
input, invalid input, players with fewer games (sample size shown), byes and missed weeks, the zero game, the
minimum-games filter, historical weeks (Week 8 and Week 11, no later game ever read), a week that hasn't been played,
the count surviving position, board, page and reload changes, browsers that saved Last 3 PPG, AM Rank restoring the
board exactly, phones, both themes, no page errors. SHOTS=dir saves screenshots (desktop and phone, light and dark).
"""
import copy, csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
season = int(re.search(r"const STATS_SEASONS = \[(\d+)", src).group(1))
board = {r["sleeper_id"]: r for r in rows if r["sleeper_id"] and r["pos"] in ("QB", "RB", "WR", "TE")}
name_sid = {r["player"]: sid for sid, r in board.items()}
STAT_KEYS = ["pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int", "pass_2pt", "pass_sack", "pass_fd", "rush_att", "rush_yd",
             "rush_td", "rush_2pt", "rush_fd", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_2pt", "rec_fd", "fum_lost"]
THRU = 11

def fixture():
    d = json.load(open(os.path.join(ROOT, f"data/stats/{season}.json")))
    ix = {c: i for i, c in enumerate(d["cols"])}
    for rws in d["schedule"].values():          # Weeks 1-11 played, Week 12 on next
        for r in rws:
            if r[0] <= THRU and r[4] is None: r[4], r[5] = 20, 17
            if r[0] > THRU: r[4] = r[5] = None
    for pl in d["players"].values(): pl["g"] = [g for g in pl["g"] if g[0] <= THRU]
    d["through_week"] = THRU
    def line(w, tm, pts=None, snaps=40):
        a = [0] * len(d["cols"]); a[ix["w"]], a[ix["tm"]], a[ix["opp"]] = w, tm, "OPP"
        for k in ("tgt_share", "air_share"): a[ix[k]] = 0.0
        if pts is None: a[ix["snap"]], a[ix["snaps"]] = 0, 0        # on the game log, never entered the game
        else: a[ix["rec"]] = a[ix["rec_tgt"]] = pts; a[ix["snap"]], a[ix["snaps"]] = 0.6, snaps
        return a
    wrs = [sid for sid, r in board.items() if r["pos"] == "WR" and sid in d["players"] and r["team"] not in ("FA", "")][20:25]
    who = dict(zip(["EVERY", "MISSED", "ZERO", "TWO", "NONE"], wrs))
    tm = {k: board[s]["team"] for k, s in who.items()}
    logs = {"EVERY": [line(w, tm["EVERY"], w) for w in range(1, 12)],
            "MISSED": [line(w, tm["MISSED"], w) for w in (1, 2, 3, 4, 6)] + [line(7, tm["MISSED"]), line(8, tm["MISSED"])] + [line(w, tm["MISSED"], w) for w in (9, 10, 11)],
            "ZERO": [line(w, tm["ZERO"], 10) for w in (7, 8, 9, 10)] + [line(11, tm["ZERO"], 0)],
            "TWO": [line(10, tm["TWO"], 12), line(11, tm["TWO"], 6)], "NONE": []}
    for k, s in who.items():
        d["players"][s]["g"] = logs[k]; d["players"][s]["p"] = "WR"
        (d.get("short") or {}).pop(s, None)
    return d, who
S, WHO = fixture()
IX = {c: i for i, c in enumerate(S["cols"])}
NAME = {k: board[s]["player"] for k, s in WHO.items()}

def played(a): return any(a[IX[k]] for k in STAT_KEYS) or (a[IX["snap"]] or 0) > 0
SC = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "pass_2pt": 2, "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
      "rec": 1, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2, "fum_lost": -2}
def game_pts(a): return round(sum(float(SC.get(k, 0)) * (a[IX[k]] or 0) for k in STAT_KEYS) * 100) / 100

def expected(n, thru=None):
    """name -> (Recent PPG, games played through the week, games in the sample, the sample's weeks)"""
    out = {}
    for sid, r in board.items():
        pl = S["players"].get(sid)
        if not pl: continue
        games = sorted((a[0], game_pts(a)) for a in pl["g"] if played(a) and (thru is None or a[0] <= thru))
        if not games: continue
        sample = games[-n:]
        out[r["player"]] = (sum(g[1] for g in sample) / len(sample), len(games), len(sample), [g[0] for g in sample])
    return out

sids = list(board)[:144]
LEAGUE = {"league_id": "L1", "name": "Recent League", "season": str(season), "status": "in_season", "total_rosters": 12,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": SC, "settings": {"num_teams": 12, "type": 0}}
rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": sids[i::12], "starters": [], "reserve": [], "taxi": [],
            "settings": {"wins": 5, "losses": 5, "ties": 0, "fpts": 900}} for i in range(12)]
users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "team_name": f"Team {i+1}", "avatar": ""} for i in range(12)]
SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": str(season),
      "leagues": [{"id": "L1", "name": "Recent League", "season": str(season), "status": "in_season", "format": ""}],
      "activeId": "L1", "data": {"L1": {"league": LEAGUE, "users": users, "rosters": rosters}}, "view": "league"}

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    m = re.match(r"/league/L1(/users|/rosters)?$", path)
    body = [] if not m else LEAGUE if not m.group(1) else users if m.group(1) == "/users" else rosters
    if path == "/state/nfl": body = {"season": str(season), "week": THRU + 1, "season_type": "regular"}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

READ = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({
  name: tr.querySelector('.pl-name').textContent.trim(), rank: Number(tr.querySelector('td.rk').textContent.replace(/[^0-9]/g, '')),
  pos: tr.querySelector('.pos-col .pos').className.split(' ').pop(),
  v: tr.querySelector('.pnum') ? Number(tr.querySelector('.pnum').firstChild.textContent) : null,
  sub: tr.querySelector('.psub') ? tr.querySelector('.psub').textContent.trim() : '', thin: !!tr.querySelector('.psub.thin'),
  tip: tr.querySelector('.psub') ? tr.querySelector('.psub').title : '',
  bar: tr.querySelector('.prodbar .fill') ? parseFloat(tr.querySelector('.prodbar .fill').style.width) : null,
  val: ((tr.querySelector('.val .num, .val .num-btn, .val .num-2') || {}).textContent || '').trim() }))"""

def compare(label, got, exp, n, min_gp=0):
    """every row: value, sample label and (full samples) the weeks used; order by value; nobody missing or extra"""
    want = {k: e for k, e in exp.items() if e[1] >= min_gp}
    bad, lab, wk = [], [], []
    for r in got:
        e = want.get(r["name"])
        if not e or abs(r["v"] - e[0]) > 0.051: bad.append((r["name"], r["v"], e and round(e[0], 2))); continue
        sub = f"last {n}" if e[2] == n else f"{e[2]} of {n} games"
        if r["sub"] != sub or r["thin"] != (e[2] < n): lab.append((r["name"], r["sub"], sub))
        if e[2] == n and [int(x) for x in re.findall(r"\d+", r["tip"].split(":")[-1])] != e[3]: wk.append((r["name"], r["tip"], e[3]))
    order = [i for i in range(1, len(got)) if want.get(got[i]["name"], (0,))[0] > want.get(got[i - 1]["name"], (0,))[0] + 1e-9]
    top = max((r["v"] for r in got), default=0)
    bars = [r["name"] for r in got if top > 0 and abs(r["bar"] - max(0, r["v"]) / top * 100) > 0.6]
    ok(not bad and not lab and not wk and not order and not bars and len(got) == len(want) and [r["rank"] for r in got] == list(range(1, len(got) + 1)),
       f"{label}: {len(got)} rows match the game logs (value {bad[:2]}, sample label {lab[:2]}, weeks {wk[:2]}, order {order[:2]}, bars {bars[:2]}, expected {len(want)})")

SHOTS = os.environ.get("SHOTS")
port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    def page(store=None, w=1440, h=1000, theme="dark", league=True, scale=1):
        pg = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
        pg.route(re.compile(rf".*/data/stats/{season}\.json.*"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(S)))
        init = f"localStorage.clear(); localStorage.setItem('spm_theme', '{theme}');"
        if league: init += f"localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))});"
        for k, v in (store or {}).items(): init += f"localStorage.setItem('{k}', {json.dumps(v if isinstance(v, str) else json.dumps(v))});"
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        return pg
    def sel(pg, id_, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('{id_}'); s.value = '{v}'; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(350)
    def typed(pg, text):      # type a count the way a person does: click the box (selects it), type
        pg.click("#rk-n"); pg.keyboard.type(text); pg.wait_for_timeout(350)
    def count(pg): return pg.input_value("#rk-n")
    def head(pg): return pg.inner_text("#rk-head-row").upper()
    def row(got, key): return next((r for r in got if r["name"] == NAME[key]), None)

    # 1. the menu and the control
    pg = page()
    spam0, head0 = pg.evaluate(READ), pg.inner_text("#rk-head-row")
    opts = pg.evaluate("() => [...document.getElementById('rk-sort').options].map(o => [o.value, o.textContent])")
    ok(["recent", "Recent PPG"] in opts and not any(v in ("l3", "l5") or "Last" in t for v, t in opts), f"Sort menu: one Recent PPG option, no Last 3 / Last 5 ({[t for _, t in opts[:5]]})")
    ok(not pg.is_visible("#rk-n-wrap"), "AM Rank: no game-count control")
    sel(pg, "rk-sort", "ppg")
    ok(not pg.is_visible("#rk-n-wrap"), "Season PPG: no game-count control")
    sel(pg, "rk-sort", "recent"); sel(pg, "rk-min", "0")
    ok(pg.is_visible("#rk-n-wrap") and count(pg) == "5" and pg.inner_text("#rk-n-wrap").upper().split() == ["LAST", "−", "GAMES", "+"],
       f"Recent PPG: the control shows beside Sort, 5 games by default ({count(pg)!r}, {pg.inner_text('#rk-n-wrap')!r})")
    ok("LAST 5 PPG" in head(pg) and "L5 RK" in head(pg), f"Header reads Last 5 PPG / L5 Rk ({head(pg)!r})")
    box = pg.evaluate("() => { const r = document.getElementById('rk-n-wrap').getBoundingClientRect(), s = document.getElementById('rk-sort-wrap').getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), Math.round(s.height)]; }")
    ok(box[0] <= 190 and box[1] <= 36 and box[2] <= 40, f"Compact: the control is {box[0]}×{box[1]}px on the one toolbar row ({box[2]}px)")
    compare("Last 5 (default)", pg.evaluate(READ), expected(5), 5)

    # 2. different counts: +, −, arrow keys, typed
    pg.click("#rk-n-inc"); pg.click("#rk-n-inc"); pg.wait_for_timeout(350)
    ok(count(pg) == "7" and "LAST 7 PPG" in head(pg), "+ twice: 7 games, header updates at once")
    compare("Last 7 (+ button)", pg.evaluate(READ), expected(7), 7)
    typed(pg, "10"); compare("Last 10 (typed)", pg.evaluate(READ), expected(10), 10)
    ok("LAST 10 PPG" in head(pg) and "his last 10 games played" in pg.inner_text("#rank-count"), "Typed 10: header and count line say 10 games: " + pg.inner_text("#rank-count"))
    typed(pg, "2"); compare("Last 2 (typed)", pg.evaluate(READ), expected(2), 2)
    pg.click("#rk-n-dec"); pg.wait_for_timeout(350)
    compare("Last 1 (− button)", pg.evaluate(READ), expected(1), 1)
    ok(pg.is_disabled("#rk-n-dec") and not pg.is_disabled("#rk-n-inc") and pg.inner_text("#rk-n-unit") == "game", "At 1: − is disabled and the unit reads 'game'")
    typed(pg, "18"); compare("Last 18 (typed)", pg.evaluate(READ), expected(18), 18)
    ok(pg.is_disabled("#rk-n-inc") and not pg.is_disabled("#rk-n-dec"), "At 18: + is disabled")
    pg.focus("#rk-n"); pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(350)
    ok(count(pg) == "17" and "LAST 17 PPG" in head(pg), "Arrow down in the box: 17")
    # invalid input never sticks
    for text, want in (("0", "1"), ("25", "18"), ("abc", "18"), ("", "18")):
        pg.click("#rk-n")
        if text: pg.keyboard.type(text)
        else: pg.keyboard.press("Backspace")
        pg.keyboard.press("Tab"); pg.wait_for_timeout(300)
        ok(count(pg) == want and f"LAST {want} PPG" in head(pg), f"Typing {text!r} and leaving the box: stays in 1–18 ({count(pg)}: below 1 becomes 1, above 18 becomes 18, nothing typed keeps the count)")
    typed(pg, "5")

    # 3. byes, missed weeks, a real zero, fewer games
    g5 = pg.evaluate(READ); e5 = expected(5)
    r = row(g5, "MISSED")
    ok(r and abs(r["v"] - 8.0) < 0.01 and r["sub"] == "last 5" and "4, 6, 9, 10, 11" in r["tip"], f"Bye and missed weeks don't use up a game: last 5 = Weeks 4, 6, 9, 10, 11 = 8.0 ({r and (r['v'], r['tip'])})")
    r = row(g5, "ZERO")
    ok(r and abs(r["v"] - 8.0) < 0.01 and r["sub"] == "last 5", f"A real 0-point game counts: 10, 10, 10, 10, 0 = 8.0 over 5 ({r and (r['v'], r['sub'])})")
    r = row(g5, "TWO")
    ok(r and abs(r["v"] - 9.0) < 0.01 and r["sub"] == "2 of 5 games" and r["thin"] and "Only 2 games" in r["tip"], f"Fewer games than asked: averaged over the 2 he played and labelled ({r and (r['v'], r['sub'], r['tip'])})")
    ok(row(g5, "NONE") is None and "without a game" in pg.inner_text("#rank-count"), "No game: left out, never a made-up number")
    few = sum(1 for e in e5.values() if e[2] < 5)
    ok(f"{few} with fewer than 5 games" in pg.inner_text("#rank-count"), f"Count line names how many have fewer than 5 games ({few})")
    typed(pg, "1"); r = row(pg.evaluate(READ), "ZERO")
    ok(r and r["v"] == 0 and r["sub"] == "last 1", f"Last 1: the 0-point game is his most recent game (0.0), not skipped ({r and r['v']})")
    typed(pg, "8"); g8 = pg.evaluate(READ); r = row(g8, "MISSED")
    ok(r and abs(r["v"] - 5.75) < 0.051 and r["sub"] == "last 8" and "1, 2, 3, 4, 6, 9, 10, 11" in r["tip"],
       f"Last 8 with missed games: his last eight actual games (5.75), not Weeks 4–11 (8.0) ({r and (r['v'], r['tip'])})")
    r = row(g8, "EVERY")
    ok(r and abs(r["v"] - 7.5) < 0.01, f"Last 8, no missed game: Weeks 4–11 = 7.5 ({r and r['v']})")

    # 4. the minimum-games filter still counts games played
    typed(pg, "5")
    for m in (4, 2, 0):
        sel(pg, "rk-min", m); compare(f"Last 5, minimum {m}+ games", pg.evaluate(READ), e5, 5, m)
    sel(pg, "rk-min", "4")
    ok(row(pg.evaluate(READ), "TWO") is None and "under 4 games hidden" in pg.inner_text("#rank-count"), "4+ games hides the two-game player and says so")
    sel(pg, "rk-min", "0")

    # 5. historical weeks: nothing after the selected week is read
    sel(pg, "rk-week", "8")
    ok(pg.input_value("#rk-wsort") == "rppg" and pg.is_visible("#rk-n-wrap") and count(pg) == "5" and not pg.is_visible("#rk-cols-btn"),
       "Picking Week 8 from Recent PPG keeps Recent PPG (Sort menu, control, count), now through Week 8")
    w8 = pg.evaluate(READ); e8 = expected(5, 8)
    compare("Last 5 through Week 8", w8, e8, 5)
    late = [r["name"] for r in w8 if any(int(x) > 8 for x in re.findall(r"\d+", r["tip"].split(":")[-1]))] if w8 else ["?"]
    ok(not late and "through Week 8" in pg.inner_text("#rank-count"), f"Week 8: no game after Week 8 in any sample {late[:2]}: " + pg.inner_text("#rank-count"))
    r = row(w8, "MISSED")
    ok(r and abs(r["v"] - 3.2) < 0.01 and "1, 2, 3, 4, 6" in r["tip"], f"Week 8, missed Weeks 5, 7, 8: last 5 = Weeks 1, 2, 3, 4, 6 = 3.2 ({r and (r['v'], r['tip'])})")
    r = row(w8, "ZERO")
    ok(r and abs(r["v"] - 10.0) < 0.01 and r["sub"] == "2 of 5 games" and r["thin"], f"Week 8: a player with 2 games by then reads '2 of 5 games' ({r and (r['v'], r['sub'])})")
    ok(row(w8, "TWO") is None, "Week 8: a player whose first game was Week 10 isn't listed")
    typed(pg, "8"); sel(pg, "rk-week", "11")
    w11 = pg.evaluate(READ); compare("Last 8 through Week 11", w11, expected(8, 11), 8)
    r = row(w11, "MISSED")
    ok(r and abs(r["v"] - 5.75) < 0.051, f"Last 8 at Week 11: eight actual games through Week 11 = 5.75 ({r and r['v']})")
    sel(pg, "rk-week", "3"); typed(pg, "5")
    compare("Last 5 through Week 3", pg.evaluate(READ), expected(5, 3), 5)
    ok(pg.input_value("#rk-min") == "0", "Minimum games stays as chosen in a past week")
    sel(pg, "rk-week", "14")
    compare("Week 14 (not played yet)", pg.evaluate(READ), expected(5), 5)
    ok(f"stats run through Week {THRU}" in pg.inner_text("#rank-count"), "A week that hasn't been played says how far the stats run")
    sel(pg, "rk-week", "0")
    compare("Season stats · Recent PPG", pg.evaluate(READ), expected(5), 5)
    # the week view's own stat tables are untouched, and Recent PPG comes back from its Sort menu
    sel(pg, "rk-week", "8"); sel(pg, "rk-wsort", "pts")
    ok(not pg.is_visible("#rk-n-wrap") and pg.is_visible("#rk-cols-btn") and "FPTS" in head(pg), "Week 8 · Fantasy points: the week's stat table, no game-count control")
    sel(pg, "rk-wsort", "rppg")
    ok(pg.is_visible("#rk-n-wrap") and "LAST 5 PPG" in head(pg), "Week 8 · Sort → Recent PPG brings it back")
    sel(pg, "rk-week", "")
    ok(pg.input_value("#rk-sort") == "recent" and pg.is_visible("#rk-n-wrap"), "Back to Full season: still Recent PPG")
    compare("Full season again", pg.evaluate(READ), expected(5), 5)

    # 6. the count is remembered: positions, boards, pages, other sorts, reload
    typed(pg, "7")
    pg.click("#pos-chips [data-pos=RB]"); pg.wait_for_timeout(300)
    rb = pg.evaluate(READ)
    ok(count(pg) == "7" and "LAST 7 PPG" in head(pg) and rb and all(r["pos"] == "RB" for r in rb), "RB tab: still 7 games")
    e7 = expected(7)
    ok(all(abs(r["v"] - e7[r["name"]][0]) < 0.051 for r in rb) and [r["rank"] for r in rb] == list(range(1, len(rb) + 1)), "RB tab: values and ranks from the last 7")
    pg.click("#pos-chips [data-pos=ALL]"); pg.wait_for_timeout(300)
    pg.click("[data-view=base]"); pg.wait_for_timeout(400)
    boards = pg.evaluate("() => [...document.getElementById('rk-board').options].map(o => o.value)")
    for b in boards:
        sel(pg, "rk-board", b)
        ok(count(pg) == "7" and "LAST 7 PPG" in head(pg) and pg.input_value("#rk-sort") == "recent", f"Board {b}: still Recent PPG over 7 games")
    pg.click("[data-view=league]"); pg.wait_for_timeout(400)
    pg.click("#tab-trade"); pg.wait_for_timeout(400); pg.click("#tab-rankings"); pg.wait_for_timeout(400)
    ok(count(pg) == "7" and "LAST 7 PPG" in head(pg), "Another page and back: still 7 games")
    sel(pg, "rk-sort", "spam")
    ok(pg.evaluate("() => localStorage.getItem('spm_rk_recent')") == "7", "AM Rank: the count stays saved (spm_rk_recent)")
    sel(pg, "rk-sort", "recent")
    ok(count(pg) == "7", "AM Rank and back to Recent PPG: still 7 games")
    pg.reload(); pg.wait_for_selector("#rank-body tr.prod"); pg.wait_for_timeout(900)
    ok(pg.input_value("#rk-sort") == "recent" and count(pg) == "7" and "LAST 7 PPG" in head(pg), "Reload: Recent PPG over 7 games")
    compare("After a reload", pg.evaluate(READ), e7, 7)
    # 7. nothing else changed: AM Rank is the board exactly as it was
    sel(pg, "rk-sort", "spam")
    ok(pg.evaluate(READ) == spam0 and pg.inner_text("#rk-head-row") == head0, "AM Rank restores the board exactly (ranks, values, header)")
    pg.close()

    # 8. browsers that saved the old sorts
    for old, n in (("l3", "3"), ("l5", "5")):
        pg = page({"spm_rk_sort": {"sort": old, "min": 0, "dir": "desc", "pos": "ALL"}})
        ok(pg.input_value("#rk-sort") == "recent" and count(pg) == n and f"LAST {n} PPG" in head(pg), f"A browser that saved 'Last {n} PPG' opens Recent PPG over {n} games")
        if old == "l3": compare("Saved Last 3", pg.evaluate(READ), expected(3), 3)
        pg.close()
    pg = page({"spm_rk_sort": {"sort": "ppg", "min": 0, "dir": "desc", "pos": "ALL"}, "spm_rk_recent": "99"})
    sel(pg, "rk-sort", "recent")
    ok(count(pg) == "18", "A saved count out of range is clamped to 18")
    pg.close()

    # 9. no league, phones, both themes
    pg = page({"spm_rk_sort": {"sort": "recent", "min": 0, "dir": "desc", "pos": "ALL"}, "spm_rk_recent": "8"}, league=False)
    ok(count(pg) == "8" and "LAST 8 PPG" in head(pg) and len(pg.evaluate(READ)) > 100, "No league connected: Recent PPG over 8 games in AM's default scoring")
    pg.close()
    for theme in ("dark", "light"):
        for w, h in ((1440, 900), (390, 844)):
            pg = page({"spm_rk_sort": {"sort": "recent", "min": 0, "dir": "desc", "pos": "ALL"}, "spm_rk_recent": "8"}, w=w, h=h, theme=theme, scale=2 if SHOTS else 1)
            over = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            vis = pg.evaluate("() => { const r = document.getElementById('rk-n-wrap').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 0.5 && r.width > 0; }")
            hit = pg.evaluate("() => ['rk-n-dec', 'rk-n-inc'].map(i => { const r = document.getElementById(i).getBoundingClientRect(); return Math.min(r.width, r.height); })")
            col = pg.evaluate("""() => { const lum = c => { const m = c.match(/[\\d.]+/g).map(Number).slice(0, 3).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * m[0] + .7152 * m[1] + .0722 * m[2]; };
              const bg = e => { for (; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(.*, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; };
              return ['rk-n', 'rk-n-unit'].map(i => { const e = document.getElementById(i), a = lum(getComputedStyle(e).color), b = lum(bg(document.querySelector('.masthead') ? document.body : e)); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }); }""")
            ok(over <= 0 and vis and min(hit) >= 28 and min(col) >= 4.5, f"{theme} {w}px: the control is on screen, no sideways scroll ({over}px), buttons {hit}px, text contrast {[round(c, 1) for c in col]}")
            pg.click("#rk-n-inc"); pg.wait_for_timeout(300)
            ok(count(pg) == "9" and ("LAST 9 PPG" in head(pg) or "L9" in head(pg)), f"{theme} {w}px: + works (9 games)")
            pg.click("#rk-n-dec"); pg.wait_for_timeout(300)
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.mouse.move(2, 400); pg.evaluate("() => document.activeElement && document.activeElement.blur()"); pg.wait_for_timeout(400)
                pg.screenshot(path=os.path.join(SHOTS, f"recent-ppg_{theme}_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": min(h, 760)})
                if w == 1440:
                    sel(pg, "rk-week", "8")
                    pg.screenshot(path=os.path.join(SHOTS, f"recent-ppg-week8_{theme}_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 620})
            pg.close()
    ok(not errs, f"No page errors {errs[:3]}")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll Recent PPG checks passed.")
sys.exit(1 if failures else 0)
