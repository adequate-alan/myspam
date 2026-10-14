"""Scheduled ranking-history snapshot (the Tuesday workflow run).

Loads the site in a headless browser so values come from the site's own model (tiers, projections,
order passes), reads the board with window.SPM.rankingSnapshot() and records it with the same code as a
publish (window.SPM.recordPublish, Oct 11): the exact board goes to data/rank_snapshots/<YYYY-MM>.json
(skipped when identical to the last one), visible entries to data/rank_history.json (a rank or tier change,
or automatic repricing of at least 0.5% since his last entry, tagged "A"), plus one event for the run.

Every ranking set is recorded on its own (Oct 14, PR 4 of the boards work): the page is loaded once per board with that
board as the edited one (spm_edit_board), so rankingSnapshot() reads that board as published, and its snapshot and
history go to that board's own files (BOARD_FILES: AM SF PPR TE+ data/rank_history.json + data/rank_snapshots/, AM PPR
data/boards/ppr/rank_history.json + data/boards/ppr/rank_snapshots/). A board's run never reads or writes another's.

Run from the pipeline folder after the projection refresh:
    python snapshot_history.py            # every board, source "S" (scheduled update), timestamp now
    python snapshot_history.py --board ppr
    python snapshot_history.py --root /path/to/checkout   # tests
    python snapshot_history.py --ts 2026-10-01 --src S
    python snapshot_history.py --src B           # a baseline snapshot (no publish involved)
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""
import argparse, datetime, functools, http.server, json, os, socketserver, sys, threading
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# each board's history file and snapshot folder, relative to the checkout (same as BOARDS' history / snaps in index.html)
BOARD_FILES = {"sf-tep": ("data/rank_history.json", "data/rank_snapshots"),
               "ppr": ("data/boards/ppr/rank_history.json", "data/boards/ppr/rank_snapshots")}


def snap_file(snaps_dir, month):
    path = os.path.join(snaps_dir, f"{month}.json")
    return json.load(open(path)) if os.path.exists(path) else {"version": 1, "snapshots": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    ap.add_argument("--src", default="S")
    ap.add_argument("--board", default="all", choices=["all", *BOARD_FILES])
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args()
    for bid in (BOARD_FILES if args.board == "all" else [args.board]):
        record(bid, args)


def record(bid, args):
    root = os.path.abspath(args.root)
    HIST, SNAPS = (os.path.join(root, *p.split("/")) for p in BOARD_FILES[bid])
    snap_file_ = lambda month: snap_file(SNAPS, month)
    current = json.load(open(HIST)) if os.path.exists(HIST) else {"version": 2, "players": {}, "events": []}
    month = args.ts[:7]
    snaps = snap_file_(month)
    prev = snaps["snapshots"][-1] if snaps.get("snapshots") else None
    if prev is None:   # first snapshot of the month: the last one is in the month of the latest event that wrote one
        last = next((e for e in reversed(current.get("events") or []) if e.get("snap") and e["snap"] != month), None)
        if last:
            older = snap_file_(last["snap"]).get("snapshots") or []
            prev = older[-1] if older else None

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=root)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.add_init_script(f"try {{ localStorage.setItem('spm_edit_board', {json.dumps(bid)}); }} catch (e) {{}}")
            pg.route("**/*", lambda r: r.abort() if not r.request.url.startswith(url.rsplit("/", 1)[0]) else r.continue_())
            pg.goto(url)
            # A function-valued predicate is called by Playwright, so rankingSnapshot() ran before the board loaded
            # (players still null) and threw. Wait for a non-empty board instead.
            try:
                pg.wait_for_function("(() => { try { return Object.keys(window.SPM.rankingSnapshot()).length > 0; } catch (e) { return false; } })()",
                                     timeout=90_000)
            except PlaywrightTimeout:
                sys.exit(f"Ranking snapshot failed ({bid}): the board in index.html didn't load within 90 s, so nothing was recorded.")
            active = pg.evaluate("() => SPM.boards().active")
            if active != bid:   # never record one board's snapshot into another's files
                sys.exit(f"Ranking snapshot failed: the page loaded board {active!r} instead of {bid!r}, so nothing was recorded.")
            out = pg.evaluate("""([hist, snaps, prev, ts, src]) => {
                const h = SPM.normalizeHistory(hist);
                const r = SPM.recordPublish(h, snaps, prev, SPM.rankingSnapshot(), ts, src, src === "B" ? "baseline" : "scheduled", null);
                return { changed: r.changed, snapshot: r.snapshot, msg: SPM.historyMessage(r.ev), text: SPM.historyText(h), snap: SPM.boardSnapText(snaps) };
            }""", [current, snaps, prev, args.ts, args.src])
            b.close()
    finally:
        srv.shutdown()
    if out["changed"] or current.get("version") != 2:
        os.makedirs(os.path.dirname(HIST), exist_ok=True)
        open(HIST, "w").write(out["text"])
    if out["snapshot"]:
        os.makedirs(SNAPS, exist_ok=True)
        open(os.path.join(SNAPS, f"{month}.json"), "w").write(out["snap"])
    print(f"{bid}: " + (f"{out['msg']} ({args.src}, {args.ts})" if out["changed"] else f"No change since the last snapshot ({args.src}, {args.ts})"))


if __name__ == "__main__":
    main()
