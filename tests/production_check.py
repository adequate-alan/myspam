"""Production sort check: the Rankings board ranked by actual fantasy production in the selected league's scoring.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/production_check.py

Uses synthetic Sleeper leagues (mocked API, nothing real) that differ only in scoring, and recomputes every
expected number in Python straight from data/stats/<season>.json with the same rules as the page:
  - a game counts only if he played (a stat line or offensive snaps); byes, inactive weeks, games he never
    entered and future games are never games played
  - each game is scored with the league's scoring_settings (rounded to 0.01 like gamePoints)
  - Season PPG = points / games played; Season Points = total; Last 3 / Last 5 = his most recent games played
Checks: Full vs Half PPR, TE premium none vs +, 4 vs 6 pt passing TD, fumble -1 vs -2, a yardage bonus, All vs
one position, minimum games (default for the week and overrides), bye/inactive handling, injury-shortened games
(starred, still counted), Last 3 with fewer than 3 games, sort direction, persistence, the player drawer, and
that going back to AM Rank restores the board exactly (ranks, values and header).
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
season = int(re.search(r"const STATS_SEASONS = \[(\d+)", src).group(1))
S = json.load(open(os.path.join(ROOT, f"data/stats/{season}.json")))
IX = {c: i for i, c in enumerate(S["cols"])}
STAT_KEYS = ["pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int", "pass_2pt", "pass_sack", "pass_fd", "rush_att", "rush_yd",
             "rush_td", "rush_2pt", "rush_fd", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_2pt", "rec_fd", "fum_lost"]
board = {r["sleeper_id"]: r for r in rows if r["sleeper_id"] and r["pos"] in ("QB", "RB", "WR", "TE")}
name_sid = {r["player"]: sid for sid, r in board.items()}

def played(a):
    return any(a[IX[k]] for k in STAT_KEYS) or (a[IX["snap"]] or 0) > 0

def game_pts(a, pos, sc):
    v = sum(float(sc.get(k, 0)) * (a[IX[k]] or 0) for k in STAT_KEYS)
    v += float(sc.get("bonus_rec_" + pos.lower(), 0)) * (a[IX["rec"]] or 0)
    if sc.get("bonus_rec_yd_100") and (a[IX["rec_yd"]] or 0) >= 100: v += sc["bonus_rec_yd_100"]
    return round(v * 100) / 100

def expected(sc, mode="ppg"):
    """sid -> (value, games played, games in sample, injury-shortened games in sample)"""
    out = {}
    for sid, r in board.items():
        pl = S["players"].get(sid)
        if not pl: continue
        sh = {x[0] for x in (S.get("short") or {}).get(sid, [])}
        games = sorted([(a[0], game_pts(a, pl["p"], sc), a[0] in sh) for a in pl["g"] if played(a)])
        if not games: continue
        k = {"l3": 3, "l5": 5}.get(mode)
        sample = games[-k:] if k else games
        tot = sum(g[1] for g in sample)
        out[sid] = (tot if mode == "pts" else tot / len(sample), len(games), len(sample), sum(1 for g in sample if g[2]))
    return out

# the week being played (earliest week any team still has to play) -> default minimum games
cw = min((next((r[0] for r in rws if r[4] is None), 99) for rws in S["schedule"].values()), default=99)
DEFAULT_MIN = 4 if cw == 99 else 0 if cw <= 2 else 2 if cw == 3 else 3 if cw <= 5 else 4

BASE = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "pass_2pt": 2, "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
        "rec": 1, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2, "fum_lost": -2}
SCORING = {"FULL": BASE, "HALF": {**BASE, "rec": 0.5}, "TEP": {**BASE, "bonus_rec_te": 0.5}, "PTD6": {**BASE, "pass_td": 6},
           "FUM1": {**BASE, "fum_lost": -1}, "BONUS": {**BASE, "bonus_rec_yd_100": 3}}
sids = list(board)[:144]
def league_obj(lid):
    return {"league_id": lid, "name": f"League {lid}", "season": str(season), "status": "in_season", "total_rosters": 12,
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
            "scoring_settings": SCORING[lid], "settings": {"num_teams": 12, "type": 0}}
rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": sids[i::12], "starters": [], "reserve": [], "taxi": [],
            "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i in range(12)]
users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "team_name": f"Team {i+1}", "avatar": ""} for i in range(12)]
def SL(active):
    return {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": str(season),
            "leagues": [{"id": l, "name": f"League {l}", "season": str(season), "status": "in_season", "format": ""} for l in SCORING],
            "activeId": active, "data": {l: {"league": league_obj(l), "users": users, "rosters": rosters} for l in SCORING}, "view": "league"}

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    m = re.match(r"/league/([A-Z0-9]+)(/users|/rosters)?$", path)
    body = [] if not m else league_obj(m.group(1)) if not m.group(2) else users if m.group(2) == "/users" else rosters
    if path == "/state/nfl": body = {"season": str(season), "week": cw if cw != 99 else 18, "season_type": "regular"}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    h = functools.partial(Quiet, directory=ROOT)
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
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
  star: tr.querySelector('.pnum .inj-star') ? tr.querySelector('.pnum .inj-star').title : '',
  spam: (tr.querySelector('.spam-rk') || {}).textContent || '',
  val: ((tr.querySelector('.val .num, .val .num-btn, .val .num-2') || {}).textContent || '').trim() }))"""

