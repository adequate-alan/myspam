"""Publishing rankings from the editor, end to end (Alan, Oct 11). The page's real publish code runs against an in-memory
GitHub repository (tests/gh_mock.py, Git Data API + the Contents API's 1 MB behaviour); the page itself is served from
that repository's current index.html, so a reload shows what was published. Nothing touches GitHub or the files on disk:
the repository starts as an in-memory copy of this checkout's index.html and data files, and the script checks at the end
that index.html on disk is byte-for-byte unchanged.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/publish_check.py

Checks:
1. The failure Alan hit: index.html is over 1 MB, so GitHub's Contents API returns it without content; the site never
   calls the Contents API.
2. Move up, move down, a tier change and a typed value, each saved and published in a row on one page: exactly one
   commit each, carrying the rankings, data/rank_history.json and data/rank_snapshots/<YYYY-MM>.json together (Phase 1:
   one atomic commit; was a rankings commit and then a history commit), verified in Python to describe the same
   publication (same_publication), every earlier entry, event and snapshot kept as it was, only the edited ranking fields change, every rank runs 1..N, Sleeper IDs
   stay unique, everything outside the rankings block is byte-identical, local edits are cleared, and the success
   message only appears after the commit is confirmed.
3. Reopening the editor (reload, served from the repository) shows the published board with nothing pending, and a
   further edit publishes on top of it.
4. No-change cases: edits undone before saving publish nothing; edits already on GitHub (another tab) say "Already live"
   and commit nothing.
5. Failures stop safely with a descriptive message, no rankings commit, the file unchanged and the edits kept in this
   browser: missing markers, two rankings blocks, malformed CSV, duplicate Sleeper IDs, a missing column, a truncated
   download, a GitHub error while writing (POST blob, PATCH ref), a read-back mismatch, and an outdated page whose
   merge would duplicate ranks.
6. A commit made by someone else while publishing (non-conflicting) is kept: the publish re-reads, re-merges and lands
   on top of it.
"""
import csv, functools, hashlib, http.server, io, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo, ONE_MB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.environ.get("INDEX", os.path.join(ROOT, "index.html"))   # INDEX=old.html reproduces a pre-fix page
DISK = open(os.path.join(ROOT, "index.html"), "rb").read(); DISK_SHA = hashlib.sha256(DISK).hexdigest()
ORIG = open(INDEX, "rb").read()
HIST = open(os.path.join(ROOT, "data/rank_history.json"), "rb").read()
INJ = open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read()
SNAPS = {f"data/rank_snapshots/{f}": open(os.path.join(ROOT, "data/rank_snapshots", f), "rb").read() for f in os.listdir(os.path.join(ROOT, "data/rank_snapshots"))}
CSV_RE = re.compile(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
EDIT_COLS = ["rank", "pos_rank", "tier", "value", "source", "tier_name"]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def block(html):
    m = CSV_RE.search(html); return m, m[2].decode() if m else None
def table(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text))); return rows[0], rows[1:]
def keyed(csv_text):
    h, rows = table(csv_text); return h, {(r[h.index("player")] + "|" + r[h.index("pos")]).lower(): r for r in rows}
def outside(html):
    m = CSV_RE.search(html); return html[:m.start(2)] + html[m.end(2):]
def sound(csv_text):   # ranks 1..N, unique Sleeper IDs, position ranks follow the overall order
    h, rows = table(csv_text); c = h.index
    ranks = sorted(int(r[c("rank")]) for r in rows)
    ids = [r[c("sleeper_id")] for r in rows if r[c("sleeper_id")]]
    pos = {}
    for r in sorted(rows, key=lambda r: int(r[c("rank")])): pos.setdefault(r[c("pos")], []).append(r)
    posok = all(r[c("pos_rank")] == str(i + 1) for lst in pos.values() for i, r in enumerate(lst))
    return ranks == list(range(1, len(rows) + 1)) and len(ids) == len(set(ids)) and posok and all(len(r) == len(h) for r in rows)
def changes(before, after):   # {key: {col: (old, new)}}, and whether any non-ranking column changed
    hb, b = keyed(before); ha, a = keyed(after); out, fixed = {}, []
    for k, rb in b.items():
        ra = a.get(k)
        if ra is None: fixed.append(("lost", k)); continue
        for col in hb:
            ov, nv = rb[hb.index(col)], (ra[ha.index(col)] if col in ha else "")
            if ov != nv:
                if col in EDIT_COLS: out.setdefault(k, {})[col] = (ov, nv)
                else: fixed.append((k, col))
    fixed += [("added", k) for k in a if k not in b]
    return out, fixed

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

