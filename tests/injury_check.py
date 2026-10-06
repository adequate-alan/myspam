"""Injury-shortened games: the detection rule and the manual correction.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/injury_check.py

1. pipeline/build_stats.py shortened() on synthetic play-by-play, snap counts and injury reports (nothing real):
   - a QB hurt at halftime whose backup takes every dropback after, with only one other game → flagged
   - a receiver with low snaps but no injury evidence → not flagged
   - a player on the injury report who played his normal snaps → not flagged
   - a QB hurt with 3 minutes left (a few late snaps) → not flagged
   - a WR hurt early whose snaps fell well under his usual → flagged
2. The site with the real 2026 data: Jayden Daniels' Week 2 (hurt at halftime, Mariota finished) is flagged
   everywhere (header PPG note, Game Log tag and tooltip, production board star); with ?debug the Game Log offers
   corrections: Mark injury on another game and Clear flag on Week 2 change the counts, survive a reload, and a
   signed-in editor publishes them to data/injury_overrides.json (GitHub mocked).
"""
import functools, gzip, http.server, io, json, os, re, socketserver, sys, tempfile, threading
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import build_stats as B

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

# ---------- 1. the rule on synthetic data ----------
tmp = tempfile.mkdtemp()
S = 2030   # a made-up season so nothing real is involved
def secs(minute): return (60 - minute) * 60
pbp = []
def play(week, tm, minute, qb, desc="pass"):
    pbp.append({"season_type": "REG", "week": week, "posteam": tm, "qb_dropback": 1, "passer_player_id": qb, "rusher_player_id": None,
                "game_seconds_remaining": secs(minute), "desc": desc})
# team AAA: QB1 starts week 2, hurt at 30:00, QB2 takes every dropback after (week 1 normal)
for m in range(1, 59, 3): play(1, "AAA", m, "Q1")
for m in range(1, 30, 3): play(2, "AAA", m, "Q1")
pbp.append({"season_type": "REG", "week": 2, "posteam": "AAA", "qb_dropback": 0, "passer_player_id": None, "rusher_player_id": None,
            "game_seconds_remaining": secs(30), "desc": "(:03) 1-Q.One pass incomplete. AAA-1-Q.One was injured during the play."})
for m in range(31, 59, 3): play(2, "AAA", m, "Q2")
# team BBB: QB3 hurt with 3 minutes left in week 2, backup kneels out the game
for w in (1, 2, 3):
    for m in range(1, 58 if w == 2 else 59, 3): play(w, "BBB", m, "Q3")
pbp.append({"season_type": "REG", "week": 2, "posteam": "BBB", "qb_dropback": 0, "passer_player_id": None, "rusher_player_id": None,
            "game_seconds_remaining": secs(57), "desc": "(3:00) 3-Q.Three sacked. BBB-3-Q.Three was injured during the play."})
for m in (57.5, 58, 58.5, 59, 59.5): play(2, "BBB", m, "Q4")
# WR W1 hurt early in week 3 (pbp), W2 low snaps in week 2 with no evidence, W3 listed on the report but full snaps
pbp.append({"season_type": "REG", "week": 3, "posteam": "AAA", "qb_dropback": 0, "passer_player_id": None, "rusher_player_id": None,
            "game_seconds_remaining": secs(10), "desc": "(5:00) 1-Q.One pass short to 11-W.One. AAA-11-W.One was injured during the play."})
