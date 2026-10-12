"""Week view check: the Rankings board's Week menu (Full season / Week N) shows one NFL week's actual stat lines.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/week_stats_check.py

Synthetic Sleeper leagues (mocked API, nothing real) that differ only in scoring, on a frozen NFL calendar (the same
fixture as tests/league_hub_check.py: Sunday 2:30 PM ET of Week 4, only Week 4's Thursday game played). Every expected
number is recomputed in Python straight from the weekly game logs in data/stats/<season>.json:
  - a week's row counts only if he played (a stat line or offensive snaps); fantasy points = that line scored with
    the league's scoring_settings (rounded to 0.01 like gamePoints)
  - players without a played line read Bye (no game for his team that week) or DNP, never a 0.0 stat line
  - the current week keeps actual stats (Final) apart from projections (Proj / Live · proj) under their own band;
    a future week shows projections only
Checks: the Week menu through the themed dropdown, Fantasy points as the default sort, every row's points and stats
against the game log, header and Sort-menu sorting (pass / rush / receiving yards, receptions, TDs) in both
directions, position filters, Full vs Half PPR and TE premium, injury-shortened stars, persistence across a reload,
going back to Full season restoring the AM board exactly (ranks, values, header), the AM rank never changing, the
phone layout (no sideways scroll), and no page errors. SHOTS=dir saves light/dark screenshots at 1440 and 390.
"""
import csv, functools, http.server, io, json, math, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
season = int(re.search(r"const STATS_SEASONS = \[(\d+)", src).group(1))
STAT_KEYS = ["pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int", "pass_2pt", "pass_sack", "pass_fd", "rush_att", "rush_yd",
             "rush_td", "rush_2pt", "rush_fd", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_2pt", "rec_fd", "fum_lost"]
board = {r["sleeper_id"]: r for r in rows if r["sleeper_id"] and r["pos"] in ("QB", "RB", "WR", "TE")}

# frozen calendar (same rule as league_hub_check.stats_fixture)
FIX_WEEK = 4
def stats_fixture():
    d = json.load(open(os.path.join(ROOT, f"data/stats/{season}.json")))
    date_i = d["schedule_cols"].index("date")
    w_rows = [r for rws in d["schedule"].values() for r in rws if r[0] == FIX_WEEK]
    first = min(r[date_i] for r in w_rows)
    played = {t for t, rws in d["schedule"].items() if any(r[0] == FIX_WEEK and r[date_i] == first for r in rws)}
    for t, rws in d["schedule"].items():
        for r in rws:
            if r[0] > FIX_WEEK or (r[0] == FIX_WEEK and t not in played): r[4] = r[5] = None
    for pl in d["players"].values():
        pl["g"] = [g for g in pl["g"] if g[0] < FIX_WEEK or (g[0] == FIX_WEEK and g[1] in played)]
    d["short"] = {k: [x for x in v if x[0] < FIX_WEEK] for k, v in d["short"].items()}
    d["through_week"] = FIX_WEEK
    if isinstance(d.get("injuries"), dict): d["injuries"]["week"] = FIX_WEEK
    return d, sorted(played)
S, FIX_PLAYED = stats_fixture()
SUNDAY = "2026-10-04T18:30:00Z"
IX = {c: i for i, c in enumerate(S["cols"])}
LAST_WEEK = max(r[0] for rws in S["schedule"].values() for r in rws)

def played(a): return any(a[IX[k]] for k in STAT_KEYS) or (a[IX["snap"]] or 0) > 0
def game_pts(a, pos, sc):
    v = sum(float(sc.get(k, 0)) * (a[IX[k]] or 0) for k in STAT_KEYS)
    v += float(sc.get("bonus_rec_" + pos.lower(), 0)) * (a[IX["rec"]] or 0)
    return round(v * 100) / 100
# Stat columns (Oct 12, second pass): an independent reference for every column. One game = his line + his team's totals
# that week (team_week); a season = the same summed over the games he played, shares = summed numerator ÷ summed
# denominator (never an average of weekly percentages), each week on the team he played for that week.
TW = S.get("team_week") or {}
TC = {c: i for i, c in enumerate(TW.get("cols", []))}
OPP = json.load(open(os.path.join(ROOT, f"data/opportunity/{season}.json")))
OPPI = {c: i for i, c in enumerate(OPP["cols"])}
XMAP = {"x_rec": "rec", "x_rec_yd": "rec_yd", "x_rec_td": "rec_td", "x_rec_fd": "rec_fd", "x_rush_yd": "rush_yd", "x_rush_td": "rush_td",
        "x_rush_fd": "rush_fd", "x_pass_cmp": "pass_cmp", "x_pass_yd": "pass_yd", "x_pass_td": "pass_td", "x_pass_int": "pass_int", "x_pass_fd": "pass_fd"}
PCT = {"tgt_pct": ("rec_tgt", "tm_tgt"), "ay_pct": ("air_yd", "tm_air"), "rush_pct": ("rush_nk", "tm_rush_nk"), "cmp_pct": ("pass_cmp", "pass_att"), "snap": ("snaps", "tm_snaps")}
SUMS = {"rz": ("rz_rush", "rz_rec"), "touch": ("rush_att", "rec"), "opp": ("rush_att", "rec_tgt"), "td": ("pass_td", "rush_td", "rec_td"), "scrim": ("rush_yd", "rec_yd")}
def jround(x): return math.floor(x + 0.5)
def same(k, got, want):   # xFP: sums of model decimals can land either side of a .x5 rounding edge
    if k == "xfp" and got not in (None, "N/A") and want != "N/A": return abs(float(got) - float(want)) < 0.1001
    return got == want
def comp(a, sid, pos, sc):
    g = {c: a[i] for c, i in IX.items()}
    t = TW.get("teams", {}).get(g["tm"], {}).get(str(g["w"]))
    T = lambda k: t[TC[k]] if t else None
    c = {k: g.get(k) for k in ["rec_tgt", "rec", "rec_yd", "rec_td", "rush_att", "rush_yd", "rush_td", "pass_att", "pass_cmp", "pass_yd", "pass_td", "pass_int", "rz_rush", "rz_rec", "snaps"]}
    c["air_yd"] = g["air_yd"] if g["air_yd"] is not None else (None if g["rec_tgt"] else 0)
    c["rush_nk"] = (g["rush_att"] or 0) - (g["kneel"] or 0)
    c["tm_tgt"], c["tm_air"], c["tm_snaps"] = T("tgt"), T("air"), T("snaps")
    c["tm_rush_nk"] = None if T("rush") is None else T("rush") - (T("kneel") or 0)
    xr = next((r for r in OPP["players"].get(sid, []) if r[0] == g["w"]), None)
    c["xfp"] = None
    if xr:
        line = {"pass_att": g["pass_att"] or 0, "rush_att": g["rush_att"] or 0, "rec_tgt": g["rec_tgt"] or 0}
        for k, i in OPPI.items():
            if k in XMAP: line[XMAP[k]] = xr[i] or 0
        xs = {k: v for k, v in sc.items() if not k.startswith("bonus_") or k.startswith("bonus_rec_")}
        xs.pop("fum_lost", None); xs.pop("pass_sack", None)
        v = sum(float(xs.get(k, 0)) * line.get(k, 0) for k in STAT_KEYS) + float(xs.get("pass_inc", 0)) * (line["pass_att"] - line.get("pass_cmp", 0))
        v += float(xs.get("bonus_rec_" + pos.lower(), 0)) * line.get("rec", 0)
        c["xfp"] = jround(v * 100) / 100
    return c
def py_stat(cs, k):
    """None = N/A; else (value, is_pct)"""
    def ssum(*ks):
        vals = [c[x] for c in cs for x in ks if c[x] is not None]
        return sum(vals) if vals else None
    if k in PCT:
        a, b = PCT[k]; pr = [(c[a], c[b]) for c in cs if c[a] is not None and c[b] is not None]
        d = sum(y for _, y in pr)
        return None if not pr or d <= 0 else sum(x for x, _ in pr) / d
    if k in SUMS: return ssum(*SUMS[k])
    return ssum(k)
def disp(k, v):
    if v is None: return "N/A"
    if k in PCT:
        t = jround(v * 1000) / 10
        return f"{jround(t) if t >= 10 or t == 0 else t:g}%"
    if k == "xfp": return f"{v:.1f}"
    return f"{jround(v):,}"
def stat(a, k, sid=None, pos="WR", sc=None):
    return py_stat([comp(a, sid, pos, sc or {})], k)
def week_expect(week, sc, pos=None):
    """sid -> ('act', pts, row) | ('Bye'|'DNP', None, None)"""
    out = {}
    for sid, r in board.items():
        if pos and r["pos"] != pos: continue
        pl = S["players"].get(sid)
        a = next((g for g in (pl or {}).get("g", []) if g[0] == week), None)
        if a and played(a): out[sid] = ("act", game_pts(a, r["pos"], sc), a); continue
        team = a[IX["tm"]] if a else r["team"]
        has_game = any(x[0] == week for x in S["schedule"].get(team, []))
        out[sid] = (("DNP" if has_game else "Bye") if team and team != "FA" else "—", None, None) if week < FIX_WEEK else ("?", None, None)
    return out

BASE = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "pass_2pt": 2, "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
        "rec": 1, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2, "fum_lost": -2}