def compare(label, got, exp, min_gp, mode="ppg"):
    """every row matches Python (value ±0.05, games), order follows the value, nobody missing or extra"""
    want = {board[s]["player"]: e for s, e in exp.items() if e[1] >= min_gp}
    bad = [(r["name"], r["v"], round(want[r["name"]][0], 2)) for r in got if r["name"] not in want or abs(r["v"] - want[r["name"]][0]) > 0.051]
    gp = [(r["name"], r["sub"]) for r in got if r["name"] in want and mode in ("ppg", "pts") and r["sub"] != f"{want[r['name']][1]} GP"]
    order = [i for i in range(1, len(got)) if want.get(got[i]["name"], (0,))[0] > want.get(got[i - 1]["name"], (0,))[0] + 1e-9]
    ok(not bad and not gp and not order and len(got) == len(want) and [r["rank"] for r in got] == list(range(1, len(got) + 1)),
       f"{label}: {len(got)} rows match the league-scored stats (value {bad[:2]}, games {gp[:2]}, order {order[:2]}, expected {len(want)})")

port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    def page(active, sort=None, w=1440):
        pg = br.new_page(viewport={"width": w, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
        init = "localStorage.clear();" + f"localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL(active)))});"
        if sort: init += f"localStorage.setItem('spm_rk_sort', {json.dumps(json.dumps(sort))});"
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        return pg
    def set_sort(pg, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('rk-sort'); s.value = '{v}'; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(400)
    def set_min(pg, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('rk-min'); s.value = '{v}'; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(300)
    def pos(pg, f):
        pg.click(f"#pos-chips [data-pos={f}]"); pg.wait_for_timeout(300)

    # 1. the normal board, then Season PPG through the UI: the default minimum for this week, then back to AM Rank
    pg = page("FULL")
    spam0, head0 = pg.evaluate(READ), pg.inner_text("#rk-head-row")
    set_sort(pg, "ppg")
    ok(pg.input_value("#rk-min") == str(DEFAULT_MIN), f"Default minimum for week {cw}: {pg.input_value('#rk-min')} (expected {DEFAULT_MIN})")
    full = expected(SCORING["FULL"])
    got = pg.evaluate(READ)
    compare(f"Full PPR, All, Season PPG, {DEFAULT_MIN}+ games", got, full, DEFAULT_MIN)
    hidden = sum(1 for e in full.values() if e[1] < DEFAULT_MIN)
    ok((f"{hidden} under {DEFAULT_MIN} games hidden" in pg.inner_text("#rank-count")) == (hidden > 0), "Count line says how many are under the minimum: " + pg.inner_text("#rank-count"))
    ok("League FULL scoring" in pg.inner_text("#rank-count"), "Count line names the league's scoring")
    ok(pg.inner_text("#rk-head").upper() == "PPG RK" and "SEASON PPG" in pg.inner_text("#rk-head-row").upper(), "Header: PPG Rk and a Season PPG column")
    ok(all(r["spam"].startswith("AM #") for r in got), "Every row keeps its AM rank as secondary context")
    ok(all(r["val"] for r in got) and not pg.query_selector("#rank-body tr.prod .valbar"), "AM value stays as a small number, no value bar")
    widths = pg.evaluate("() => [...document.querySelectorAll('#rank-body .prodbar .fill')].slice(0, 2).map(f => parseFloat(f.style.width))")
    ok(widths and widths[0] == 100, f"PPG bar scaled to the best in the set: {widths}")
    # one position
    all_order = [r["name"] for r in got]
    pos(pg, "RB"); rb = pg.evaluate(READ)
    ok(rb and all(r["pos"] == "RB" for r in rb) and [r["name"] for r in rb] == [n for n in all_order if board[name_sid[n]]["pos"] == "RB"]
       and [r["rank"] for r in rb] == list(range(1, len(rb) + 1)), f"RB filter: only RBs, same order as All, ranked 1–{len(rb)}")
    pos(pg, "ALL")
    # direction
    pg.click("#rk-dir"); pg.wait_for_timeout(300); asc = pg.evaluate(READ)
    ok([r["name"] for r in asc] == all_order[::-1] and asc[0]["rank"] == len(asc) and pg.inner_text("#rk-dir") == "Low → High", "Low → High reverses the list and keeps each player's real rank")
    pg.click("#rk-dir"); pg.wait_for_timeout(300)
    # minimum overrides
    for m in (4, 0):
        set_min(pg, m); g = pg.evaluate(READ)
        compare(f"Minimum {m}+ games", g, full, m)
    # Last 3 with fewer than 3 games (no minimum): uses the games he has, says so
    set_sort(pg, "l3"); l3 = pg.evaluate(READ); e3 = expected(SCORING["FULL"], "l3")
    compare("Last 3 PPG, no minimum", l3, e3, 0, "l3")
    few = [r for r in l3 if e3[name_sid[r["name"]]][2] < 3]
    ok(few and all(r["thin"] and r["sub"] == f"last {e3[name_sid[r['name']]][2]}" for r in few), f"Fewer than 3 games: 'last N' flagged ({len(few)} players, e.g. {few[0]['name'] if few else ''} {few[0]['sub'] if few else ''})")
    ok(all(r["sub"] == "last 3" and not r["thin"] for r in l3 if e3[name_sid[r["name"]]][2] == 3), "Full samples read 'last 3'")
    set_sort(pg, "l5"); compare("Last 5 PPG, no minimum", pg.evaluate(READ), expected(SCORING["FULL"], "l5"), 0, "l5")
    set_sort(pg, "pts"); compare("Season Points, no minimum", pg.evaluate(READ), expected(SCORING["FULL"], "pts"), 0, "pts")
    # bye / inactive: a week with no stat line and no snaps isn't a game; byes and future games aren't either
    set_sort(pg, "ppg"); g0 = {r["name"]: r for r in pg.evaluate(READ)}
    dnp = [(board[s]["player"], len(S["players"][s]["g"]), e[1]) for s, e in full.items() if len(S["players"][s]["g"]) > e[1]]
    ok(dnp and all(g0[n]["sub"] == f"{gp} GP" for n, rws, gp in dnp if n in g0), f"Games he never entered don't count: {dnp[:3]}")
    played_max = max(e[1] for e in full.values())
    ok(played_max <= S["through_week"] and all(int(r["sub"].split()[0]) <= S["through_week"] for r in g0.values()), f"No one has more games than weeks played ({played_max} ≤ {S['through_week']}): byes and future games never count")
    # injury-shortened games: starred, still in the official average
    inj = [board[s]["player"] for s, e in full.items() if e[3]]
    ok(inj and all(g0[n]["star"].startswith("Includes") for n in inj if n in g0), f"Injury-shortened games are starred and counted: {inj[:3]}")
    # drawer: same league-scored PPG and games
    n0 = next(n for n in all_order if g0[n]["v"] > 0)
    pg.locator("#rank-body tr.player", has_text=n0).locator(".pl-name").click(); pg.wait_for_timeout(900)
    hdr = pg.inner_text("#player-modal")
    ok(f"{g0[n0]['v']:.1f}" in hdr and f"{g0[n0]['sub'].split()[0]} G" in hdr, f"Drawer shows the same PPG and games for {n0}: {g0[n0]['v']} · {g0[n0]['sub']}")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    # AM Board view: same production order, AM rank = the base board's overall rank
    pg.click("[data-view=base]"); pg.wait_for_timeout(400); sb = pg.evaluate(READ)
    ok([(r["name"], r["v"]) for r in sorted(sb, key=lambda r: r["name"])] == [(r["name"], r["v"]) for r in sorted(g0.values(), key=lambda r: r["name"])]
       and all(sb[i]["v"] <= sb[i - 1]["v"] for i in range(1, len(sb))) and all(r["spam"] == f"AM #{board[name_sid[r['name']]]['rank']}" for r in sb),
       "AM Board view: same production numbers and order (exact ties follow the board's rank), AM rank is the board's overall rank")
    pg.click("[data-view=league]"); pg.wait_for_timeout(400)
    # back to AM Rank: the board exactly as before
    set_sort(pg, "spam")
    ok(pg.evaluate(READ) == spam0 and pg.inner_text("#rk-head-row") == head0, "AM Rank restores the board exactly (ranks, values, header)")
    pg.close()

    # 2. scoring variants: each league's own scoring reaches the ranking
    base = full
    for lid, label, pick in [("HALF", "Half PPR", "WR"), ("TEP", "TE Premium +", "TE"), ("PTD6", "6-pt passing TD", "QB"),
                             ("FUM1", "Fumble −1", None), ("BONUS", "100-yd receiving bonus", "WR")]:
        pg = page(lid, {"sort": "ppg", "min": 0, "dir": "desc", "pos": "ALL"})
        exp = expected(SCORING[lid]); got = pg.evaluate(READ)
        compare(f"{label}: All, Season PPG", got, exp, 0)
        moved = [board[s]["player"] for s in exp if s in base and abs(exp[s][0] - base[s][0]) > 0.05]
        if pick:
            ok(any(board[name_sid[n]]["pos"] == pick for n in moved), f"{label}: {pick} PPG differs from Full PPR (e.g. {next((n for n in moved if board[name_sid[n]]['pos'] == pick), '')})")
        else:
            ok(moved, f"{label}: players with lost fumbles score differently ({moved[:3]})")
        if lid == "TEP":
            ok(all(board[name_sid[n]]["pos"] == "TE" for n in moved), "TE premium only changes TEs")
            b = name_sid.get("Brock Bowers")
            if b in exp: ok(abs(exp[b][0] - base[b][0]) > 0.5, f"Brock Bowers: {base[b][0]:.1f} Full PPR vs {exp[b][0]:.1f} with TE Premium +")
        pg.close()

    # 2b. the drawer's production ranks (Alan, Oct 8): FPTS rank = position rank by total points, PPG rank = by points per
    # game among players with the week's minimum games (NR below it), both over every player in the stats file at his
    # position, in the selected league's scoring; injury-shortened games starred; AM rank shown first
    def prod_ranks(sc):
        rows = {}
        for sid, pl in S["players"].items():
            if pl["p"] not in ("QB", "RB", "WR", "TE"): continue
            g = [game_pts(a, pl["p"], sc) for a in pl["g"] if played(a)]
            if g: rows[sid] = (pl["p"], sum(g), len(g), len({x[0] for x in (S.get("short") or {}).get(sid, [])} & {a[0] for a in pl["g"] if played(a)}))
        mn = max(1, DEFAULT_MIN); out = {}
        for sid, (ps, pts, gp, sh) in rows.items():
            same = [r for r in rows.values() if r[0] == ps]
            fr = 1 + sum(1 for r in same if r[1] > pts + 1e-9)
            pr = 1 + sum(1 for r in same if r[2] >= mn and r[1] / r[2] > pts / gp + 1e-9) if gp >= mn else None
            out[sid] = (ps, fr, pr, gp, sh)
        return out
    def drawer_ranks(pg, sid):
        pg.evaluate(f"() => document.querySelector('#rank-body [data-player=\"{sid}\"]').click()"); pg.wait_for_timeout(700)
        r = pg.evaluate("""() => { const q = c => { const e = document.querySelector('.pm-prodrk .pr-item.' + c + ' b'); return e ? e.textContent.trim() : null; };
          const d = document.querySelector('.pm-prodrk .pr-diff'), n = document.querySelector('.pm-prodrk .pr-note');
          const first = document.querySelector('.pm-prodrk .pr-item');
          return { am: q('am'), fp: q('fp'), ppg: q('ppg'), diff: d ? d.textContent : '', note: n ? n.textContent : '', firstAm: !!first && first.classList.contains('am') }; }""")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(250)
        return r
    picks = []
    for want in ("TE", "WR", "RB", "QB"):
        picks += [sid for sid, r in board.items() if r["pos"] == want and sid in S["players"]][:3]
    shorts = [sid for sid in board if sid in S["players"] and (S.get("short") or {}).get(sid)]
    picks += shorts[:2]
    for lid in ("FULL", "TEP"):
        pg = page(lid); exp = prod_ranks(SCORING[lid]); bad = []
        for sid in picks:
            e, got = exp.get(sid), drawer_ranks(pg, sid)
            if not e: bad.append((board[sid]["player"], "no games", got)) if got["fp"] not in ("—", None) else None; continue
            ps, fr, pr, gp, sh = e
            want_ppg = f"{ps}{pr}{'*' if sh else ''}" if pr else f"NR · {gp} GP"
            if got["fp"] != f"{ps}{fr}" or got["ppg"] != want_ppg or not got["firstAm"] or (sh and pr and "injury-shortened" not in got["note"]):
                bad.append((board[sid]["player"], got, (f"{ps}{fr}", want_ppg)))
        ok(not bad, f"{lid}: drawer FPTS and PPG ranks match the league-scored stats for {len(picks)} players, AM rank first {bad[:2]}")
        if lid == "TEP": tep_fp = {sid: exp[sid][1] for sid in picks if sid in exp and exp[sid][0] == "TE"}
        else: full_fp = {sid: exp[sid][1] for sid in picks if sid in exp and exp[sid][0] == "TE"}
        pg.close()
    ok(True, f"TE FPTS ranks Full PPR vs TE premium: {[(board[s]['player'], full_fp.get(s), tep_fp.get(s)) for s in tep_fp][:3]}")

    # 3. persistence: RB · Season PPG · 3+ games survives a reload
    pg = page("FULL", {"sort": "ppg", "min": 3, "dir": "desc", "pos": "RB"})
    pg.reload(); pg.wait_for_selector("#rank-body tr.prod"); pg.wait_for_timeout(800)
    rb = pg.evaluate(READ)
    ok(pg.input_value("#rk-sort") == "ppg" and pg.input_value("#rk-min") == "3" and rb and all(r["pos"] == "RB" for r in rb), "Refresh restores RB · Season PPG · 3+ games")
    # phones: nothing overflows the table
    pg.set_viewport_size({"width": 390, "height": 900}); pg.wait_for_timeout(300)
    over = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    tw = pg.evaluate("() => document.querySelector('.table-scroll table').offsetWidth - document.querySelector('.table-scroll').clientWidth")
    ok(over <= 0 and tw <= 0, f"Phone width: no horizontal scroll, the PPG column stays on screen (page {over}px, table {tw}px)")
    pg.close()
    ok(not errs, f"No page errors {errs[:3]}")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll production checks passed.")
sys.exit(1 if failures else 0)