pd.DataFrame(pbp).to_csv(os.path.join(tmp, f"pbp_{S}.csv.gz"), index=False, compression="gzip")
snaps = []
def snap(season, week, pfr, pct): snaps.append({"season": season, "game_type": "REG", "week": week, "pfr_player_id": pfr, "offense_pct": pct, "offense_snaps": int(pct * 70)})
snap(S, 1, "q1", 1.0); snap(S, 2, "q1", 0.52)
for w, v in ((1, 1.0), (2, 0.96), (3, 1.0)): snap(S, w, "q3", v)
for w, v in ((1, 0.9), (2, 0.88), (3, 0.2)): snap(S, w, "w1", v)
for w, v in ((1, 0.85), (2, 0.3), (3, 0.86)): snap(S, w, "w2", v)
for w, v in ((1, 0.8), (2, 0.82), (3, 0.81)): snap(S, w, "w3", v)
pd.DataFrame(snaps).to_csv(os.path.join(tmp, f"snaps_{S}.csv"), index=False)
pd.DataFrame(snaps[:0] + [{"season": S - 1, "game_type": "REG", "week": 1, "pfr_player_id": "q1", "offense_pct": 1.0, "offense_snaps": 70}]).to_csv(os.path.join(tmp, f"snaps_{S-1}.csv"), index=False)
inj = [{"season_type": "REG", "week": 3, "gsis_id": "G1", "report_primary_injury": "Elbow", "practice_primary_injury": "Elbow"},
       {"season_type": "REG", "week": 2, "gsis_id": "G6", "report_primary_injury": "Ankle", "practice_primary_injury": "Ankle"},
       {"season_type": "REG", "week": 3, "gsis_id": "G6", "report_primary_injury": "Ankle", "practice_primary_injury": "Ankle"}]
pd.DataFrame(inj).to_csv(os.path.join(tmp, f"inj_{S}.csv"), index=False)
people = {"G1": ("Q.One", "AAA", "QB", "q1", [1, 2]), "G3": ("Q.Three", "BBB", "QB", "q3", [1, 2, 3]),
          "G4": ("W.One", "AAA", "WR", "w1", [1, 2, 3]), "G5": ("W.Two", "AAA", "WR", "w2", [1, 2, 3]), "G6": ("W.Three", "AAA", "WR", "w3", [1, 2, 3])}
stats = pd.DataFrame([{"player_id": g, "player_name": n, "team": t, "position": pos, "week": w} for g, (n, t, pos, _, ws) in people.items() for w in ws])
ids = {g: "S" + g for g in people}; pfr = {g: v[3] for g, v in people.items()}
out = B.shortened(S, stats, ids, pfr, os.path.join(tmp, "pbp_{}.csv.gz"), os.path.join(tmp, "snaps_{}.csv"), os.path.join(tmp, "inj_{}.csv"))
weeks = {sid: [r[0] for r in rows] for sid, rows in out.items()}
ok(weeks.get("SG1") == [2] and out["SG1"][0][4] and 29 <= out["SG1"][0][4] <= 31, f"QB hurt at halftime, backup finished, one other game: flagged {out.get('SG1')}")
ok("SG5" not in out, "Low snaps without injury evidence: not flagged")
ok("SG6" not in out, "On the injury report but played his normal snaps: not flagged")
ok("SG3" not in out, "QB hurt with 3 minutes left (a few late snaps): not flagged")
ok(weeks.get("SG4") == [3], f"WR hurt early, snaps well under his usual: flagged {out.get('SG4')}")

# ---------- 2. the site ----------
DANIELS = "11566"
stats26 = json.load(open(os.path.join(ROOT, "data/stats/2026.json")))
ok(any(r[0] == 2 for r in stats26["short"].get(DANIELS, [])), f"2026 data: Jayden Daniels Week 2 is in the injury-shortened list {stats26['short'].get(DANIELS)}")

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