SCORING = {"FULL": BASE, "HALF": {**BASE, "rec": 0.5}, "TEP": {**BASE, "bonus_rec_te": 0.5}}
sids = list(board)[:144]
def league_obj(lid):
    return {"league_id": lid, "name": f"League {lid}", "season": str(season), "status": "in_season", "total_rosters": 12,
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
            "scoring_settings": SCORING[lid], "settings": {"num_teams": 12, "type": 0, "playoff_week_start": 15}}
rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": sids[i::12], "starters": [], "reserve": [], "taxi": [],
            "settings": {"wins": 2, "losses": 1, "ties": 0, "fpts": 400}} for i in range(12)]
users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "team_name": f"Team {i+1}", "avatar": ""} for i in range(12)]
def SL(active):
    return {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": str(season),
            "leagues": [{"id": l, "name": f"League {l}", "season": str(season), "status": "in_season", "format": ""} for l in SCORING],
            "activeId": active, "data": {l: {"league": league_obj(l), "users": users, "rosters": rosters} for l in SCORING}, "view": "league"}
def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    m = re.match(r"/league/([A-Z0-9]+)(/users|/rosters)?$", path)
    body = [] if not m else league_obj(m.group(1)) if not m.group(2) else users if m.group(2) == "/users" else rosters
    if path == "/state/nfl": body = {"season": str(season), "week": FIX_WEEK, "season_type": "regular"}
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