def new_repo(index=ORIG):
    return Repo({"index.html": index, "data/rank_history.json": HIST, "data/injury_overrides.json": INJ, **SNAPS})

def same_publication(repo, before, after):
    """Phase 1: the commit `after` holds the rankings, the history and the exact snapshot of ONE publication. Checked
    here independently of the page: every player's rank, position rank, tier and typed value in index.html equals the
    new snapshot; the new history entries and the publish event carry the snapshot's timestamp and its values; nothing
    recorded before (entries, events, snapshots) changed. Returns a list of problems."""
    errs = []
    h, rows = table(block(repo.read("index.html", after))[1]); c = h.index
    hb, ha = json.loads(repo.read("data/rank_history.json", before)), json.loads(repo.read("data/rank_history.json", after))
    ev = ha["events"][-1] if len(ha["events"]) > len(hb.get("events", [])) else None
    if not ev: return ["no new publish event"]
    if ha["events"][:len(hb.get("events", []))] != hb.get("events", []): errs.append("earlier events changed")
    if any(ha["players"].get(sid, [])[:len(l)] != l for sid, l in hb["players"].items()): errs.append("earlier history entries changed")
    path = f"data/rank_snapshots/{ev['ts'][:7]}.json"
    sb, sa = repo.read(path, before), repo.read(path, after)
    old_s = json.loads(sb)["snapshots"] if sb else []; new_s = json.loads(sa)["snapshots"] if sa else []
    if ev.get("snap") != ev["ts"][:7] or len(new_s) != len(old_s) + 1 or new_s[:len(old_s)] != old_s: return errs + [f"{path} didn't get exactly one new snapshot (event snap {ev.get('snap')})"]
    snap = new_s[-1]
    if snap["ts"] != ev["ts"]: errs.append("snapshot and event times differ")
    for r in rows:
        sid = r[c("sleeper_id")]; a = snap["players"].get(sid)
        if a is None: continue
        typed = r[c("value")].strip() != ""
        if [a[0], a[1], str(a[2])] != [int(r[c("rank")]), int(r[c("pos_rank")]), r[c("tier")]] or a[4] != (1 if typed else 0) or (typed and a[3] != round(float(r[c("value")]))):
            errs.append(f"{r[c('player')]}: index.html {r[c('rank')]}/{r[c('pos_rank')]}/T{r[c('tier')]}/{r[c('value')] or 'model'} vs snapshot {a}"); break
    new_entries = {sid: l[-1] for sid, l in ha["players"].items() if len(l) > len(hb["players"].get(sid, []))}
    for sid, e in new_entries.items():
        a = snap["players"].get(sid)
        if e[0] != ev["ts"] or not a or e[1:5] != a[:4]: errs.append(f"history entry for {sid} {e} doesn't match the snapshot {a}"); break
    if not new_entries and (ev["ranking"] or ev["manual"]): errs.append("event lists changes but no entries were added")
    return errs

