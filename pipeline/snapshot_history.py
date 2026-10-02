"""Scheduled ranking-history snapshot (the Tuesday workflow run).

Loads the site in a headless browser so values come from the site's own model (tiers, projections,
order passes), reads the board with window.SPM.rankingSnapshot(), and adds an entry to
data/rank_history.json for every player whose overall rank, position rank, tier or value changed
since his last entry (same rule as manual edits, so unchanged players get no duplicate point).

Run from the pipeline folder after the projection refresh:
    python snapshot_history.py            # source "S" (scheduled update), timestamp now
    python snapshot_history.py --ts 2026-10-01 --src S
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""
import argparse, datetime, functools, http.server, json, os, socketserver, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HIST = os.path.join(ROOT, "data", "rank_history.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    ap.add_argument("--src", default="S")
    args = ap.parse_args()
    current = json.load(open(HIST)) if os.path.exists(HIST) else {"version": 2, "players": {}}

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
            out = pg.evaluate("""([hist, ts, src]) => {
                const h = SPM.normalizeHistory(hist), n = SPM.addSnapshot(h, SPM.rankingSnapshot(), ts, src);
                return { n, text: SPM.historyText(h) };
            }""", [current, args.ts, args.src])
            b.close()
    finally:
        srv.shutdown()
    if out["n"] or current.get("version") != 2:
        open(HIST, "w").write(out["text"])
    print(f"rank_history.json: {out['n']} player(s) changed ({args.src}, {args.ts})")


if __name__ == "__main__":
    main()