READ = """() => { const heads = [...document.querySelectorAll('#rk-head-row th')].map(th => (th.querySelector('[data-wk-sort]') || {dataset: {}}).dataset.wkSort || '');
  let band = '';
  const out = [];
  document.querySelectorAll('#rank-body tr').forEach(tr => {
    if (tr.classList.contains('wk-band')) { band = tr.textContent.trim(); return; }
    if (!tr.classList.contains('player')) return;
    const cells = [...tr.children], st = {};
    cells.forEach((td, i) => { const h = heads[i + 1];   // heads[0] is the hidden editor column the rows don't have
      if (h && h !== 'pts') { const n = td.querySelector('.wk-n, .wk-na'); st[h] = n ? n.textContent : null; } });
    out.push({ sid: (tr.querySelector('[data-sid]') || tr.querySelector('.pl-name') || {}).dataset?.sid || '', id: tr.dataset.id,
      name: tr.querySelector('.pl-name').textContent.trim(), rank: tr.querySelector('td.rk').textContent.trim(),
      grp: ['act', 'proj', 'none'].find(c => tr.classList.contains(c)), band,
      pts: tr.querySelector('.pnum') ? Number(tr.querySelector('.pnum').firstChild.textContent) : null,
      sub: tr.querySelector('.psub') ? tr.querySelector('.psub').textContent.trim() : '',
      status: tr.querySelector('.wk-status') ? tr.querySelector('.wk-status').textContent.trim() : '',
      star: !!tr.querySelector('.pnum .inj-star'), am: (tr.querySelector('.spam-rk') || {}).textContent || '', st });
  });
  return { heads, rows: out }; }"""