put = []
def github(route):
    u, m = route.request.url, route.request.method
    if m == "PUT": put.append(json.loads(route.request.post_data)); return route.fulfill(status=200, content_type="application/json", body="{}")
    if "/contents/data/injury_overrides.json" in u: return route.fulfill(status=404, content_type="application/json", body='{"message":"Not Found"}')
    if u.endswith("/user"): return route.fulfill(status=200, content_type="application/json", body='{"login":"tester"}')
    return route.fulfill(status=200, content_type="application/json", body='{"permissions":{"push":true}}')

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(q="", token=False):
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com))/.*"), lambda r: r.abort())
        pg.route("https://api.github.com/**", github)
        init = "localStorage.clear();" + ("localStorage.setItem('spm_editor_token','test-token');" if token else "")
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(f"http://127.0.0.1:{port}/{q}#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1200)
        return pg
    def open_daniels(pg):
        pg.evaluate(f"document.querySelector('#rank-body [data-player=\"{DANIELS}\"]').click()"); pg.wait_for_timeout(1300)
    def game_log(pg):
        pg.locator("#player-modal button", has_text=re.compile(r"^Game Log$")).first.click(); pg.wait_for_timeout(500)
    def row(pg, w):
        return pg.locator("#player-modal tr.gl-row").nth(w - 1)

    pg = page()
    open_daniels(pg)
    head = pg.inner_text("#player-modal")
    ok("1 injury-shortened" in head, "Daniels' header PPG says '1 injury-shortened'")
    game_log(pg)
    tag = row(pg, 2).locator(".inj-tag")
    tip = tag.get_attribute("title") if tag.count() else ""
    ok(tag.count() == 1 and "Elbow" in tip and "halftime" in tip, f"Game Log Week 2: Left early · {tip}")
    ok(row(pg, 1).locator(".inj-tag").count() == 0, "Week 1 (full game) isn't flagged")
    ok(pg.locator("#player-modal .inj-ov").count() == 0, "No correction buttons without the editor or ?debug")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('rk-sort'); s.value = 'ppg'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(400)
    pg.evaluate("() => { const s = document.getElementById('rk-min'); s.value = '0'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(400)
    st = pg.locator(f"#rank-body tr.player:has([data-player='{DANIELS}']) .pnum .inj-star")
    ok(st.count() == 1, "Production board: Daniels' PPG is starred")
    pg.close()

    # corrections in debug mode (this browser only)
    pg = page("?debug=1")
    open_daniels(pg); game_log(pg)
    ok(row(pg, 1).locator(".inj-ov").inner_text() == "Mark injury" and row(pg, 2).locator(".inj-ov").inner_text() == "Clear flag", "?debug: Mark injury / Clear flag on each played game")
    row(pg, 1).locator(".inj-ov").click(); pg.wait_for_timeout(500)
    ok(row(pg, 1).locator(".inj-tag").count() == 1 and "marked by SPAM" in row(pg, 1).locator(".inj-tag").get_attribute("title"), "Mark injury: Week 1 now Left early (marked by SPAM)")
    ok("2 injury-shortened" in pg.inner_text("#player-modal tfoot"), "Game Log footer counts 2 injury-shortened games")
    row(pg, 2).locator(".inj-ov").click(); pg.wait_for_timeout(500)
    ok(row(pg, 2).locator(".inj-tag").count() == 0, "Clear flag: Week 2 no longer flagged")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1200)
    open_daniels(pg); game_log(pg)
    ok(row(pg, 1).locator(".inj-tag").count() == 1 and row(pg, 2).locator(".inj-tag").count() == 0, "Corrections survive a reload (this browser)")
    row(pg, 2).locator(".inj-ov").click(); pg.wait_for_timeout(400); row(pg, 1).locator(".inj-ov").click(); pg.wait_for_timeout(400)
    ok(row(pg, 2).locator(".inj-tag").count() == 1 and row(pg, 1).locator(".inj-tag").count() == 0, "Undoing both restores the detected flags")
    pg.close()

    # a signed-in editor publishes the correction (GitHub mocked)
    pg = page(token=True)
    pg.wait_for_timeout(800)
    open_daniels(pg); game_log(pg)
    row(pg, 1).locator(".inj-ov").click(); pg.wait_for_timeout(1200)
    body = json.loads(__import__("base64").b64decode(put[-1]["content"]).decode()) if put else {}
    ok(put and put[-1]["message"].startswith("Injury-shortened correction") and body.get("seasons", {}).get("2026", {}).get(DANIELS, {}).get("1", {}).get("short") is True,
       f"Signed-in editor: published data/injury_overrides.json ({put[-1]['message'] if put else 'no PUT'})")
    pg.close()
    ok(not errs, f"No page errors {errs[:3]}")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll injury checks passed.")
sys.exit(1 if failures else 0)
