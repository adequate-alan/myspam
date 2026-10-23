"""Practice Report days on the page (Alan, Oct 23: the Falcons' Week 7 report in Bijan Robinson's drawer showed Wednesday's
LP under Thu, Wednesday blank and Thursday's DNP / FP missing, checked against atlantafalcons.com).

Root cause: not the data. The stats file and the live site held the official days (Robinson LP / DNP, Collins LP / FP,
Jerrell LP / DNP, Zaccheaus LP / LP) from the Fri 13:41 UTC run on. The drawer showed the file as committed Thu Oct 22
14:04 UTC, before the day fix: a tab keeps the stats file it loaded, and stats refreshes don't change BUILD_ID, so no
update prompt ever told an open tab to reload. Also, a day whose report wasn't out yet read "–", the same as "not on that
day's report".

On the real Week 7 reports (the injuries blocks as committed Thu 00:15 UTC and Fri 17:25 UTC, `tests/fixtures/practice/`),
the frozen test board and a clock on Thursday or Friday:

  A. Thursday, Wednesday's report out: Falcons Wed LP, Thu and Fri Pending (never "–", never Wednesday's LP under Thu).
  B. Friday, Thursday's report out: Robinson LP / DNP, Collins LP / FP, Jerrell LP / DNP, Zaccheaus LP / LP, Fri Pending;
     a player first listed Thursday reads "–" (not on Wednesday's report) under Wed; Bijan himself "Not on Week 7 report".
  C. Thursday- and Monday-game teams (CHI, DAL) show one Latest column, no day and no Pending.
  D. An open tab (Alan, Oct 23, at approval): with a synthetic league connected and a player's Practice Report open, for a
     Sunday (ATL), Thursday (CHI) and Monday (DAL) team: an unchanged file offers nothing; a changed file (Wednesday's ->
     Thursday's report) offers a quiet refresh; × keeps that version from offering again, a newer one offers once more;
     Refresh reloads with the same league, tab and drawer (player, Practice Report) and the new report, and offers nothing
     after it; board values and ranks are identical before and after.

    python3 tests/practice_display_check.py            (CHROMIUM=/path for a non-Playwright Chromium)
"""
import functools, http.server, json, os, re, socketserver, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fixture_board as FB
from playwright.sync_api import sync_playwright

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

WEEK = 7
BIJAN, MONANGAI, PICKENS = "9509", "12534", "8137"
FIX = os.path.join(ROOT, "tests/fixtures/practice")
INJ = {k: json.load(open(os.path.join(FIX, f"wk7_{k}.json"))) for k in ("wed", "thu")}

def stats(inj):   # the real stats file with Week 7 unplayed (the Thursday game included) and the given report
    d = json.load(open(os.path.join(ROOT, "data/stats/2026.json")))
    for rows in d["schedule"].values():
        for r in rows:
            if r[0] >= WEEK: r[4] = r[5] = None
    for pl in d["players"].values():
        pl["g"] = [g for g in pl["g"] if g[0] < WEEK]
    d["through_week"] = WEEK - 1
    d["injuries"] = inj
    return json.dumps(d)
BODY = {k: stats(v) for k, v in INJ.items()}

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
THURSDAY, FRIDAY = "2026-10-22T16:00:00Z", "2026-10-23T17:30:00Z"

