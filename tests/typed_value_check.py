"""A value you type stays his value when somebody else moves (Alan, Nov 18).

Found while verifying free editing on both boards: D'Andre Swift typed at 4,945, another RB moved past him before
saving, and Swift read 4,836 with no notice. A typed value was anchored at the curve of the spot he held when it was
typed, and another player moving past him shifts that spot by one. Now the typed value is kept exactly while he doesn't
move himself; the mover still follows the curve; a typed value that can't be kept (no whole number left between his
neighbours) or whose player changes tier is said in the notice, never silent.

The page's real editor and publishing code runs against an in-memory GitHub repository (tests/gh_mock.py) holding this
checkout's files. Players are picked from the board as it is, so a rankings publish never breaks the suite.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/typed_value_check.py

On AM SF PPR TE+ and then on AM PPR, each on its own:
1. Type a value that fits: only he changes.
2. Another player at his position moves past him inside his tier: the typed value is exact, only the mover's value
   changes, and the mover is repriced (he follows the curve). Moved back: the board after step 1 exactly. The value
   typed back: the published board exactly, nothing unsaved (undo).
3. Again, then a player from a lower tier moves past him at the position (across tiers) and a player at another
   position moves past him overall: the typed value is exact after each.
4. Save (no token: saved in this browser), reload: the same board. A further move and Cancel: the saved board.
5. Publish: one commit; the board's block carries the typed value and the moves; the other board's block and files are
   byte-identical; his history entry is a value edit at the typed value. Reload: the same board, nothing pending.
6. Conflict: his value typed one point under the player ahead, then a player moved between them: no whole number is
   left, his value steps a point and the notice names him and his typed value. Cancel restores the published board.
7. He moves himself after typing: his value follows the curve from the typed value (the mover is repriced, as before).
8. A tier added above his tier (tiers renumber, position tiers only): the typed value is exact.
No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rd(p): return open(os.path.join(ROOT, p), "rb").read()
FILES = {"index.html": rd("index.html"), "data/rank_history.json": rd("data/rank_history.json"),
         "data/injury_overrides.json": rd("data/injury_overrides.json"), "data/boards/ppr/rank_history.json": rd("data/boards/ppr/rank_history.json")}
for d in ("data/rank_snapshots", "data/boards/ppr/rank_snapshots"):
    for f in os.listdir(os.path.join(ROOT, d)): FILES[f"{d}/{f}"] = rd(f"{d}/{f}")

def block_re(name): return re.compile(rb"(const " + name.encode() + rb" = `\n)([\s\S]*?)(\n`;)")
RX = {"sf-tep": block_re("RANKINGS_CSV"), "ppr": block_re("RANKINGS_CSV_PPR")}
HIST = {"sf-tep": "data/rank_history.json", "ppr": "data/boards/ppr/rank_history.json"}
OWN = {"sf-tep": lambda p: p == "data/rank_history.json" or p.startswith("data/rank_snapshots/"), "ppr": lambda p: p.startswith("data/boards/ppr/")}
LABEL = {"sf-tep": "AM SF PPR TE+", "ppr": "AM PPR"}
def block(html, rx): return rx.search(html)[2].decode()
def table(text):
    rows = list(csv.reader(io.StringIO(text))); h = rows[0]
    return {r[h.index("sleeper_id")]: {k: r[h.index(k)] for k in ("rank", "pos_rank", "tier", "value")} for r in rows[1:]}

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

BOARD = "() => SPM.edit.board().map(p => ({ id: p.id, sid: String(p.sid), name: p.name, pos: p.pos, rank: p.rank, posNum: p.posNum, tier: String(p.tier), value: Math.round(p.value), source: p.source }))"

repo = Repo(dict(FILES))
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.github.com/**", repo.handle)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
    pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|rank_snapshots/|boards/ppr/).*"), lambda r: (lambda b: r.fulfill(status=200, content_type="application/json", body=b) if b is not None else r.fulfill(status=404, body=""))(
        repo.read(r.request.url.split(BASE + "/")[1].split("?")[0])))
    pg.add_init_script("window.__SPM_APPLY_OFF = true;")   # the plain publish: no "both formats" prompt (tests/board_apply_check.py covers it)
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")

    def load():
        pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
        if pg.locator("#league-controls [data-view=base]").is_visible(): pg.click("#league-controls [data-view=base]"); pg.wait_for_timeout(300)
    def board(): return sorted(pg.evaluate(BOARD), key=lambda r: r["rank"])
    def by_sid(b): return {r["sid"]: r for r in b}
    def state(b): return [(r["sid"], r["rank"], r["posNum"], r["tier"], r["value"], r["source"]) for r in b]
    def unsaved(): return pg.inner_text("#eb-count").strip()
    def toast(): return pg.inner_text("#toast")
    def clear_toast(): pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    def edit(fn, *a):
        clear_toast(); pg.evaluate("([fn, a]) => SPM.edit[fn](...a)", [fn, list(a)]); pg.wait_for_timeout(350)
    def cur(sid): return by_sid(board())[sid]
    def wait_toast(rx):
        pg.wait_for_function("rx => new RegExp(rx).test(document.getElementById('toast').textContent)", arg=rx, timeout=20000); pg.wait_for_timeout(300); return toast()

    def scenario(bid):
        L = LABEL[bid]; other = "ppr" if bid == "sf-tep" else "sf-tep"
        pg.evaluate("() => localStorage.removeItem('spm_editor_token')"); pg.reload(); load()
        ok(pg.evaluate("() => SPM.boards().active") == bid, f"{L}: this page edits it")
        start = board(); S = by_sid(start)
        tag = lambda r: int(r["tier"]) >= 90
        rbs = sorted([r for r in start if r["pos"] == "RB" and not tag(r)], key=lambda r: r["posNum"])
        ov = {r["rank"]: r for r in start}
        def pick():
            for i in range(6, len(rbs) - 6):
                x, y = rbs[i], rbs[i + 1]
                up, dn = ov.get(x["rank"] - 1), ov.get(x["rank"] + 1)
                if not up or not dn or x["value"] < 600 or y["tier"] != x["tier"] or rbs[i - 1]["tier"] != x["tier"]: continue
                if up["value"] - x["value"] < 8 or x["value"] - dn["value"] < 8 or rbs[i - 1]["value"] - x["value"] < 8 or x["value"] - y["value"] < 4: continue
                z = next((r for r in rbs[i + 2:] if r["tier"] != x["tier"]), None)
                w = next((r for r in start if r["rank"] > x["rank"] + 3 and r["pos"] not in ("RB",) and not tag(r) and r["value"] > 0), None)
                if z and w and z["value"] >= 400: return x, y, z, w
        X, Y, Z, W = pick()
        v = X["value"] + 3
        print(f"     {L}: typed {X['name']} RB{X['posNum']} {X['value']} → {v}; movers {Y['name']} (same tier), {Z['name']} (Tier {Z['tier']} → {X['tier']}), {W['name']} ({W['pos']})")

        # 1. the typed value
        edit("setValue", X["id"], v); b1 = board()
        d = [r["sid"] for r in b1 if state([r]) != state([S[r["sid"]]])]
        ok(cur(X["sid"])["value"] == v and [s for s in d if s != X["sid"]] == [], f"{L}: the typed value {v} is kept and nobody else changes {d[:4]}")

        # 2. another player at his position moves past him, inside his tier; then everything undone
        edit("movePlayer", Y["id"], X["posNum"]); b2 = by_sid(board()); t2 = toast()
        ok(b2[X["sid"]]["value"] == v, f"{L}: {Y['name']} moved past him: the typed value stays {v} (reads {b2[X['sid']]['value']})")
        ok(b2[X["sid"]]["posNum"] == X["posNum"] + 1 and b2[Y["sid"]]["posNum"] == X["posNum"], f"{L}: …with the two position ranks swapped (RB{b2[Y['sid']]['posNum']}, RB{b2[X['sid']]['posNum']})")
        chg = [s for s, r in b2.items() if r["value"] != by_sid(b1)[s]["value"]]
        ok(chg == [Y["sid"]], f"{L}: only the mover's value changes: he follows the curve ({Y['value']} → {b2[Y['sid']]['value']}) {chg[:4]}")
        ok("typed value" not in t2, f"{L}: no warning when the typed value is kept ({t2[:70]!r})")
        edit("movePlayer", Y["id"], Y["posNum"])
        ok(state(board()) == state(b1), f"{L}: moved back: the board after the value edit exactly")
        edit("setValue", X["id"], X["value"])
        ok(state(board()) == state(start) and unsaved() == "All saved", f"{L}: the value typed back: the published board exactly, nothing unsaved ({unsaved()!r})")

        # 3. again, across tiers and across positions
        edit("setValue", X["id"], v); edit("movePlayer", Y["id"], X["posNum"])
        edit("movePlayer", Z["id"], cur(X["sid"])["posNum"]); bz = by_sid(board())
        ok(bz[X["sid"]]["value"] == v and bz[Z["sid"]]["posNum"] < bz[X["sid"]]["posNum"], f"{L}: {Z['name']} moved up past him from a lower tier (now Tier {bz[Z['sid']]['tier']}): the typed value stays {v} (reads {bz[X['sid']]['value']})")
        edit("moveOverall", W["id"], cur(X["sid"])["rank"]); bw = by_sid(board())
        ok(bw[X["sid"]]["value"] == v and bw[W["sid"]]["rank"] < bw[X["sid"]]["rank"], f"{L}: {W['name']} ({W['pos']}) moved past him overall: the typed value stays {v} (reads {bw[X['sid']]['value']})")
        final = board()
        others = [s for s, r in by_sid(final).items() if s not in (X["sid"], Y["sid"], Z["sid"], W["sid"]) and abs(r["value"] - S[s]["value"]) > 0 and not (abs(r["value"] - S[s]["value"]) <= 5 and r["value"] < 1000)]
        ok(not others, f"{L}: nobody but the typed player and the three movers changed value {others[:4]}")

        # 4. save in this browser, reload, cancel
        clear_toast(); pg.click("#eb-save"); msg = wait_toast("Saved in this browser")
        ok("Saved in this browser" in msg, f"{L}: saved in this browser")
        pg.reload(); load()
        ok(state(board()) == state(final), f"{L}: a reload shows the saved board, the typed value {cur(X['sid'])['value']}")
        edit("movePlayer", Y["id"], cur(Y["sid"])["posNum"] + 3)
        ok(cur(X["sid"])["value"] == v, f"{L}: a move after the reload keeps the typed value too")
        pg.click("#eb-cancel"); pg.wait_for_timeout(500)
        ok(state(board()) == state(final), f"{L}: Cancel returns to the saved board")

        # 5. publish
        pg.evaluate("() => localStorage.setItem('spm_editor_token', 'test-token')"); pg.reload(); load()
        ok(state(board()) == state(final), f"{L}: signed in after another reload: still the saved board")
        head0 = repo.head; before = repo.read("index.html"); n0 = len(repo.log())
        clear_toast(); pg.click("#eb-publish"); msg = wait_toast("Publish|Already live")
        after = repo.read("index.html"); new = repo.log()[n0:]
        ok("Published and confirmed" in msg and len(new) == 1, f"{L}: published in one commit ({[m.splitlines()[0] for m in new]})")
        pa = table(block(after, RX[bid]))
        ok(all(pa[r["sid"]] == {"rank": str(r["rank"]), "pos_rank": str(r["posNum"]), "tier": r["tier"], "value": str(r["value"])} for r in final), f"{L}: the published block is the edited board")
        ok(pa[X["sid"]]["value"] == str(v), f"{L}: the typed value is published ({pa[X['sid']]['value']})")
        ok(block(before, RX[other]) == block(after, RX[other]) and before[:RX[bid].search(before).start(2)] == after[:RX[bid].search(after).start(2)], f"{L}: {LABEL[other]}'s block and the code are byte-identical")
        ch = [f for f in set(FILES) | set(repo.files()) if repo.read(f, head0) != repo.read(f)] if hasattr(repo, "files") else [f for f in FILES if repo.read(f, head0) != repo.read(f)]
        ok(not [f for f in ch if OWN[other](f)], f"{L}: {LABEL[other]}'s history and snapshots untouched")
        h = json.loads(repo.read(HIST[bid])); e = h["players"][X["sid"]][-1]
        ok(e[4] == v and "V" in str(e[6]), f"{L}: his history entry is a value edit at {v} ({e[1:]})")
        pg.reload(); load()
        pub = board()
        ok(state(pub) == state(final) and unsaved() == "All saved", f"{L}: a reload shows the published board, nothing pending ({unsaved()!r})")

        # 6. a typed value that can't be kept is said out loud
        P = by_sid(pub); xr = P[X["sid"]]; up = next(r for r in pub if r["rank"] == xr["rank"] - 1)
        m = next(r for r in pub if r["rank"] > xr["rank"] + 4 and r["pos"] != xr["pos"] and not tag(r) and r["value"] > 0)
        edit("setValue", X["id"], up["value"] - 1)
        ok(cur(X["sid"])["value"] == up["value"] - 1, f"{L}: typed one point under {up['name']} ({up['value'] - 1})")
        edit("moveOverall", m["id"], xr["rank"]); t6 = toast(); c6 = by_sid(board())
        ok(c6[m["sid"]]["rank"] == xr["rank"] and c6[X["sid"]]["value"] != up["value"] - 1, f"{L}: {m['name']} moved between them: no whole number left, his value steps to {c6[X['sid']]['value']}")
        ok(X["name"] in t6 and "typed value" in t6 and f"{up['value'] - 1:,}" in t6, f"{L}: …and the notice says so ({t6[-110:]!r})")
        vals = [r["value"] for r in board()]
        ok(all(a > b or (a == 0 and b == 0) for a, b in zip(vals, vals[1:])), f"{L}: values still run strictly down the board")
        pg.click("#eb-cancel"); pg.wait_for_timeout(500)
        ok(state(board()) == state(pub) and unsaved() == "All saved", f"{L}: Cancel restores the published board")

        # 7. he moves himself after typing: his value follows the curve, as for any mover
        # (a value that fits between his neighbours on the published board, whatever the movers left around him)
        dn = next(r for r in pub if r["rank"] == xr["rank"] + 1)
        t7 = xr["value"] + 1 if up["value"] - xr["value"] > 1 else xr["value"] - 1
        assert dn["value"] < t7 < up["value"], (dn["value"], t7, up["value"])
        edit("setValue", X["id"], t7)
        ok(cur(X["sid"])["value"] == t7, f"{L}: typed {t7} on the published board")
        edit("movePlayer", X["id"], xr["posNum"] + 3); c7 = cur(X["sid"])
        ok(c7["posNum"] == xr["posNum"] + 3 and c7["value"] < t7, f"{L}: moved down three spots himself, his value follows the curve ({t7} → {c7['value']})")
        edit("movePlayer", X["id"], xr["posNum"])
        ok(cur(X["sid"])["value"] == t7, f"{L}: …and moved back, the typed value is back exactly")
        pg.click("#eb-cancel"); pg.wait_for_timeout(500)

        # 8. a tier added above his (position tiers renumber)
        if bid == "sf-tep":
            edit("setValue", X["id"], t7); edit("tierAction", "above", "RB", int(xr["tier"])); c8 = cur(X["sid"])
            ok(c8["value"] == t7 and int(c8["tier"]) == int(xr["tier"]) + 1, f"{L}: an empty tier added above his: the typed value stays {t7} (Tier {xr['tier']} → {c8['tier']})")
            pg.click("#eb-cancel"); pg.wait_for_timeout(500)
            ok(state(board()) == state(pub), f"{L}: Cancel restores the published board")

    pg.goto(BASE + "/#rankings"); load()
    scenario("sf-tep")
    pg.evaluate("bid => { const s = document.getElementById('rk-board'); s.value = bid; s.dispatchEvent(new Event('change', { bubbles: true })); }", "ppr"); pg.wait_for_timeout(700)
    with pg.expect_navigation(): pg.click("#ed-switch")
    load()
    scenario("ppr")
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
