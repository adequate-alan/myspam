"""Reversible editor across Save, Publish and reloads (Alan, Oct 12, on values as state). tests/reversal_check.py proves undone moves restore
the board inside one editing session; this checks the same rule holds when the session is interrupted, through the real
editor UI only (arrows, typed values, tier header actions, Save, Cancel, reloads; no test hook), against an in-memory
GitHub repository (tests/gh_mock.py), so nothing reaches GitHub or the files on disk.

1. Deliberate edits (a value edit, a deleted tier whose players join the tier above, an Auto player moved) are saved and
   published, and come back exactly after a reload: nothing pending, the published board on screen.
2. A new session on the reloaded page: moves across tier boundaries (All view and a position tab), an Auto player and the
   published player moved and moved back, each restore the published board exactly (nothing unsaved, same ranks, tiers,
   values on screen); the deliberate edits stay.
3. Moves then Cancel bring back the published board, and moves made after a Cancel still undo exactly.
4. Saved in this browser but not published (no token), then reloaded: undoing those moves after the reload and saving
   leaves no browser edits at all (the board equals the live one again, the Auto player is Auto again, every tier back,
   every stored value back), and the editor's bookkeeping and touched players are cleared with them.
5. Visitors' pages don't expose the editor's test hook (SPM.edit).

Run from the repo root:  python3 tests/reversal_persist_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, hashlib, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISK_SHA = hashlib.sha256(open(os.path.join(ROOT, "index.html"), "rb").read()).hexdigest()
FILES = {"index.html": open(os.path.join(ROOT, "index.html"), "rb").read(),
         "data/rank_history.json": open(os.path.join(ROOT, "data/rank_history.json"), "rb").read(),
         "data/injury_overrides.json": open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read(),
         **{f"data/rank_snapshots/{f}": open(os.path.join(ROOT, "data/rank_snapshots", f), "rb").read() for f in os.listdir(os.path.join(ROOT, "data/rank_snapshots"))}}
CSV_RE = re.compile(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;")
def board_csv(html): return CSV_RE.search(html if isinstance(html, str) else html.decode()).group(1)
def rows_of(text):
    r = list(csv.DictReader(io.StringIO(text))); return {(x["player"], x["pos"]): x for x in r}

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

# the board as shown: every player's row in the All view (id, name, rank by position in the list, tier tag, value)
BOARD = """() => [...document.querySelectorAll('#rank-body tr.player')].map((tr, i) => [tr.dataset.id, tr.querySelector('.pl-name').textContent.trim(),
  i + 1, (tr.querySelector('.tier-tag') || {}).textContent || '', (tr.querySelector('.val .num, .val .num-btn') || {}).textContent || ''].join('|'))"""

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    repo = Repo(dict(FILES))

    def open_page(ctx, token=True):
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history|injury_overrides)\.json.*"), lambda r: r.fulfill(status=200, content_type="application/json",
                 body=repo.read("data/" + r.request.url.split("/data/")[1].split("?")[0])))
        if token: pg.add_init_script("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        return pg
    def tab(pg, pos):
        pg.click(f"#pos-chips button:has-text('{pos}')"); pg.wait_for_timeout(300)
    def board(pg):
        tab(pg, "All"); return pg.evaluate(BOARD)
    def row(pg, name): return pg.locator("#rank-body tr.player", has_text=name).first
    def arrow(pg, name, d, n=1):
        for _ in range(n):
            r = row(pg, name); r.evaluate("el => el.scrollIntoView({ block: 'center' })")   # clear of the sticky header
            r.locator(f'.arrow[data-dir="{d}"]').click(force=True); pg.wait_for_timeout(150)
    def status(pg): return pg.inner_text("#eb-count").strip()
    def save(pg):
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
        pg.wait_for_timeout(400); return pg.inner_text("#toast")
    def local(pg): return pg.evaluate("() => [JSON.parse(localStorage.getItem('spm_local_edits') || '{}'), localStorage.getItem('spm_edit_session'), localStorage.getItem('spm_value_touch')]")
    def by_rank(text): return sorted(rows_of(text).values(), key=lambda x: int(x["rank"]))

    pub0 = board_csv(repo.read("index.html")); R0 = by_rank(pub0)
    # a Manual player near #40 with room for a value edit that fits his spot (values as state: it must stay under the player ahead)
    typed_p = next(x for i, x in enumerate(R0) if int(x["rank"]) >= 40 and x["source"] == "manual" and float(R0[i - 1]["value"]) - float(x["value"]) >= 10)
    typed_v = round(float(typed_p["value"]) + (float(R0[R0.index(typed_p) - 1]["value"]) - float(typed_p["value"])) / 2)
    auto1, auto2, auto3 = [next(x for x in R0 if int(x["rank"]) == k) for k in (200, 210, 225)]
    wr = [x for x in R0 if x["pos"] == "WR"]
    del_tier = next(x["tier"] for x in wr if int(x["tier"]) >= 6)   # a mid WR tier, deleted into the tier above

    # 1. deliberate edits, saved and published, then reloaded
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    pg = open_page(ctx)
    ok(not pg.evaluate("() => !!(window.SPM && SPM.edit)"), "Visitors' pages don't expose the editor's test hook (SPM.edit)")
    tab(pg, "All")
    r = row(pg, typed_p["player"]); r.evaluate("el => el.scrollIntoView({ block: 'center' })")
    r.locator(".num-btn").click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(typed_v)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(500)
    arrow(pg, auto1["player"], 1, 3)
    tab(pg, "WR")
    pg.locator(f'#rank-body tr[data-tier="{del_tier}"]:not(.player) [data-tier-act="delete"]').first.click(force=True); pg.wait_for_timeout(300)
    pg.locator('#rank-body [data-tier-act="del-up"]').first.click(force=True); pg.wait_for_timeout(500)
    msg = save(pg)
    pub1 = board_csv(repo.read("index.html")); P1 = rows_of(pub1)
    moved_wr = [x for x in wr if x["tier"] == del_tier]
    ok("Published" in msg and P1[(typed_p["player"], typed_p["pos"])]["value"] == str(typed_v)
       and P1[(auto1["player"], auto1["pos"])]["source"] == "manual" and int(P1[(auto1["player"], auto1["pos"])]["rank"]) == 203
       and all(P1[(x["player"], "WR")]["tier"] == str(int(del_tier) - 1) for x in moved_wr),
       f"Deliberate edits published: {typed_p['player']} value edited to {typed_v}, WR Tier {del_tier} deleted into Tier {int(del_tier) - 1} ({len(moved_wr)} players), Auto {auto1['player']} moved #200 → #203 (Manual) · {msg!r}")
    after_pub = board(pg)
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    shown = board(pg)
    ok(shown == after_pub and status(pg) == "All saved" and local(pg) == [{}, None, None], f"After a reload the published board is on screen with nothing pending ({status(pg)!r}, browser edits {local(pg)})")

    # 2. a new session on the reloaded page: moves and their reversal
    def undo_check(label, do, undo):
        do(); mid = status(pg); undo()
        same = board(pg) == shown and status(pg) == "All saved"
        ok(same and mid != "All saved", f"New session, {label}: back to the published board exactly ({mid} on the way, {status(pg)!r} after)")
    tab(pg, "All")
    undo_check(f"Auto player {auto2['player']} down 4 and back", lambda: arrow(pg, auto2["player"], 1, 4), lambda: arrow(pg, auto2["player"], -1, 4))
    undo_check(f"the published mover {auto1['player']} up 3 and back", lambda: arrow(pg, auto1["player"], -1, 3), lambda: arrow(pg, auto1["player"], 1, 3))
    first_moved = sorted(moved_wr, key=lambda x: int(x["rank"]))[0]["player"]   # first player of the merged tier's old part
    undo_check(f"{first_moved} (re-tiered by the deleted tier) down 6 and back, All view", lambda: arrow(pg, first_moved, 1, 6), lambda: arrow(pg, first_moved, -1, 6))
    w2 = by_rank(pub1); wrs = [x for x in w2 if x["pos"] == "WR"]
    edge = next(x for k, x in enumerate(wrs) if k > 4 and wrs[k - 1]["tier"] != x["tier"])["player"]
    def wr_do(): tab(pg, "WR"); arrow(pg, edge, -1, 3)
    def wr_undo(): tab(pg, "WR"); arrow(pg, edge, 1, 3)
    undo_check(f"WR tab, {edge} up 3 across a tier boundary and back", wr_do, wr_undo)
    tab(pg, "All")
    undo_check(f"value-edited player {typed_p['player']} down 5 and back", lambda: arrow(pg, typed_p["player"], 1, 5), lambda: arrow(pg, typed_p["player"], -1, 5))

    # 3. Cancel, then moves after the Cancel
    tab(pg, "All"); arrow(pg, auto3["player"], -1, 5); arrow(pg, edge, 1, 2)
    pg.click("#eb-cancel"); pg.wait_for_timeout(500)
    ok(board(pg) == shown and status(pg) == "All saved", "Moves then Cancel: the published board again")
    undo_check(f"after a Cancel, {auto3['player']} up 5 and back", lambda: arrow(pg, auto3["player"], -1, 5), lambda: arrow(pg, auto3["player"], 1, 5))
    ok(repo.read("index.html") is not None and board_csv(repo.read("index.html")) == pub1, "Nothing was published by the moves and reversals")
    ctx.close()

    # 4. saved in this browser (no token), reloaded, then undone
    ctx2 = br.new_context(viewport={"width": 1440, "height": 1000})
    pg = open_page(ctx2, token=False)
    live = board(pg)
    tab(pg, "All"); arrow(pg, auto2["player"], 1, 3)
    tab(pg, "WR"); arrow(pg, edge, -1, 3); tier_mid = row(pg, edge).get_attribute("data-tier") or ""
    tab(pg, "All")
    msg = save(pg); edits, sess, tch = local(pg)
    ok("Saved in this browser" in msg and len(edits) > 0 and sess and tch, f"Saved in this browser, not published: {len(edits)} players with browser edits, editor bookkeeping and touched players saved with them")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(status(pg) == "All saved" and local(pg)[0] == edits, "After a reload the browser edits are back, nothing unsaved")
    tab(pg, "WR"); arrow(pg, edge, 1, 3)
    tab(pg, "All"); arrow(pg, auto2["player"], -1, 3)
    msg = save(pg); edits2, sess2, tch2 = local(pg)
    ok(edits2 == {} and sess2 is None and tch2 is None and board(pg) == live,
       f"Those moves undone after the reload and saved: no browser edits left, bookkeeping cleared, the live board on screen (Auto {auto2['player']} Auto again, {edge} back in his tier) {edits2}")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(board(pg) == live and local(pg) == [{}, None, None], "And after another reload")
    ctx2.close()

    ok(not errs, f"No page errors {errs[:3]}")
    br.close()

ok(hashlib.sha256(open(os.path.join(ROOT, "index.html"), "rb").read()).hexdigest() == DISK_SHA, "index.html on disk unchanged")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll reversal persistence checks passed.")
sys.exit(1 if failures else 0)
