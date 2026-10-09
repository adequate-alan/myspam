"""The frozen test board (Alan, Oct 13): a committed, deterministic Architecture C board for tests of HOW the editor,
the history and the market layer behave, so Alan's ranking publishes never break them.

Rule: tests of how Adequate works (moves, tier moves, value edits, publishing, history, market comparisons) run on this
fixture; tests of data validity (static_check, the migration identity, the pre-publish checks on the live block) keep
using the current rankings in index.html. The fixture is the board as published at ae79eeb (Oct 13, before the six
publishes of Oct 13/14): tests/fixtures/board/rankings.csv (the RANKINGS_CSV block), rank_history.json and
rank_snapshots/2026-10.json from the same commit. It is read only here and never written to index.html or data/.

    import fixture_board as FB
    FB.CSV            the fixture rankings block (str, no trailing newline)
    FB.rows()         the block as csv.DictReader rows
    FB.html()         the current index.html (bytes) with only the rankings block replaced by the fixture: the code
                      under test is always the current code, the board is always the fixture
    FB.files()        {"data/rank_history.json": bytes, "data/rank_snapshots/2026-10.json": bytes}
    FB.route(page, base)   Playwright routes so `base/` and `base/index.html` serve FB.html() and the two data files
                      serve the fixture copies (base = the local server's origin); everything else (stats, players,
                      market files) is still served from the repo as usual
"""
import csv, io, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "tests", "fixtures", "board")
CSV_RE = re.compile(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")

CSV = open(os.path.join(DIR, "rankings.csv"), encoding="utf-8").read().rstrip("\n")
FILES = {"data/rank_history.json": os.path.join(DIR, "rank_history.json"),
         "data/rank_snapshots/2026-10.json": os.path.join(DIR, "rank_snapshots", "2026-10.json")}

def rows():
    return list(csv.DictReader(io.StringIO(CSV)))

def html(src=None):
    """index.html (bytes; the repo's unless `src` is given) with its RANKINGS_CSV block replaced by the fixture board."""
    if src is None: src = open(os.path.join(ROOT, "index.html"), "rb").read()
    if isinstance(src, str): src = src.encode("utf-8")
    blocks = CSV_RE.findall(src)
    if len(blocks) != 1: raise RuntimeError(f"index.html holds {len(blocks)} RANKINGS_CSV blocks, expected exactly one")
    m = CSV_RE.search(src)
    return src[:m.start(2)] + CSV.encode("utf-8") + src[m.end(2):]

def files():
    return {k: open(p, "rb").read() for k, p in FILES.items()}

def route(page, base):
    """Serve the fixture page and data files on `base` (a Playwright Page or BrowserContext)."""
    body = html(); data = files()
    page.route(re.compile(re.escape(base) + r"/(index\.html)?([?#].*)?$"),
               lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=body))
    def data_file(r):
        path = "data/" + r.request.url.split("/data/")[1].split("?")[0]
        if path in data: r.fulfill(status=200, content_type="application/json", body=data[path])
        elif path.startswith("data/rank_snapshots/"): r.fulfill(status=404, content_type="application/json", body=b"{}")   # the fixture has one month
        else: r.continue_()
    page.route(re.compile(re.escape(base) + r"/data/(rank_history\.json|rank_snapshots/[^/?]+\.json).*"), data_file)