ROWS = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({ id: tr.dataset.id, name: tr.querySelector('.pl-name').textContent.trim(),
  pos: (tr.querySelector('.pos-col .pos') || {}).textContent, tier: tr.dataset.tier || null,
  v: Number((tr.querySelector('.val .num, .val .num-btn') || {}).textContent.replace(/\\D/g, '')) }))"""

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []

    def open_page(repo, ctx=None, token=True):
        ctx = ctx or br.new_context(viewport={"width": 1440, "height": 1000})
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        # the page and the files it publishes come from the repository's current head
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history|injury_overrides)\.json.*"), lambda r: r.fulfill(status=200, content_type="application/json",
                 body=repo.read("data/" + r.request.url.split("/data/")[1].split("?")[0])))
        if token: pg.add_init_script("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        return pg

    def all_tab(pg):
        pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
    def rows(pg): return pg.evaluate(ROWS)
    def arrow(pg, name, d):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(f'.arrow[data-dir="{d}"]').click(force=True); pg.wait_for_timeout(350)
    def type_value(pg, name, v):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(".num-btn").click(); pg.wait_for_timeout(200)
        pg.fill(".val-input", str(v)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(500)
    def save(pg, wait=True):   # Save changes; with a token it publishes. Returns the final message.
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-save")
        if not wait: return ""
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
        pg.wait_for_timeout(300)
        return pg.inner_text("#toast")
    def local_edits(pg): return pg.evaluate("() => JSON.parse(localStorage.getItem('spm_local_edits') || '{}')")
    def contents_calls(repo): return [c for c in repo.calls if "/contents/" in c[1]]

    # 1. the failure: over 1 MB the Contents API has no content
    r0 = new_repo()
    ok(len(ORIG) > ONE_MB, f"index.html is {len(ORIG):,} bytes, over GitHub's 1 MB Contents API limit")
    big = r0.read("index.html")
    ok(big and len(big) > ONE_MB, "The mock answers the Contents API like GitHub (content left out above 1 MB)")

    # 2. publishing four kinds of edit in a row
    repo = new_repo()
    pg = open_page(repo)
    ok(pg.evaluate("() => !document.getElementById('editor-bar').hidden"), "Editor bar is open")
    all_tab(pg); board = rows(pg)
    def publish_step(label, act, expect):
        before = repo.read("index.html"); head0 = repo.head; n0 = len(repo.log())
        act(); msg = save(pg)
        after = repo.read("index.html")
        ch, fixed = changes(block(before)[1], block(after)[1])
        new = repo.log()[n0:]
        ok("Published and confirmed" in msg and repo.head != head0, f"{label}: published and confirmed ({msg[:90]!r})")
        ok(len(new) == 1 and new[0].startswith("Rankings edit by @tester"), f"{label}: exactly one commit {[m.splitlines()[0] for m in new]}")
        hl = [l for l in new[0].splitlines() if l.startswith("Ranking history: ")] if new else []
        files = {f for f in ["index.html", "data/rank_history.json"] + [p for p in SNAPS] + [f"data/rank_snapshots/{time.strftime('%Y-%m', time.gmtime())}.json"]
                 if repo.read(f) != repo.read(f, head0)}
        ok(len(hl) == 1 and {"index.html", "data/rank_history.json"} <= files and any(f.startswith("data/rank_snapshots/") for f in files),
           f"{label}: that one commit changes the rankings, the history and the board snapshot together ({sorted(files)}; {hl})")
        probs = same_publication(repo, head0, repo.head)
        ok(not probs, f"{label}: rankings, history entries, event and snapshot describe the same publication; nothing earlier changed {probs[:2]}")
        ok(outside(before) == outside(after), f"{label}: everything outside the rankings block is byte-identical")
        ok(not fixed and sound(block(after)[1]), f"{label}: only ranking fields changed, ranks 1..N, unique IDs, position ranks in order {fixed[:3]}")
        ok(expect(ch), f"{label}: the intended fields changed {json.dumps({k: v for k, v in list(ch.items())[:4]})}")
        ok(not local_edits(pg) and pg.evaluate("() => document.getElementById('eb-local').hidden"), f"{label}: browser edits cleared, nothing pending")
        return ch
    up = board[49]["name"]; up_above = board[48]["name"]
    publish_step("Move up", lambda: arrow(pg, up, -1),
                 lambda ch: any(v.get("rank") == ("50", "49") for v in ch.values()) and any(v.get("rank") == ("49", "50") for v in ch.values()) and len(ch) == 2)
    all_tab(pg); board = rows(pg); down = board[79]["name"]
    publish_step("Move down", lambda: arrow(pg, down, 1),
                 lambda ch: any(v.get("rank") == ("80", "81") for v in ch.values()) and any(v.get("rank") == ("81", "80") for v in ch.values()) and len(ch) == 2)
    # tier change: in the WR tab, the first player of a lower tier moves up into the tier above
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(400)
    TIERED = """() => [...document.querySelectorAll('#rank-body tr')].reduce((o, tr) => { if (tr.dataset.tier && !tr.classList.contains('player')) o.t = tr.dataset.tier;
      if (tr.classList.contains('player')) o.rows.push({ name: tr.querySelector('.pl-name').textContent.trim(), tier: tr.dataset.tier || o.t }); return o; }, { t: null, rows: [] }).rows"""
    wr = pg.evaluate(TIERED)
    i = next(k for k in range(1, len(wr)) if wr[k]["tier"] != wr[k - 1]["tier"] and k > 8)
    tmover = wr[i]["name"]
    publish_step("Tier change", lambda: arrow(pg, tmover, -1),
                 lambda ch: any(k.startswith(tmover.lower() + "|") and "tier" in v for k, v in ch.items()))
    all_tab(pg); board = rows(pg); vp = board[119]; newv = vp["v"] + 1
    publish_step("Typed value", lambda: type_value(pg, vp["name"], newv),
                 lambda ch: any(k.startswith(vp["name"].lower() + "|") and v.get("value", (None, None))[1] == str(newv) for k, v in ch.items()))

    # 3. reopen the editor: the reload is served from the repository
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500); all_tab(pg)
    after_rows = rows(pg); names = [r["name"] for r in after_rows]
    ok(names.index(up) == 48 and names.index(up_above) == 49 and names.index(down) == 80, f"Reload shows the published board ({up} #49, {down} #81)")
    vrow = next(r for r in after_rows if r["name"] == vp["name"])
    ok(vrow["v"] == newv, f"Reload shows the published value ({vp['name']} {vrow['v']})")
    ok(pg.inner_text("#eb-count").strip() == "All saved" and pg.evaluate("() => document.getElementById('eb-local').hidden") and not local_edits(pg), "Reopened editor: nothing unsaved or unpublished")
    nxt = after_rows[149]["name"]
    publish_step("Edit after reopening", lambda: arrow(pg, nxt, -1), lambda ch: len(ch) == 2)

    # 4a. no change: an edit undone before saving publishes nothing
    all_tab(pg); h0 = repo.head; mid = rows(pg)[99]["name"]
    arrow(pg, mid, -1); arrow(pg, mid, 1)
    disabled = pg.evaluate("() => document.getElementById('eb-save').disabled")
    if not disabled: msg = save(pg)
    else: msg = "(Save disabled)"
    ok(repo.head == h0 and "Publish" not in msg.replace("Nothing to publish", ""), f"Undone edit: no commit ({msg[:80]!r})")
    ok(not contents_calls(repo), f"The Contents API was never used ({len(repo.calls)} GitHub calls)")

    # 4b. edits already on GitHub (published from another tab): "Already live", no commit
    rp = new_repo(); pga = open_page(rp); all_tab(pga); nm = rows(pga)[59]["name"]
    rp.faults["patch"] = 500   # the first try fails, so the edit stays saved in this browser
    arrow(pga, nm, -1); save(pga); rp.faults.clear()
    edits = local_edits(pga)
    other = new_repo(); pgb = open_page(other); all_tab(pgb); arrow(pgb, nm, -1); save(pgb)   # the same edit, published elsewhere
    rp.commit_file("index.html", other.read("index.html"), "Rankings edit from another tab"); h0 = rp.head
    pga.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; }")
    pga.click("#eb-publish")
    pga.wait_for_function("() => /Publish|Already live/.test(document.getElementById('toast').textContent)", timeout=20000); pga.wait_for_timeout(300)
    msg = pga.inner_text("#toast")
    ok(edits and "Already live" in msg and not [m for m in rp.log() if m.startswith("Rankings edit by")] and not local_edits(pga),
       f"Edits already on GitHub: no rankings commit, browser edits cleared ({msg[:70]!r})")
    pga.context.close(); pgb.context.close()

    # 5. failures stop safely
    def broken(label, setup, expect_msg, fault=None, after_load=True):
        rp = new_repo(); pgf = open_page(rp); all_tab(pgf)
        if setup and after_load: setup(rp)   # the change lands on GitHub after the page loaded (another commit)
        if fault: rp.faults.update(fault)
        nm = rows(pgf)[29]["name"]; arrow(pgf, nm, -1)
        before = rp.read("index.html"); log0 = rp.log()
        msg = save(pgf)
        rank_commits = [m for m in rp.log()[len(log0):] if m.startswith("Rankings edit")]
        same_file = rp.read("index.html") == before
        kept = bool(local_edits(pgf))
        ok(re.match(r"Publish (failed|stopped)", msg) and re.search(expect_msg, msg, re.I) and "Published and confirmed" not in msg,
           f"{label}: stops with a clear message ({msg[:150]!r})")
        if fault and fault.get("readback"):
            ok(same_file and kept, f"{label}: the file content is unchanged and the edits stay in this browser")
        else:
            ok(not rank_commits and same_file and kept, f"{label}: no rankings commit, file unchanged, edits kept in this browser")
        pgf.context.close()
        return msg
    def edit_file(fn):
        def go(rp): rp.commit_file("index.html", fn(rp.read("index.html")))
        return go
    def edit_csv(fn):
        return edit_file(lambda html: html[:CSV_RE.search(html).start(2)] + fn(CSV_RE.search(html)[2].decode()).encode() + html[CSV_RE.search(html).end(2):])
    def row_edit(fn):   # change rows of the CSV through a callback on (header, rows)
        def go(text):
            h, rs = table(text); fn(h, rs); out = io.StringIO(); csv.writer(out, lineterminator="\n").writerows([h] + rs)
            return out.getvalue().rstrip("\n")
        return go
    broken("Missing markers", edit_file(lambda h: h.replace(b"const RANKINGS_CSV = `", b"const RANKINGS = `", 1)), r"Couldn't find the rankings block")
    broken("Two rankings blocks", edit_file(lambda h: h.replace(b"</body>", b"<script>const RANKINGS_CSV = `\nx\n`;</script></body>", 1)), r"2 rankings blocks")
    broken("Malformed CSV (non-numeric rank)", edit_csv(row_edit(lambda h, rs: rs[200].__setitem__(h.index("rank"), "abc"))), r"invalid rank")
    broken("Malformed CSV (extra field)", edit_csv(lambda t: "\n".join(l + (",extra" if i == 150 else "") for i, l in enumerate(t.split("\n")))), r"fields instead of")
    broken("Duplicate Sleeper IDs", edit_csv(row_edit(lambda h, rs: rs[201].__setitem__(h.index("sleeper_id"), rs[200][h.index("sleeper_id")]))), r"Sleeper ID .* appears twice")
    broken("Missing column", edit_csv(lambda t: t.replace(",source", ",src", 1)), r"source column is missing")
    broken("Truncated download", None, r"incomplete", fault={"truncate": True})
    broken("GitHub error writing (blob)", None, r"Server Error", fault={"post_blob": 500})
    broken("GitHub error moving the branch", None, r"Server Error", fault={"patch": 500})
    broken("Read-back mismatch", None, r"didn't match", fault={"readback": True})
    # outdated page: another browser moved players next to mine, so the merge would give two players one rank
    def overlap_conflict(rp):
        html = rp.read("index.html"); text = CSV_RE.search(html)[2].decode(); h, rs = table(text); c = h.index
        by = {int(r[c("rank")]): r for r in rs}
        # they moved #29 down two spots (#30 → 29, #31 → 30); mine moves #30 up to #29, so #29 → 30 and #31 → 30 collide
        by[29][c("rank")], by[30][c("rank")], by[31][c("rank")] = "31", "29", "30"
        out = io.StringIO(); csv.writer(out, lineterminator="\n").writerows([h] + rs)
        edit_csv(lambda t: out.getvalue().rstrip("\n"))(rp)
    # Phase 1: caught by the three-way merge (a rank someone else published since this edit), before the rank checks
    broken("Outdated page (overlapping rank moves)", overlap_conflict, r"also changed on the live site.*Nothing was published")

    # 6. someone else commits while publishing (not conflicting): re-read, re-merge, keep both
    rp = new_repo(); pgc = open_page(rp); all_tab(pgc)
    def outside_commit(r):
        html = r.read("index.html"); text = CSV_RE.search(html)[2].decode(); h, rs = table(text)
        rs[240][h.index("proj_ppg")] = "1.23"
        out = io.StringIO(); csv.writer(out, lineterminator="\n").writerows([h] + rs)
        r.commit_file("index.html", html[:CSV_RE.search(html).start(2)] + out.getvalue().rstrip("\n").encode() + html[CSV_RE.search(html).end(2):], "Weekly projections")
    rp.faults["concurrent"] = outside_commit
    nm = rows(pgc)[39]["name"]; arrow(pgc, nm, -1); msg = save(pgc)
    h, final = keyed(block(rp.read("index.html"))[1])
    mine = next(r for k, r in final.items() if k.startswith(nm.lower() + "|"))
    patches = [c for c in rp.calls if c[0] == "PATCH" and "/refs/heads/" in c[1]]
    ok("Published and confirmed" in msg and mine[h.index("rank")] == "39" and any(r[h.index("proj_ppg")] == "1.23" for r in final.values()),
       f"Concurrent commit: retried ({len(patches)} branch updates) and kept both the edit and the other commit ({msg[:60]!r})")
    ok("Weekly projections" in rp.log() and sound(block(rp.read("index.html"))[1]), "Concurrent commit: history keeps the other commit, ranks still 1..N")
    pgc.context.close()

    ok(not errs, f"No page errors {errs[:3]}")
    br.close()

ok(hashlib.sha256(open(os.path.join(ROOT, "index.html"), "rb").read()).hexdigest() == DISK_SHA, "index.html on disk is unchanged")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll publishing checks passed.")
sys.exit(1 if failures else 0)