TABLE = """() => [...document.querySelectorAll('#player-body section.pr-sec')].map(s => ({
  team: s.querySelector('.pr-team b') ? s.querySelector('.pr-team b').textContent : '',
  head: [...s.querySelectorAll('thead th')].map(th => th.textContent.trim()),
  rows: Object.fromEntries([...s.querySelectorAll('tbody tr:not(.pr-group)')].map(tr => [tr.querySelector('.pl-name').textContent.trim(),
    [...tr.querySelectorAll('td.pr-day')].map(td => ({ t: td.textContent.trim(), tip: (td.firstElementChild && (td.firstElementChild.title || td.firstElementChild.getAttribute('data-hc-t'))) || '' }))]))
}))"""

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    serve = {"key": "wed", "etag": '"wed"'}

    def page_at(clock, key, width=1440):
        serve.update(key=key, etag=f'"{key}"')
        pg = br.new_page(viewport={"width": width, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install(time=clock)
        FB.route(pg, BASE)
        pg.route("**/data/stats/2026.json*", lambda r: r.fulfill(status=200, content_type="application/json", headers={"ETag": serve["etag"]},
                                                                   body="" if r.request.method == "HEAD" else BODY[serve["key"]]))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.goto(BASE + "/#rankings"); pg.wait_for_timeout(2500)
        return pg

    def practice(pg, sid, full=True):
        pg.evaluate("sid => document.querySelector(`#rank-body [data-player=\"${sid}\"]`).click()", sid); pg.wait_for_timeout(1200)
        pg.evaluate("() => document.querySelector('#player-body [data-pp-tab=\"practice\"], #player-modal [data-pp-tab=\"practice\"]').click()"); pg.wait_for_timeout(500)
        if full and pg.query_selector("#player-body [data-pr-full][aria-expanded=false]"):
            pg.click("#player-body [data-pr-full]"); pg.wait_for_timeout(400)
        return {s["team"]: s for s in pg.evaluate(TABLE)}, pg.inner_text("#player-body")

    days = lambda cells: [c["t"] for c in cells]

    # A. Thursday: only Wednesday's report is out
    pg = page_at(THURSDAY, "wed")
    secs, txt = practice(pg, BIJAN)
    atl = secs.get("Atlanta Falcons")
    ok(atl is not None and atl["head"][1:4] == ["Wed", "Thu", "Fri"], f"A. Falcons table has Wed / Thu / Fri ({atl and atl['head']})")
    for name in ("Brian Robinson", "Beaux Collins", "Michael Jerrell", "Olamide Zaccheaus"):
        ok(atl and days(atl["rows"].get(name, [])) == ["LP", "Pending", "Pending"], f"A. Thursday: {name} Wed LP, Thu and Fri Pending ({atl and days(atl['rows'].get(name, []))})")
    pend = atl and atl["rows"]["Brian Robinson"][1]["tip"]
    ok(pend and "Thursday's report isn't out yet" in pend, f"A. Pending says that day's report isn't out ({pend!r})")
    ok("Pending means that day's report isn't out yet" in txt, "A. the note explains – vs Pending")
    if os.environ.get("SHOTS"): pg.screenshot(path=os.path.join(os.environ["SHOTS"], "thursday_falcons.png"))
    pg.close()

    # B. Friday afternoon: Thursday's report is out, Friday's isn't
    pg = page_at(FRIDAY, "thu")
    secs, txt = practice(pg, BIJAN)
    atl = secs.get("Atlanta Falcons")
    official = {"Brian Robinson": ["LP", "DNP"], "Beaux Collins": ["LP", "FP"], "Michael Jerrell": ["LP", "DNP"], "Olamide Zaccheaus": ["LP", "LP"]}
    for name, (w, t) in official.items():
        ok(atl and days(atl["rows"].get(name, [])) == [w, t, "Pending"], f"B. Friday: {name} {w} / {t} / Pending (official Falcons report; shown {atl and days(atl['rows'].get(name, []))})")
    ct = atl and atl["rows"].get("Cameron Thomas")
    ok(ct and days(ct) == ["–", "LP", "Pending"] and "Not on Wednesday's report" in ct[0]["tip"], f"B. first listed Thursday: Wed reads – 'not on Wednesday's report' ({ct and [days(ct), ct[0]['tip']]})")
    ok("Not on Week 7 report" in txt, "B. Bijan himself: Not on Week 7 report")
    if os.environ.get("SHOTS"): pg.screenshot(path=os.path.join(os.environ["SHOTS"], "friday_falcons.png"))
    ok(not errs, f"no page errors ({errs[:2]})")

    # C. Thursday- and Monday-game teams: one Latest column, no day, no Pending
    pg = page_at(THURSDAY, "wed")
    secs, _ = practice(pg, MONANGAI)
    chi = secs.get("Chicago Bears")
    ok(chi and chi["head"][1] == "Latest" and len(chi["head"]) == 3, f"C. Chicago (Thursday game): one Latest column ({chi and chi['head']})")
    ok(chi and all(len(c) == 1 and c[0]["t"] != "Pending" for c in chi["rows"].values()), "C. Chicago: no Pending, no day")
    pg.close()
    pg = page_at(FRIDAY, "thu")
    secs, _ = practice(pg, PICKENS)
    dal = secs.get("Dallas Cowboys")
    ok(dal and dal["head"][1] == "Latest" and days(dal["rows"].get("George Pickens", [])) == ["LP"], f"C. Dallas (Monday game): Latest LP ({dal and [dal['head'], days(dal['rows'].get('George Pickens', []))]})")
    pg.close()

    # D. an open tab learns the stats changed, for a Sunday, a Thursday and a Monday team, with a league connected
    LID = "LG1"
    lg = {"league_id": LID, "name": "Refresh League", "season": "2026", "status": "in_season", "total_rosters": 2,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "bonus_rec_te": 0.5},
          "settings": {"num_teams": 2, "type": 0}}
    users = [{"user_id": f"u{i}", "display_name": f"mgr{i}", "metadata": {"team_name": f"Team {i}"}, "avatar": ""} for i in (1, 2)]
    rosters = [{"roster_id": 1, "owner_id": "u1", "co_owners": [], "players": [BIJAN, MONANGAI, PICKENS], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 3, "losses": 3, "ties": 0, "fpts": 600, "pf": 600, "streak": "1W", "division": 0}},
               {"roster_id": 2, "owner_id": "u2", "co_owners": [], "players": [], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 3, "losses": 3, "ties": 0, "fpts": 600, "pf": 600, "streak": "1L", "division": 0}}]
    lg["divisions"] = None
    def sleeper_api(route):
        path = route.request.url.split("/v1", 1)[-1].split("?")[0]
        body = lg if path == f"/league/{LID}" else users if path.endswith("/users") else rosters if path.endswith("/rosters") \
            else {"season": "2026", "week": WEEK, "season_type": "regular"} if path == "/state/nfl" else []
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    VALS = """() => [...document.querySelectorAll('#rank-body tr.player')].slice(0, 80).map(tr => tr.querySelector('.pl-name').textContent.trim() + '|' + tr.querySelector('td.rk').textContent.trim() + '|' + (tr.querySelector('.val') ? tr.querySelector('.val').textContent.trim() : ''))"""
    STATE = """() => ({ hash: location.hash, league: (JSON.parse(localStorage.getItem('spm_sleeper') || 'null') || {}).activeId,
      chip: (document.querySelector('#league-ui, .league-chip') || {}).textContent || '',
      open: document.getElementById('player-modal').open, tab: (document.querySelector('#player-body [data-pp-tab][aria-selected=true]') || {}).dataset?.ppTab || '',
      name: (document.querySelector('#player-body .pm-name, #player-body h2') || {}).textContent || '' })"""

    def open_tab(clock, sid):
        serve.update(key="wed", etag='"wed"')
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install(time=clock)
        FB.route(pg, BASE)
        pg.route("**/data/stats/2026.json*", lambda r: r.fulfill(status=200, content_type="application/json", headers={"ETag": serve["etag"]},
                                                                   body="" if r.request.method == "HEAD" else BODY[serve["key"]]))
        pg.route("https://api.sleeper.app/**", sleeper_api)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|use\.typekit\.net)/.*"), lambda r: r.abort())
        sl = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
              "leagues": [{"id": LID, "name": lg["name"], "season": "2026", "status": "in_season", "format": ""}],
              "activeId": LID, "data": {LID: {"league": lg, "users": users, "rosters": rosters, "syncedAt": 0}}, "view": "league"}
        init = f"localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(sl))});"
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2500)
        before_vals = pg.evaluate(VALS)
        practice(pg, sid, full=False)
        return pg, before_vals

    def visible_again(pg):
        pg.clock.fast_forward("06:00"); pg.wait_for_timeout(200)
        pg.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(700)
        return pg.query_selector("#update-bar")

    for label, clock, sid, team, row, before_txt, after_txt in (
        ("Sunday (ATL)", THURSDAY, BIJAN, "Atlanta Falcons", "Brian Robinson", ["LP", "Pending", "Pending"], ["LP", "DNP", "Pending"]),
        ("Thursday (CHI)", THURSDAY, MONANGAI, "Chicago Bears", None, None, None),
        ("Monday (DAL)", THURSDAY, PICKENS, "Dallas Cowboys", "George Pickens", None, None)):
        pg, vals0 = open_tab(clock, sid)
        st0 = pg.evaluate(STATE)
        ok(st0["open"] and st0["tab"] == "practice" and st0["league"] == LID, f"D. {label}: league connected, Practice Report open ({st0['league']}, {st0['tab']})")
        secs0 = {s["team"]: s for s in pg.evaluate(TABLE)}
        if before_txt:
            ok(days(secs0[team]["rows"].get(row, [])) == before_txt, f"D. {label}: before the refresh {row} {before_txt} ({days(secs0.get(team, {'rows': {}})['rows'].get(row, []))})")
        bar = visible_again(pg)
        ok(bar is None, f"D. {label}: unchanged file, no refresh offer")
        bar = visible_again(pg)
        ok(bar is None, f"D. {label}: still unchanged on the next look, still nothing")
        serve.update(key="thu", etag='"thu"')
        bar = visible_again(pg)
        ok(bar is not None and "New stats and practice reports" in bar.inner_text(), f"D. {label}: changed file, the open tab offers a refresh ({bar and bar.inner_text()!r})")
        if bar:
            quiet = pg.evaluate("() => { const b = document.getElementById('update-bar'); return [b.classList.contains('quiet'), !!b.querySelector('.btn.secondary'), !b.querySelector('.btn.primary'), !!b.querySelector('[data-ub-close]'), Math.round(b.getBoundingClientRect().height)]; }")
            ok(quiet[:4] == [True, True, True, True] and quiet[4] <= 44, f"D. {label}: the offer is quiet: neutral Refresh, a dismiss, at most 44px tall ({quiet})")
            if label.startswith("Sunday") and os.environ.get("SHOTS"): pg.screenshot(path=os.path.join(os.environ["SHOTS"], "refresh_offer.png"))
            pg.click("#update-bar [data-ub-close]"); pg.wait_for_timeout(200)
            ok(pg.query_selector("#update-bar") is None, f"D. {label}: × dismisses it")
            ok(visible_again(pg) is None and visible_again(pg) is None, f"D. {label}: the same file version never offers again after ×")
            serve["etag"] = '"thu2"'
            ok(visible_again(pg) is not None, f"D. {label}: a newer file version offers again")
        pg.click("#update-bar [data-ub-refresh]"); pg.wait_for_load_state(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(3000)
        st1 = pg.evaluate(STATE)
        ok(st1["hash"] == st0["hash"] and st1["league"] == LID, f"D. {label}: after Refresh the same tab and league ({st1['hash']}, {st1['league']})")
        ok(st1["open"] and st1["tab"] == "practice" and st1["name"] == st0["name"], f"D. {label}: the drawer reopens on the same player's Practice Report ({st1['open']}, {st1['tab']}, {st1['name']!r})")
        secs1 = {s["team"]: s for s in pg.evaluate(TABLE)}
        sec = secs1.get(team)
        if after_txt:
            ok(sec and days(sec["rows"].get(row, [])) == after_txt, f"D. {label}: the new report shows: {row} {after_txt} ({sec and days(sec['rows'].get(row, []))})")
        else:
            ok(sec and sec["head"][1] == "Latest" and all(c and c[0]["t"] != "Pending" for c in sec["rows"].values()), f"D. {label}: one Latest column, no day, no Pending ({sec and sec['head']})")
        ok(visible_again(pg) is None, f"D. {label}: no refresh offer after the refresh")
        modal_close = "() => { const m = document.getElementById('player-modal'); if (m.open) m.close(); }"
        pg.evaluate(modal_close); pg.wait_for_timeout(300)
        ok(pg.evaluate(VALS) == vals0, f"D. {label}: board ranks and values identical before and after the refresh")
        pg.close()

    # phone: Pending fits its column
    pg = page_at(THURSDAY, "wed", 390)
    practice(pg, BIJAN)
    w = pg.evaluate("() => { const b = document.querySelector('#player-body .pr-pend'); if (!b) return null; const td = b.closest('td'); return [b.getBoundingClientRect().width, td.getBoundingClientRect().width]; }")
    ok(w is not None and w[0] <= w[1], f"390px: Pending fits its day column ({w})")
    pg.close()
    ok(not errs, f"no page errors ({errs[:2]})")
    br.close()

print(f"\n{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
