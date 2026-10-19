"""Bring AM SF PPR TE+'s position order in line with AM PPR's published order (Alan, Oct 19).

Normally this happens inside an AM PPR publish (index.html: publishLive → syncOrder, one commit with both boards and both
histories). This script does the same from a checkout, for the first activation (the boards already differed when the
sync was added) or after a hand edit: it loads the page in a headless browser, runs the page's own SPM.syncOrder on the
two published blocks ("spots stay": every SF spot keeps its overall rank, value, tier and tier name; the players fill
them in AM PPR's order; tag tiers and zero values stay with their player), writes the new RANKINGS_CSV block into
index.html and records the change in AM SF PPR TE+'s history and snapshot with SPM.recordPublish (source O, the event
says it came from "ppr"). Nothing else changes; AM PPR and its files are never written.

Run from the pipeline folder:
    python sync_board_order.py               # timestamp now
    python sync_board_order.py --dry-run     # print what would change
    python sync_board_order.py --root /path/to/checkout --ts 2026-10-19T15:00:00.000Z
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""
import argparse, datetime, functools, http.server, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SF_RE = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
PPR_RE = re.compile(r"(const RANKINGS_CSV_PPR = `\n)([\s\S]*?)(\n`;)")
HIST, SNAPS = "data/rank_history.json", "data/rank_snapshots"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--by", default="sync")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    index_path = os.path.join(root, "index.html")
    html = open(index_path, encoding="utf-8").read()
    if len(SF_RE.findall(html)) != 1 or len(PPR_RE.findall(html)) != 1:
        sys.exit("index.html needs exactly one RANKINGS_CSV and one RANKINGS_CSV_PPR block; nothing was changed.")
    sf, ppr = SF_RE.search(html)[2], PPR_RE.search(html)[2]
    hist_path = os.path.join(root, HIST)
    hist = json.load(open(hist_path, encoding="utf-8"))
    month = a.ts[:7]
    snap_path = os.path.join(root, SNAPS, f"{month}.json")
    snaps = json.load(open(snap_path, encoding="utf-8")) if os.path.exists(snap_path) else {"version": 1, "snapshots": []}
    prev = snaps["snapshots"][-1] if snaps["snapshots"] else None
    if prev is None:
        last = next((e for e in reversed(hist.get("events") or []) if e.get("snap") and e["snap"] != month), None)
        if last:
            older = json.load(open(os.path.join(root, SNAPS, f"{last['snap']}.json"), encoding="utf-8"))["snapshots"]
            prev = older[-1] if older else None

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *x):
            pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
            pg = b.new_page()
            pg.add_init_script("try { localStorage.setItem('spm_edit_board', 'sf-tep'); } catch (e) {}")
            pg.route("**/*", lambda r: r.abort() if not r.request.url.startswith(url.rsplit("/", 1)[0]) else r.continue_())
            pg.goto(url)
            pg.wait_for_function("(() => { try { return Object.keys(window.SPM.rankingSnapshot()).length > 0; } catch (e) { return false; } })()", timeout=90_000)
            out = pg.evaluate("""([ppr, sf, hist, snaps, prev, ts, by]) => {
                const s = SPM.syncOrder(ppr, sf);
                if (!s.moved.length) return { moved: [] };
                const errs = SPM.validateRankings(s.csv, sf, new Set(s.moved.map(m => `${m.name}|${m.pos}`.toLowerCase())));
                const h = SPM.normalizeHistory(hist);
                const r = SPM.recordPublish(h, snaps, prev, SPM.snapshotOf(s.csv, "sf-tep"), ts, "O", by, null, "ppr");
                return { moved: s.moved, kept: s.kept, csv: s.csv, errs, msg: SPM.historyMessage(r.ev), changed: r.changed, snapshot: r.snapshot,
                         text: SPM.historyText(h), snap: SPM.boardSnapText(snaps) };
            }""", [ppr, sf, hist, snaps, prev, a.ts, a.by])
            b.close()
    finally:
        srv.shutdown()
    if not out["moved"]:
        print("AM SF PPR TE+ already follows AM PPR's position order: nothing to do."); return
    for m in out["moved"]:
        f, t = m["from"], m["to"]
        print(f"{m['name']:<24} {m['pos']}{f['pos_rank']} #{f['rank']} T{f['tier']} {f['value']:,} -> {m['pos']}{t['pos_rank']} #{t['rank']} T{t['tier']} {t['value']:,}")
    for k in out["kept"]:
        print(f"kept in place: {k['name']} ({k['pos']}): {k['why']}")
    if out["errs"]:
        sys.exit("The synced board didn't pass the pre-publish checks, so nothing was written: " + "; ".join(out["errs"][:3]))
    if a.dry_run:
        return
    m = SF_RE.search(html)
    open(index_path, "w", encoding="utf-8").write(html[:m.start(2)] + out["csv"] + html[m.end(2):])
    if out["changed"]:
        open(hist_path, "w", encoding="utf-8").write(out["text"])
    if out["snapshot"]:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        open(snap_path, "w", encoding="utf-8").write(out["snap"])
    print(f"AM SF PPR TE+ position order follows AM PPR: {len(out['moved'])} players. {out['msg']}")


if __name__ == "__main__":
    main()
