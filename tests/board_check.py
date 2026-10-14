"""Ranking sets (Alan, Oct 14): AM SF PPR TE+ and AM PPR. Synthetic leagues only.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/board_check.py

Checks:
1. SPM.boardCheck() in the page: each board in its own native format gives exactly its saved values, ranks 1..N and
   values strictly down each board, tiers in one piece, the same player pool, the QB format picks the board in every
   tested format (1QB -> AM PPR, Superflex / 2QB -> AM SF PPR TE+), adjustments start from the board's own format
   (TE premium and PPR applied once), no format-created cliffs from AM PPR's overall tiers, provisional players marked,
   and pricing a league never changes a board.
2. A 1QB league (10-team, Half PPR) is valued on AM PPR; a Superflex league (12-team, TE premium) on AM SF PPR TE+.
3. The Rankings tab's board picker is separate: showing the other board on the AM Board view never changes the league's
   values, a board that isn't the edited one hides the editor and offers "Edit <board>", the choice persists across a reload.
4. The calculator names the board; a 1QB trade from before AM PPR existed reads "No AM PPR value available then";
   the drawer opened from the AM PPR view names AM PPR; nothing is written to AM PPR storage keys; no page errors.
"""
import os, re, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve(), freeze()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def connect(pg, lid):
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator(f"#sd-leagues [data-league='{lid}']").click(); pg.wait_for_timeout(1800)

def pick_board(pg, bid):
    pg.evaluate("bid => { const s = document.getElementById('rk-board'); s.value = bid; s.dispatchEvent(new Event('change', { bubbles: true })); }", bid)
    pg.wait_for_timeout(700)

def first_row(pg):
    return pg.evaluate("""() => { const tr = document.querySelector('#rank-body tr.player'); if (!tr) return null;
      return { name: tr.querySelector('.pl-name').textContent.trim(), value: Number((tr.querySelector('.val .num, .val .num-btn') || {}).textContent.replace(/\\D/g, '')),
               rows: document.querySelectorAll('#rank-body tr.player').length }; }""")

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    freeze(pg, FRIDAY)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)

    # 1. the page's own self-test
    for c in pg.evaluate("() => SPM.boardCheck()"):
        ok(c["pass"], "boardCheck: " + c["check"] + " " + json.dumps(c["values"])[:180])
    reg = pg.evaluate("() => SPM.boards()")
    ok([b["id"] for b in reg["boards"]] == ["sf-tep", "ppr"] and reg["active"] == "sf-tep", f"Registry: {[b['id'] for b in reg['boards']]}, active {reg['active']}")
    auto = pg.evaluate("""() => [['1', 0], ['1', 1], ['sf', 0], ['sf', 1], ['2', 0.5]].map(([qb, tep]) => SPM.boards({ qb, tep }).auto)""")
    ok(auto == ["ppr", "ppr", "sf-tep", "sf-tep", "sf-tep"], f"Custom formats pick the board by QB format: {auto}")

    # 2. a 1QB league is valued on AM PPR
    connect(pg, "L2")
    b2 = pg.evaluate("() => ({ boards: SPM.boards(), lv: SPM.leagueValues() })")
    ok(b2["boards"]["league"] == "ppr" and b2["lv"]["board"] == "ppr", f"1QB league (Beta) is valued on AM PPR: {b2['boards']['league']} / {b2['lv']['board']}")
    lv2 = b2["lv"]["adj"]

    # 3. the Rankings board picker
    pg.click("#tab-rankings"); pg.wait_for_timeout(400)
    pg.click("#league-controls [data-view=base]"); pg.wait_for_timeout(700)
    ok(pg.locator("#rk-board-lab").is_visible(), "The AM Board view offers a board picker")
    ok(pg.evaluate("() => document.getElementById('rk-board').value") == "ppr", "It starts on the league's board (AM PPR)")
    fr = first_row(pg)
    ok(fr and fr["rows"] == 260, f"AM PPR lists 260 players: {fr}")
    ok(pg.locator("#editor-bar").is_hidden(), "AM PPR isn't the edited board: no editor bar")
    ok(pg.locator("#ed-switch").is_visible() and "Edit AM PPR" in pg.inner_text("#ed-switch"), "It offers Edit AM PPR instead")
    ok(pg.locator("#rank-body .prov").count() > 0, f"Provisional players are tagged on the board ({pg.locator('#rank-body .prov').count()} visible)")
    pick_board(pg, "sf-tep")
    ok(pg.evaluate("() => SPM.leagueValues().adj") == lv2 and pg.evaluate("() => SPM.leagueValues().board") == "ppr",
       "Showing AM SF PPR TE+ on the Rankings tab leaves the league's AM PPR values unchanged")
    ok(pg.locator("#editor-bar").is_visible() and pg.locator("#ed-switch-wrap").is_hidden(), "The edited board shows the editor bar again")
    sf_first = first_row(pg)
    ok(sf_first and sf_first["rows"] != 0, f"AM SF PPR TE+ board renders: {sf_first}")
    pick_board(pg, "ppr")
    pg.reload(); pg.wait_for_timeout(4500)
    pg.click("#tab-rankings"); pg.wait_for_timeout(400)
    ok(pg.evaluate("() => SPM.leagueValues().board") == "ppr" and pg.evaluate("() => SPM.leagueValues().adj") == lv2, "After a reload the 1QB league is still on AM PPR with the same values")

    # drawer from the AM PPR view
    pg.click("#league-controls [data-view=base]"); pg.wait_for_timeout(600)
    pick_board(pg, "ppr")
    pg.locator("#rank-body tr.player .pl-name").first.click(); pg.wait_for_timeout(900)
    ok("AM PPR" in pg.inner_text("dialog.pm"), "The drawer opened from the AM PPR view names AM PPR")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # 4. calculator and trade history
    pg.click("#tab-trade"); pg.wait_for_timeout(700)
    ok("AM PPR" in pg.inner_text("#tc-badge"), "The calculator says its values come from AM PPR")
    pg.click("#tab-league"); pg.wait_for_timeout(400)
    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2000)
    pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
    while pg.locator("[data-tx-older]").count(): pg.click("[data-tx-older]"); pg.wait_for_timeout(300)
    txt = pg.inner_text("#league-body") if pg.locator("#league-body").count() else pg.inner_text("body")
    ok("No AM PPR value" in txt, "A 1QB trade from before AM PPR existed reads No AM PPR value then")

    # the Superflex league stays on AM SF PPR TE+
    connect(pg, "L1")
    ok(pg.evaluate("() => SPM.leagueValues().board") == "sf-tep", "Superflex league (Alpha) is valued on AM SF PPR TE+")
    pg.click("#tab-league"); pg.wait_for_timeout(400)
    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2000)
    txt1 = pg.inner_text("body")
    ok("No AM PPR value" not in txt1, "Superflex trades never mention AM PPR")
    keys = pg.evaluate("() => Object.keys(localStorage)")
    ok(not [k for k in keys if k.endswith(":ppr")], f"Nothing is written to AM PPR storage keys: {[k for k in keys if ':ppr' in k]}")
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
