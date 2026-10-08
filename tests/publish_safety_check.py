"""Publishing safety and editor credentials (Phase 1 reliability). Runs the page's real publish code against the in-memory
GitHub repository in tests/gh_mock.py; nothing reaches GitHub, and index.html on disk is checked unchanged at the end.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/publish_safety_check.py
INDEX=old.html runs the same checks against another version of the page (e.g. the code before Phase 1, to show they fail).

Checks:
 1. Atomic: rankings and ranking history land in ONE commit; a failure while writing the second file leaves no commit.
 2. Lost answer after the branch moved: the publish looks again, finds its commit and reports success (no second commit).
 3. Offline right after the branch moved: "not confirmed", edits kept; the next publish finds the commit landed and adds
    no second commit and no duplicate history entries.
 4. Three-way conflict: someone else published a different value for a field edited here → stopped, nothing written,
    edits kept; the same conflict is still caught after a reload (the edit's base is saved with it).
 5. 401 (expired token): message, edits kept, token removed from storage. 403 (no write access): message, token kept.
    Rate limit: its own message. Timeout / no connection: message, edits kept, nothing written.
 6. A malformed history file on GitHub stops the publish (nothing written).
 7. An unexpected response shape (a commit with no tree) gives a clear failure, never a success.
 8. Tokens never appear in messages (GitHub echoing the token back is redacted).
 9. Token storage: this tab only by default (sessionStorage), localStorage only with "Remember"; Sign out clears both;
    a token remembered before Phase 1 keeps working.
10. Site storage blocked: the page loads, the editor works, and Save says it couldn't save (no false "saved").
11. Edits made while a publish is in flight are kept after it completes; a double click publishes once.
"""
import functools, hashlib, http.server, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISK_SHA = hashlib.sha256(open(os.path.join(ROOT, "index.html"), "rb").read()).hexdigest()
ORIG = open(os.environ.get("INDEX", os.path.join(ROOT, "index.html")), "rb").read()
HIST = open(os.path.join(ROOT, "data/rank_history.json"), "rb").read()
INJ = open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read()
SNAPS = {f"data/rank_snapshots/{f}": open(os.path.join(ROOT, "data/rank_snapshots", f), "rb").read() for f in os.listdir(os.path.join(ROOT, "data/rank_snapshots"))}
CSV_RE = re.compile(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
TOKEN = "ghp_SECRETtesttoken0123456789abcdef"

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

def new_repo():
    return Repo({"index.html": ORIG, "data/rank_history.json": HIST, "data/injury_overrides.json": INJ, **SNAPS})
def snap_count(repo, commit=None):
    return sum(len(json.loads(repo.read(p, commit) or b'{"snapshots":[]}')["snapshots"]) for p in set(SNAPS) | {f"data/rank_snapshots/{time.strftime('%Y-%m', time.gmtime())}.json"})
def ev_count(repo, commit=None):
    return len(json.loads(repo.read("data/rank_history.json", commit)).get("events", []))
def hist_count(repo, commit=None):
    return sum(len(v) for v in json.loads(repo.read("data/rank_history.json", commit))["players"].values())
def csv_rows(repo):
    import csv, io
    rows = list(csv.reader(io.StringIO(CSV_RE.search(repo.read("index.html"))[2].decode()))); return rows[0], rows[1:]

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []

    def open_page(repo, ctx=None, token="local", init=None):
        ctx = ctx or br.new_context(viewport={"width": 1440, "height": 1000})
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history|injury_overrides)\.json.*"), lambda r: r.fulfill(status=200, content_type="application/json",
                 body=repo.read("data/" + r.request.url.split("/data/")[1].split("?")[0])))
        if token == "local": pg.add_init_script(f"try {{ if (!sessionStorage.getItem('t0')) {{ localStorage.setItem('spm_editor_token', '{TOKEN}'); sessionStorage.setItem('t0', '1'); }} }} catch (e) {{}}")
        if init: pg.add_init_script(init)
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
        return pg

    def name_at(pg, i): return pg.evaluate(f"() => document.querySelectorAll('#rank-body tr.player')[{i}].querySelector('.pl-name').textContent.trim()")
    def arrow(pg, name, d):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(f'.arrow[data-dir="{d}"]').click(force=True); pg.wait_for_timeout(350)
    def type_value(pg, name, v):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(".num-btn").click(); pg.wait_for_timeout(200)
        pg.fill(".val-input", str(v)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(500)
    def clear_toast(pg): pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    def wait_msg(pg, timeout=30000):
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved|Couldn't save/.test(document.getElementById('toast').textContent)", timeout=timeout)
        pg.wait_for_timeout(300); return pg.inner_text("#toast")
    def save(pg): clear_toast(pg); pg.click("#eb-save"); return wait_msg(pg)
    def publish(pg): clear_toast(pg); pg.click("#eb-publish"); return wait_msg(pg)
    def local_edits(pg): return pg.evaluate("() => JSON.parse(localStorage.getItem('spm_local_edits') || '{}')")
    def stored(pg): return pg.evaluate("() => ({ local: localStorage.getItem('spm_editor_token'), session: sessionStorage.getItem('spm_editor_token') })")
    def commits_since(repo, n0): return repo.log()[n0:]

    write = lambda st, body, headers=None: (lambda m, r: (st, body, headers or {}) if m != "GET" else None)   # every write answered with st
    def run_case(n, fn):   # one crash is one failure; the other scenarios still run
        try: fn()
        except Exception as e:
            ok(False, f"Scenario {n} crashed: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
            for c in br.contexts:
                try: c.close()
                except Exception: pass

    # 1. atomic: one commit with both files; a failure on the second blob leaves nothing
    def case_1():
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log()); h0, s0, e0 = hist_count(repo), snap_count(repo), ev_count(repo)
        nm = name_at(pg, 40); arrow(pg, nm, -1); msg = save(pg)
        new = commits_since(repo, n0)
        ok("Published and confirmed" in msg and len(new) == 1 and hist_count(repo) > h0 and snap_count(repo) == s0 + 1 and ev_count(repo) == e0 + 1 and repo.read("index.html") != ORIG,
           f"Atomic: one commit carries the rankings, {hist_count(repo) - h0} history entries, 1 event and 1 board snapshot ({[m.splitlines()[0] for m in new]})")
        blobs = {"n": 0}
        def second_blob_fails(method, rest):
            if method == "POST" and rest == "/git/blobs":
                blobs["n"] += 1
                if blobs["n"] == 2: return (500, {"message": "Server Error"})
        repo.faults["respond"] = second_blob_fails
        n0 = len(repo.log()); head0 = repo.head; nm = name_at(pg, 60); arrow(pg, nm, -1); msg = save(pg); repo.faults.clear()
        ok(msg.startswith("Publish failed") and repo.head == head0 and not commits_since(repo, n0) and local_edits(pg),
           f"Atomic: the history blob failing leaves no commit at all and keeps the edits ({msg[:70]!r})")
        msg = publish(pg)
        ok("Published and confirmed" in msg and len(commits_since(repo, n0)) == 1 and not local_edits(pg), f"Atomic: publishing again lands it in one commit ({msg[:50]!r})")
        pg.context.close()
    run_case(1, case_1)

    # 2. the branch moved but the answer was lost
    def case_2():
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log())
        repo.faults["patch_lost"] = True
        nm = name_at(pg, 30); arrow(pg, nm, -1); msg = save(pg)
        ok("Published and confirmed" in msg and len(commits_since(repo, n0)) == 1 and not local_edits(pg),
           f"Lost answer: the publish found its own commit on the branch and confirmed it, one commit ({msg[:60]!r})")
        pg.context.close()
    run_case(2, case_2)

    # 3. offline right after the branch moved, then back online
    def case_3():
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log())
        repo.faults["offline_after_patch"] = True
        nm = name_at(pg, 50); arrow(pg, nm, -1); msg = save(pg)
        landed_head, h1, s1, e1 = repo.head, hist_count(repo), snap_count(repo), ev_count(repo)
        ok("not confirmed" in msg and "Published and confirmed" not in msg and local_edits(pg) and len(commits_since(repo, n0)) == 1,
           f"Offline after the commit: says it isn't confirmed, keeps the edits ({msg[:80]!r})")
        ok(pg.evaluate("() => !!JSON.parse(localStorage.getItem('spm_publish_pending') || 'null')"), "Offline after the commit: the unconfirmed commit is remembered")
        repo.faults.clear()
        msg = publish(pg)
        ok("Already live" in msg and repo.head == landed_head and len(commits_since(repo, n0)) == 1 and hist_count(repo) == h1 and snap_count(repo) == s1 and ev_count(repo) == e1 and not local_edits(pg)
           and pg.evaluate("() => !localStorage.getItem('spm_publish_pending') && !localStorage.getItem('spm_history_pending')"),
           f"Back online: the retry finds it landed, no second commit, no duplicate history entry, event or snapshot ({msg[:60]!r})")
        pg.context.close()
    run_case(3, case_3)

    # 4. three-way conflict, on this page and after a reload
    def case_4():
        repo = new_repo(); pg = open_page(repo, token=None); n0 = len(repo.log())
        nm = name_at(pg, 70); v = pg.evaluate(f"() => Number([...document.querySelectorAll('#rank-body tr.player')][70].querySelector('.val .num, .val .num-btn').textContent.replace(/\\D/g, ''))")
        type_value(pg, nm, v + 7); msg = save(pg)   # no token: saved in this browser only
        ok("Saved in this browser" in msg and local_edits(pg), "Conflict setup: a typed value saved in this browser")
        h, rows = csv_rows(repo)   # someone else publishes a different value for the same player
        for r in rows:
            if r[h.index("player")] == nm: r[h.index("value")] = str(v + 99)
        import csv as _csv, io as _io
        out = _io.StringIO(); _csv.writer(out, lineterminator="\n").writerows([h] + rows)
        html = repo.read("index.html"); m = CSV_RE.search(html)
        repo.commit_file("index.html", html[:m.start(2)] + out.getvalue().rstrip("\n").encode() + html[m.end(2):], "Rankings edit by @someone (1 player)")
        head0 = repo.head
        pg.evaluate(f"() => localStorage.setItem('spm_editor_token', '{TOKEN}')"); pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        msg = publish(pg)
        ok(msg.startswith("Publish stopped") and nm in msg and repo.head == head0 and local_edits(pg),
           f"Conflict after a reload: stopped, names {nm}, nothing written, edits kept ({msg[:110]!r})")
        h, rows = csv_rows(repo)
        ok(next(r for r in rows if r[h.index("player")] == nm)[h.index("value")] == str(v + 99), "Conflict: the other editor's published value is untouched")
        pg.context.close()
    run_case(4, case_4)

    # 5. auth, permission, rate limit, timeout
    def case_5():
        def fault_case(label, respond, expect, token_after):
            repo = new_repo(); pg = open_page(repo); n0 = len(repo.log())
            repo.faults["respond"] = respond
            nm = name_at(pg, 90); arrow(pg, nm, 1); msg = save(pg)
            st = stored(pg)
            ok(msg.startswith("Publish failed") and re.search(expect, msg, re.I) and not commits_since(repo, n0) and local_edits(pg),
               f"{label}: clear message, nothing written, edits kept ({msg[:110]!r})")
            ok(bool(st["local"]) == token_after, f"{label}: token {'kept' if token_after else 'removed from this browser'}")
            ok(TOKEN not in msg, f"{label}: the token isn't in the message")
            pg.context.close()
        fault_case("Expired token (401)", write(401, {"message": "Bad credentials"}), r"no longer accepts the saved token", False)
        fault_case("No write access (403)", write(403, {"message": "Resource not accessible by personal access token"}), r"needs write access", True)
        fault_case("Rate limited", write(403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0"}), r"rate limit", True)
        fault_case("No connection", lambda m, r: "abort" if m != "GET" else None, r"couldn't reach GitHub.*safe", True)
    run_case(5, case_5)

    # 6. malformed history on GitHub
    def case_6():
        repo = new_repo(); pg = open_page(repo); repo.commit_file("data/rank_history.json", b"{not json"); head0 = repo.head
        nm = name_at(pg, 33); arrow(pg, nm, -1); msg = save(pg)
        ok(msg.startswith("Publish failed") and "isn't valid JSON" in msg and repo.head == head0 and local_edits(pg), f"Malformed history on GitHub: stops, nothing written, edits kept ({msg[:90]!r})")
        pg.context.close()
    run_case(6, case_6)

    # 7. an unexpected response shape
    def case_7():
        repo = new_repo(); pg = open_page(repo); head0 = repo.head; repo.faults["bad_commit"] = True
        nm = name_at(pg, 34); arrow(pg, nm, -1); msg = save(pg); repo.faults.clear()
        ok(msg.startswith("Publish failed") and "Published and confirmed" not in msg and repo.head == head0 and local_edits(pg),
           f"Unexpected response: a clear failure, nothing written, edits kept ({msg[:100]!r})")
        pg.context.close()
    run_case(7, case_7)

    # 8. GitHub echoing the token back is redacted
    def case_8():
        repo = new_repo(); pg = open_page(repo)
        repo.faults["respond"] = write(422, {"message": f"Invalid request: token {TOKEN} rejected"})
        nm = name_at(pg, 35); arrow(pg, nm, -1); msg = save(pg)
        diag = pg.evaluate("() => JSON.stringify(SPM.diagnostics ? SPM.diagnostics() : [])")
        ok(TOKEN not in msg and TOKEN not in diag and "[token]" in msg + diag, f"Token echoed by GitHub is redacted in the message and diagnostics ({msg[:90]!r})")
        pg.context.close()
    run_case(8, case_8)

    # 9. token storage
    def case_9():
        repo = new_repo(); pg = open_page(repo, token=None)
        nm = name_at(pg, 36); arrow(pg, nm, -1); clear_toast(pg); pg.click("#eb-save"); pg.wait_for_timeout(1200)
        pg.click("#eb-publish"); pg.wait_for_selector("#signin-dialog[open]")
        ok(pg.is_visible("#signin-remember") and not pg.is_checked("#signin-remember"), "Sign-in: 'Remember on this browser' is offered and off by default")
        pg.fill("#signin-token", TOKEN); clear_toast(pg); pg.click("#signin-submit"); msg = wait_msg(pg)
        st = stored(pg)
        ok("Published and confirmed" in msg and st["session"] == TOKEN and not st["local"], f"Default sign-in keeps the token in this tab only (session {bool(st['session'])}, local {bool(st['local'])})")
        ok(pg.input_value("#signin-token") == "", "The token field is cleared after sign-in")
        pg.click("#eb-signout"); pg.wait_for_timeout(300); st = stored(pg)
        ok(not st["local"] and not st["session"] and pg.evaluate("() => document.getElementById('eb-signout').hidden"), "Sign out clears the token everywhere")
        nm = name_at(pg, 37); arrow(pg, nm, -1); clear_toast(pg); pg.click("#eb-save"); pg.wait_for_timeout(1200)
        pg.click("#eb-publish"); pg.wait_for_selector("#signin-dialog[open]")
        pg.fill("#signin-token", TOKEN); pg.check("#signin-remember"); clear_toast(pg); pg.click("#signin-submit"); wait_msg(pg); st = stored(pg)
        ok(st["local"] == TOKEN and not st["session"], "'Remember on this browser' keeps it in localStorage")
        pg.context.close()
        repo = new_repo(); pg = open_page(repo)   # remembered the old way (localStorage)
        ok(pg.evaluate("() => !document.getElementById('eb-signout').hidden"), "A token remembered before Phase 1 still signs in")
        pg.context.close()
    run_case(9, case_9)

    # 10. site storage blocked
    def case_10():
        repo = new_repo()
        blocked = """(() => { const no = () => { throw new DOMException('blocked', 'SecurityError'); };
          for (const k of ['localStorage', 'sessionStorage']) Object.defineProperty(window, k, { get: no, configurable: true }); })();"""
        n_err = len(errs)
        pg = open_page(repo, token=None, init=blocked)
        nm = name_at(pg, 38); arrow(pg, nm, -1); msg = save(pg)
        ok(len(errs) == n_err and "Couldn't save" in msg and "Saved in this browser" not in msg, f"Storage blocked: page works, Save says it couldn't save ({msg[:70]!r}) {errs[n_err:][:2]}")
        pg.context.close()
    run_case(10, case_10)

    # 11. edits during an in-flight publish, and a double click
    def case_11():
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log())
        a = name_at(pg, 20); arrow(pg, a, -1)
        repo.delay = 0.25
        clear_toast(pg); pg.click("#eb-save"); pg.wait_for_timeout(600)
        ok(pg.evaluate("() => document.getElementById('eb-local-text').textContent").startswith("Publishing"), "In flight: the bar says Publishing…")
        b = name_at(pg, 100); arrow(pg, b, -1)   # an unsaved move while the publish runs
        pg.evaluate("() => document.getElementById('eb-publish').click()")   # a second publish request mid-flight
        msg = wait_msg(pg, 60000); repo.delay = 0
        ok("Published and confirmed" in msg and len(commits_since(repo, n0)) == 1, f"Double publish: one commit ({len(commits_since(repo, n0))})")
        ok(name_at(pg, 99) == b and pg.inner_text("#eb-count").strip() != "All saved", f"The move made during the publish is still on the board, unsaved ({name_at(pg, 99)} at #100)")
        h, rows = csv_rows(repo)
        ok(next(r for r in rows if r[h.index("player")] == a)[h.index("rank")] == "20", f"The published move is live ({a} #20)")
        pg.context.close()
    run_case(11, case_11)

    ok(not errs, f"No page errors {errs[:3]}")
    br.close()

ok(hashlib.sha256(open(os.path.join(ROOT, "index.html"), "rb").read()).hexdigest() == DISK_SHA, "index.html on disk is unchanged")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll publishing safety checks passed.")
sys.exit(1 if failures else 0)
