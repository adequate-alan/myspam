"""Scheduled ranking-history snapshot (the Tuesday workflow run).

Loads the site in a headless browser so values come from the site's own model (tiers, projections,
order passes), reads the board with window.SPM.rankingSnapshot() and records it with the same code as a
publish (window.SPM.recordPublish, Oct 11): the exact board goes to data/rank_snapshots/<YYYY-MM>.json
(skipped when identical to the last one), visible entries to data/rank_history.json (a rank or tier change,
or automatic repricing of at least 0.5% since his last entry, tagged "A"), plus one event for the run.

Run from the pipeline folder after the projection refresh:
    python snapshot_history.py            # source "S" (scheduled update), timestamp now
    python snapshot_history.py --ts 2026-10-01 --src S
    python snapshot_history.py --src B           # a baseline snapshot (no publish involved)
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""
import argparse, datetime, functools, http.server, json, os, socketserver, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HIST = os.path.join(ROOT, "data", "rank_history.json")
SNAPS = os.path.join(ROOT, "data", "rank_snapshots")


def snap_file(month):
    path = os.path.join(SNAPS, f"{month}.json")
    return json.load(open(path)) if os.path.exists(path) else {"version": 1, "snapshots": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    ap.add_argument("--src", default="S")
    args = ap.parse_args()
    current = json.load(open(HIST)) if os.path.exists(HIST) else {"version": 2, "players": {}, "events": []}
    month = args.ts[:7]
    snaps = snap_file(month)
    prev = snaps["snapshots"][-1] if snaps.get("snapshots") else None
    if prev is None:   # first snapshot of the month: the last one is in the month of the latest event that wrote one
        last = next((e for e in reversed(current.get("events") or []) if e.get("snap") and e["snap"] != month), None)
        if last:
            older = snap_file(last["snap"]).get("snapshots") or []
            prev = older[-1] if older else None

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.route("**/*", lambda r: r.abort() if not r.request.url.startswith(url.rsplit("/", 1)[0]) else r.continue_())
            pg.goto(url)
            pg.wait_for_function("window.SPM && window.SPM.rankingSnapshot")
            out = pg.evaluate("""([hist, snaps, prev, ts, src]) => {
                const h = SPM.normalizeHistory(hist);
                const r = SPM.recordPublish(h, snaps, prev, SPM.rankingSnapshot(), ts, src, src === "B" ? "baseline" : "scheduled", null);
                return { changed: r.changed, snapshot: r.snapshot, msg: SPM.historyMessage(r.ev), text: SPM.historyText(h), snap: SPM.boardSnapText(snaps) };
            }""", [current, snaps, prev, args.ts, args.src])
            b.close()
    finally:
        srv.shutdown()
    if out["changed"] or current.get("version") != 2:
        open(HIST, "w").write(out["text"])
    if out["snapshot"]:
        os.makedirs(SNAPS, exist_ok=True)
        open(os.path.join(SNAPS, f"{month}.json"), "w").write(out["snap"])
    print(f"{out['msg']} ({args.src}, {args.ts})" if out["changed"] else f"No change since the last snapshot ({args.src}, {args.ts})")


if __name__ == "__main__":
    main()