BOARD = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => [tr.dataset.id, tr.querySelector('td.rk').textContent.trim(),
  ((tr.querySelector('.val .num, .val .num-btn') || {}).textContent || '').trim()])"""
name_of = {sid: r["player"] for sid, r in board.items()}
by_name = {r["player"]: sid for sid, r in board.items()}

port = serve()
shots = os.environ.get("SHOTS")
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    def page(active, w=1440, theme=None, fresh=True):
        pg = br.new_page(viewport={"width": w, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install(time=SUNDAY)
        pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(S)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
        init = "localStorage.clear();" + f"localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL(active)))});"
        if theme: init += f"localStorage.setItem('spm_theme', '{theme}');"
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        return pg
    def set_sel(pg, sid, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('{sid}'); s.value = '{v}'; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(400)
    def pos(pg, f):
        pg.click(f"#pos-chips [data-pos={f}]"); pg.wait_for_timeout(300)
    def check_week(label, got, week, sc, pos_f=None, by_pts=True):
        exp = week_expect(week, sc, pos_f)
        act = [r for r in got["rows"] if r["grp"] == "act"]
        want_act = {name_of[s]: e for s, e in exp.items() if e[0] == "act"}
        bad = [(r["name"], r["pts"], want_act.get(r["name"], (0, None))[1]) for r in act if r["name"] not in want_act or abs(r["pts"] - want_act[r["name"]][1]) > 0.051]
        stbad = []
        for r in act:
            a = want_act.get(r["name"], (0, 0, None))[2]
            if a is None: continue
            sid = by_name[r["name"]]
            for k, v in r["st"].items():
                want = disp(k, stat(a, k, sid, board[sid]["pos"], sc))
                if not same(k, v, want): stbad.append((r["name"], k, v, want))
        order = [i for i in range(1, len(act)) if act[i]["pts"] > act[i - 1]["pts"] + 1e-9] if by_pts else []
        ok(not bad and not stbad and not order and len(act) == len(want_act) and [r["rank"] for r in act] == [str(i) for i in range(1, len(act) + 1)],
           f"{label}: {len(act)} players with stats match the Week {week} game log (points {bad[:2]}, stats {stbad[:2]}, order {order[:2]}, expected {len(want_act)})")
        if week < FIX_WEEK:
            none = {r["name"]: r["status"] for r in got["rows"] if r["grp"] == "none"}
            want_none = {name_of[s]: e[0] for s, e in exp.items() if e[0] != "act"}
            diff = [(n, none.get(n), want_none.get(n)) for n in set(none) | set(want_none) if none.get(n) != want_none.get(n)]
            fake = [r["name"] for r in got["rows"] if r["grp"] == "none" and (r["pts"] is not None or any(v is not None for v in r["st"].values()))]
            ok(not diff and not fake and not [r for r in got["rows"] if r["grp"] == "proj"],
               f"{label}: players without a Week {week} game read Bye / DNP with no stat line ({len(want_none)}: {sum(1 for v in want_none.values() if v == 'Bye')} bye, {sum(1 for v in want_none.values() if v == 'DNP')} DNP; mismatches {diff[:3]}, fake numbers {fake[:2]})")
        return act

    # 1. the AM board before; the Week menu through the themed dropdown
    pg = page("FULL")
    board0, head0 = pg.evaluate(BOARD), pg.inner_text("#rk-head-row")
    opts = pg.evaluate("() => [...document.getElementById('rk-week').options].map(o => o.textContent)")
    ok(opts[0] == "Full season" and opts[1] == "Season stats" and len(opts) == LAST_WEEK + 2 and opts[2] == "Week 1" and opts[FIX_WEEK + 1] == f"Week {FIX_WEEK} · now" and opts[FIX_WEEK + 2] == f"Week {FIX_WEEK + 1} · proj",
       f"Week menu: Full season, Season stats + Weeks 1–{LAST_WEEK}, the current week marked now and later weeks proj ({opts[:3]} … {opts[FIX_WEEK + 1:FIX_WEEK + 3]})")
    btn = pg.locator("#rk-week + .dd-btn")
    ok(btn.inner_text().strip() == "Full season", f"The Week menu starts on Full season ({btn.inner_text().strip()!r})")
    btn.click(); pg.wait_for_timeout(200)
    pg.locator(".dd-menu:not([hidden]) .dd-opt", has_text="Week 2").first.click(); pg.wait_for_timeout(600)
    g2 = pg.evaluate(READ)
    ok(pg.input_value("#rk-wsort") == "pts" and g2["heads"][4] == "pts" and pg.locator("#rk-wsort-lab").is_visible() and not pg.locator("#rk-sort-lab").is_visible() and not pg.locator("#rk-min + .dd-btn").is_visible(),
       "Picking Week 2 sorts by Fantasy points, swaps in the week's Sort menu and hides the season-only minimum games")
    act2 = check_week("Week 2 · All · Full PPR", g2, 2, SCORING["FULL"])
    ok(g2["heads"][5:] == ["rec_tgt", "tgt_pct", "rec", "rec_yd", "rush_att", "rush_yd", "touch", "snap"], f"All positions show TGT · TGT% · REC · REC YDS · ATT · RUSH YDS · TOUCH · SNAP% ({g2['heads'][5:]})")
    bands = [r["band"] for r in g2["rows"] if r["grp"] == "none"][:1]
    ok(bands and bands[0].startswith("No stats this week"), f"Players without stats sit under their own band ({bands})")
    ok(all(r["sub"] == "Final" for r in act2), "Every Week 2 stat line is labelled Final")
    shorts = {(sid, x[0]) for sid, lst in S["short"].items() for x in lst}
    want_star = {name_of[s] for s in board if (s, 2) in shorts and week_expect(2, BASE)[s][0] == "act"}
    got_star = {r["name"] for r in act2 if r["star"]}
    ok(got_star == want_star, f"Injury-shortened Week 2 games carry the * ({sorted(got_star)[:3]}, expected {sorted(want_star)[:3]})")
    ams = {r["id"]: r["am"] for r in g2["rows"]}
    board_rank = {b[0]: b[1] for b in board0}
    ok(all(ams[i].replace("AM #", "") == re.sub(r"\D.*", "", board_rank[i]) for i in ams if i in board_rank),
       "Each row's AM # is his board rank, unchanged by the week view")

    # 2. sorting: header clicks and the Sort menu, both directions
    numv = lambda v: float(v.rstrip("%").replace(",", "")) if v not in (None, "N/A") else -1
    for k in ["rec_yd", "rush_yd", "rec", "tgt_pct", "touch", "snap"]:
        pg.click(f"#rk-head-row [data-wk-sort={k}]"); pg.wait_for_timeout(350)
        g = pg.evaluate(READ); act = [r for r in g["rows"] if r["grp"] == "act"]
        vals = [numv(r["st"][k]) for r in act]
        ok(vals == sorted(vals, reverse=True) and len(act) == len(act2) and pg.input_value("#rk-wsort") == k,
           f"Header sort by {k}: high → low ({vals[:4]}), the Sort menu follows")
    pg.click("#rk-head-row [data-wk-sort=snap]"); pg.wait_for_timeout(350)
    g = pg.evaluate(READ); vals = [numv(r["st"]["snap"]) for r in g["rows"] if r["grp"] == "act" and r["st"]["snap"] != "N/A"]
    ok(vals == sorted(vals) and pg.inner_text("#rk-dir") == "Low → High", f"Clicking the sorted header again flips to low → high ({vals[:4]})")
    for k in ["rec", "pass_yd", "td", "ay_pct"]:
        set_sel(pg, "rk-wsort", k)
        g = pg.evaluate(READ); vals = [numv(r["st"][k]) for r in g["rows"] if r["grp"] == "act"]
        ok(k in g["heads"] and vals == sorted(vals, reverse=True), f"Sort menu: {k}, high → low, its column added ({vals[:4]})")
        check_week(f"Week 2 · sorted by {k}", g, 2, SCORING["FULL"], by_pts=False)

    # 3. position filters keep working, with position stat columns
    set_sel(pg, "rk-wsort", "pts")
    for f, cols in [("QB", ["pass_att", "pass_yd", "pass_td", "pass_int", "rush_att", "rush_yd"]), ("RB", ["rush_att", "rush_yd", "rec_tgt", "tgt_pct", "touch", "opp", "snap"]),
                    ("WR", ["rec_tgt", "tgt_pct", "rec", "rec_yd", "snap"]), ("TE", ["rec_tgt", "tgt_pct", "rec", "rec_yd", "snap"])]:
        pos(pg, f); g = pg.evaluate(READ)
        check_week(f"Week 2 · {f}", g, 2, SCORING["FULL"], f)
        ok(g["heads"][5:] == cols, f"{f} columns: {g['heads'][5:]}")
    pos(pg, "RB"); set_sel(pg, "rk-wsort", "rush_yd")
    g = pg.evaluate(READ); vals = [float(r["st"]["rush_yd"].replace(",", "")) for r in g["rows"] if r["grp"] == "act"]
    ok(vals == sorted(vals, reverse=True), f"RB · Week 2 by rushing yards ({vals[:3]})")
    pos(pg, "ALL"); set_sel(pg, "rk-wsort", "pts")

    # 4. the current week (Sunday of Week 4) and a future week
    set_sel(pg, "rk-week", str(FIX_WEEK)); g4 = pg.evaluate(READ)
    act4 = [r for r in g4["rows"] if r["grp"] == "act"]
    played_teams = set(FIX_PLAYED)
    exp4 = {name_of[s] for s, e in week_expect(FIX_WEEK, BASE).items() if e[0] == "act"}
    ok({r["name"] for r in act4} == exp4 and all(r["sub"] == "Final" for r in act4),
       f"Week {FIX_WEEK} (now): only the Thursday game's players ({'/'.join(FIX_PLAYED)}) have actual stats, labelled Final ({len(act4)})")
    check_week(f"Week {FIX_WEEK} · actual stats", g4, FIX_WEEK, BASE)
    proj4 = [r for r in g4["rows"] if r["grp"] == "proj"]
    ok(proj4 and all(r["sub"].startswith(("Proj", "Live")) and not any(v is not None for v in r["st"].values()) for r in proj4)
       and proj4[0]["band"].startswith("Not played yet"),
       f"Week {FIX_WEEK}: the rest are projections under their own band, labelled Proj / Live · proj, with no stat line ({len(proj4)}; {sorted({r['sub'] for r in proj4})})")
    live = [r for r in proj4 if r["sub"].startswith("Live")]
    ok(live, f"Sunday 2:30 PM: games in progress read Live · proj ({len(live)})")
    nxt = FIX_WEEK + 2
    set_sel(pg, "rk-week", str(nxt)); g6 = pg.evaluate(READ)
    ok(not [r for r in g6["rows"] if r["grp"] == "act"] and [r for r in g6["rows"] if r["grp"] == "proj"] and
       all(r["status"] == "Bye" or r["grp"] == "proj" or r["status"] in ("Out", "—") for r in g6["rows"]) and
       next(r for r in g6["rows"] if r["grp"] == "proj")["band"].startswith(f"Week {nxt} hasn't been played"),
       f"Week {nxt} (future): projections and byes only, no actual stats")

    # 5. persistence across a reload, and Full season restores the AM board exactly
    set_sel(pg, "rk-week", "3"); pg.click("#rk-head-row [data-wk-sort=rec_yd]"); pg.wait_for_timeout(300); pos(pg, "WR")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
    g3 = pg.evaluate(READ)
    ok(pg.input_value("#rk-week") == "3" and pg.input_value("#rk-wsort") == "rec_yd" and g3["heads"][4] == "pts" and "rec_yd" in g3["heads"]
       and pg.get_attribute("#pos-chips [data-pos=WR]", "aria-pressed") == "true",
       "After a reload: Week 3, sorted by receiving yards, WR tab")
    vals = [float(r["st"]["rec_yd"].replace(",", "")) for r in g3["rows"] if r["grp"] == "act"]
    ok(vals == sorted(vals, reverse=True), f"Week 3 WRs by receiving yards after the reload ({vals[:3]})")
    set_sel(pg, "rk-week", "6"); g = pg.evaluate(READ)
    ok(pg.input_value("#rk-wsort") == "rec_yd", "Switching from one week to another keeps the chosen stat sort")
    pos(pg, "ALL"); set_sel(pg, "rk-week", "")
    ok(pg.evaluate(BOARD) == board0 and pg.inner_text("#rk-head-row") == head0 and pg.locator("#rk-sort-lab").is_visible(),
       "Full season brings back the AM board exactly: same ranks, values and header")
    set_sel(pg, "rk-week", "1")
    ok(pg.input_value("#rk-wsort") == "pts", "Coming from Full season, a week opens on Fantasy points again")
    set_sel(pg, "rk-week", "")
    pg.close()

    # 5b. Season stats: totals over the games he played; shares from summed numerators and team denominators
    EXTRA = ["xfp", "air_yd", "ay_pct", "rush_pct", "rz", "pass_cmp", "cmp_pct", "snaps", "opp", "rec_td", "td"]
    def season_expect(sc, pos_f=None):
        out = {}
        for sid, r in board.items():
            if pos_f and r["pos"] != pos_f: continue
            games = [a for a in (S["players"].get(sid) or {}).get("g", []) if played(a)]
            out[sid] = (games, round(sum(game_pts(a, r["pos"], sc) for a in games) * 100) / 100, [comp(a, sid, r["pos"], sc) for a in games])
        return out
    def check_season(label, got, sc, pos_f=None):
        exp = season_expect(sc, pos_f)
        act = [r for r in got["rows"] if r["grp"] == "act"]
        want = {name_of[s]: e for s, e in exp.items() if e[0]}
        bad, stbad = [], []
        for r in act:
            e = want.get(r["name"])
            if not e or abs(r["pts"] - e[1]) > 0.051 or r["sub"] != f"{len(e[0])} GP": bad.append((r["name"], r["pts"], e and e[1], r["sub"])); continue
            for k, v in r["st"].items():
                w = disp(k, py_stat(e[2], k))
                if not same(k, v, w): stbad.append((r["name"], k, v, w))
        none = {r["name"] for r in got["rows"] if r["grp"] == "none"}
        order = [i for i in range(1, len(act)) if act[i]["pts"] > act[i - 1]["pts"] + 1e-9]
        ok(not bad and not stbad and not order and len(act) == len(want) and none == {name_of[s] for s, e in exp.items() if not e[0]},
           f"{label}: {len(act)} season lines match the game logs (points/GP {bad[:2]}, stats {stbad[:3]}, order {order[:2]}, expected {len(want)}, no games {len(none)})")
        return act
    pg = page("FULL")
    opts = pg.evaluate("() => [...document.getElementById('rk-week').options].map(o => o.textContent)")
    ok(opts[:3] == ["Full season", "Season stats", "Week 1"], f"Week menu: Full season (the AM board), then Season stats, then the weeks ({opts[:3]})")
    set_sel(pg, "rk-week", "0"); gs = pg.evaluate(READ)
    ok(gs["heads"][4] == "pts" and pg.locator("#rk-cols-btn").is_visible() and "Season stats · through Week" in pg.inner_text("#rank-count"),
       f"Season stats opens on fantasy points with the Columns button ({pg.inner_text('#rank-count')[:70]})")
    acts = check_season("Season stats · All · Full PPR", gs, SCORING["FULL"])
    ok(not [r for r in gs["rows"] if r["grp"] == "proj"] and all(r["sub"].endswith("GP") for r in acts), "Season stats never mix in projections")
    # a share is the ratio of sums, not the mean of weekly shares: find players where the two differ and check ours
    diffw = []
    for sid, (games, _, cs) in season_expect(BASE).items():
        if len(cs) < 2: continue
        weekly = [py_stat([c], "tgt_pct") for c in cs]
        if None in weekly: continue
        mean, ros = sum(weekly) / len(weekly), py_stat(cs, "tgt_pct")
        if ros is not None and disp("tgt_pct", mean) != disp("tgt_pct", ros): diffw.append(name_of[sid])
    shown = {r["name"]: r["st"].get("tgt_pct") for r in acts}
    ok(diffw and all(n in shown for n in diffw[:5]), f"{len(diffw)} players whose averaged weekly TGT% differs from summed targets ÷ team targets show the latter (e.g. {diffw[:3]})")
    movers = [name_of[s] for s, (games, _, _) in season_expect(BASE).items() if len({a[IX["tm"]] for a in games}) > 1]
    ok(True, f"Players with two teams this season (each week's own team totals): {movers[:4] or 'none in this data'}")
    # sorting the season by the new stats, header and menu, both directions
    for k in ["tgt_pct", "snap", "touch"]:
        pg.click(f"#rk-head-row [data-wk-sort={k}]"); pg.wait_for_timeout(350)
        g = pg.evaluate(READ); vals = [r["st"][k] for r in g["rows"] if r["grp"] == "act"]
        num = [float(v.rstrip("%").replace(",", "")) for v in vals if v != "N/A"]
        ok(num == sorted(num, reverse=True) and all(v == "N/A" for v in vals[len(num):]), f"Season sort by {k}: high → low, N/A last ({vals[:4]})")
    pg.click("#rk-head-row [data-wk-sort=touch]"); pg.wait_for_timeout(350)
    g = pg.evaluate(READ); num = [float(r["st"]["touch"].replace(",", "")) for r in g["rows"] if r["grp"] == "act" and r["st"]["touch"] != "N/A"]
    ok(num == sorted(num), "Clicking TOUCH again sorts low → high")
    set_sel(pg, "rk-wsort", "rz"); g = pg.evaluate(READ)
    num = [float(r["st"]["rz"]) for r in g["rows"] if r["grp"] == "act" and r["st"].get("rz") not in (None, "N/A")]
    ok("rz" in g["heads"] and num == sorted(num, reverse=True), f"Sort menu: Red-zone touches adds its column and sorts ({num[:4]})")
    set_sel(pg, "rk-wsort", "pts")

    # 5c. Columns menu: per position, saved, reset; every optional stat checked against the logs (week and season)
    pos(pg, "WR")
    pg.click("#rk-cols-btn"); pg.wait_for_timeout(250)
    ok(pg.locator("#rk-cols-pop").is_visible() and pg.evaluate("() => document.activeElement.matches('#rk-cols-pop input')"),
       "Columns opens a menu with focus on its first option")
    na = pg.evaluate("() => [...document.querySelectorAll('#rk-cols-pop .rk-col-opt.na')].map(x => [x.textContent.trim(), x.querySelector('input').disabled])")
    ok(len(na) == 3 and all(d for _, d in na), f"Routes run, route participation and YPRR are listed as not available, disabled ({na})")
    on = pg.evaluate("() => [...document.querySelectorAll('#rk-cols-pop [data-wk-col]:checked')].map(x => x.dataset.wkCol)")
    ok(on == ["rec_tgt", "tgt_pct", "rec", "rec_yd", "snap"], f"WR defaults checked: {on}")
    pg.click("#rk-cols-pop [data-wk-col=snap]"); pg.wait_for_timeout(250)
    for k in EXTRA: pg.click(f"#rk-cols-pop [data-wk-col={k}]"); pg.wait_for_timeout(150)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    ok(not pg.locator("#rk-cols-pop").is_visible() and pg.evaluate("() => document.activeElement.id") == "rk-cols-btn", "Escape closes the menu and returns focus to Columns")
    gw = pg.evaluate(READ)
    ok("snap" not in gw["heads"] and all(k in gw["heads"] for k in EXTRA), f"WR shows the chosen columns, SNAP% hidden ({gw['heads'][5:]})")
    check_season("Season stats · WR · chosen columns", gw, SCORING["FULL"], "WR")
    xs = [r["st"]["xfp"] for r in gw["rows"] if r["grp"] == "act"]
    ok(sum(1 for v in xs if v != "N/A") > 50, f"xFP is filled from the expected-points data ({sum(1 for v in xs if v != 'N/A')} of {len(xs)})")
    set_sel(pg, "rk-week", "2"); g = pg.evaluate(READ)
    check_week("Week 2 · WR · chosen columns", g, 2, SCORING["FULL"], "WR")
    pos(pg, "ALL"); g = pg.evaluate(READ)
    ok(g["heads"][5:] == ["rec_tgt", "tgt_pct", "rec", "rec_yd", "rush_att", "rush_yd", "touch", "snap"], "All players keeps its own columns")
    pos(pg, "QB"); pg.click("#rk-cols-btn"); pg.wait_for_timeout(200)
    for k in ["pass_cmp", "cmp_pct", "rush_pct", "xfp"]: pg.click(f"#rk-cols-pop [data-wk-col={k}]"); pg.wait_for_timeout(150)
    pg.keyboard.press("Escape"); g = pg.evaluate(READ)
    check_week("Week 2 · QB · passing columns", g, 2, SCORING["FULL"], "QB")
    ok("RUSH ATT" in pg.inner_text("#rk-head-row") and "PASS ATT" in pg.inner_text("#rk-head-row"), "QB headers tell pass and rush attempts apart")
    pos(pg, "WR")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
    g = pg.evaluate(READ)
    ok(pg.input_value("#rk-week") == "2" and "snap" not in g["heads"] and all(k in g["heads"] for k in EXTRA), "After a reload: Week 2, WR, the chosen columns")
    pg.click("#rk-cols-btn"); pg.wait_for_timeout(200); pg.click("#rk-cols-reset"); pg.wait_for_timeout(300)
    pg.mouse.click(5, 5); pg.wait_for_timeout(200)
    g = pg.evaluate(READ)
    ok(g["heads"][5:] == ["rec_tgt", "tgt_pct", "rec", "rec_yd", "snap"] and not pg.locator("#rk-cols-pop").is_visible(), f"Reset to WR defaults; a click outside closes the menu ({g['heads'][5:]})")
    if shots:
        os.makedirs(shots, exist_ok=True)
        for theme in ("dark", "light"):
            for w in (1440, 390):
                q = page("FULL", w=w, theme=theme); pos(q, "WR"); set_sel(q, "rk-week", "0")
                q.screenshot(path=os.path.join(shots, f"season_wr_{theme}_{w}.png"))
                q.click("#rk-cols-btn"); q.wait_for_timeout(250)
                q.screenshot(path=os.path.join(shots, f"columns_{theme}_{w}.png"))
                q.close()
    set_sel(pg, "rk-week", ""); pos(pg, "ALL")
    pg.close()

    # 6. league scoring: Half PPR and TE premium
    def week_pts(active, week, f):
        q = page(active); pos(q, f); set_sel(q, "rk-week", str(week)); g = q.evaluate(READ); q.close()
        return g
    gh = week_pts("HALF", 2, "WR"); check_week("Week 2 · WR · Half PPR", gh, 2, SCORING["HALF"], "WR")
    gt = week_pts("TEP", 2, "TE"); check_week("Week 2 · TE · TE premium +", gt, 2, SCORING["TEP"], "TE")
    gf = week_pts("FULL", 2, "TE")
    full_te = {r["name"]: r["pts"] for r in gf["rows"] if r["grp"] == "act"}
    diffs = [(r["name"], round(r["pts"] - full_te[r["name"]], 2), float(r["st"]["rec"]) * 0.5) for r in gt["rows"] if r["grp"] == "act" and r["name"] in full_te]
    ok(diffs and all(abs(d - w) < 0.051 for _, d, w in diffs), f"TE premium + adds 0.5 per catch to each TE's week ({diffs[:3]})")

    # 7. phone width: no sideways scroll, fantasy points and the sorted stat stay on screen
    for w in (390, 375):
        q = page("FULL", w=w); set_sel(q, "rk-week", "2"); set_sel(q, "rk-wsort", "rush_yd")
        m = q.evaluate("""() => ({ doc: document.documentElement.scrollWidth, vw: innerWidth,
          tbl: document.querySelector('#rank-body').closest('table').getBoundingClientRect().right,
          vis: [...document.querySelectorAll('#rk-head-row th')].filter(th => th.offsetParent && getComputedStyle(th).display !== 'none').map(th => th.textContent.trim()) })""")
        ok(m["doc"] <= m["vw"] and m["tbl"] <= m["vw"] + 1, f"{w}px: no sideways scroll (page {m['doc']}, table right edge {round(m['tbl'])}, viewport {m['vw']})")
        ok(any(t.startswith("FPTS") for t in m["vis"]) and any(t.startswith("RUSH YDS") for t in m["vis"]) and not any(t.startswith("REC YDS") for t in m["vis"]),
           f"{w}px: FPTS and the sorted stat stay, other stat columns step aside ({m['vis']})")
        q.close()

    if shots:
        os.makedirs(shots, exist_ok=True)
        for theme in ("dark", "light"):
            for w in (1440, 390):
                q = page("FULL", w=w, theme=theme); set_sel(q, "rk-week", "2")
                q.screenshot(path=os.path.join(shots, f"week2_{theme}_{w}.png"))
                set_sel(q, "rk-week", str(FIX_WEEK)); q.evaluate("() => { const b = [...document.querySelectorAll('.wk-band')][0]; if (b) b.scrollIntoView({block: 'center'}); }"); q.wait_for_timeout(200)
                q.screenshot(path=os.path.join(shots, f"week{FIX_WEEK}_{theme}_{w}.png"))
                q.close()

    ok(not errs, f"No page errors {errs[:3]}")
    br.close()

print("\nAll week view checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
sys.exit(1 if failures else 0)
