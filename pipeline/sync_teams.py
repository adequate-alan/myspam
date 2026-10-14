"""Keep the AM Board's NFL team column in step with Sleeper (Oct 14 valuation audit).

The board's `team` column was written by hand and nothing refreshed it, so players who changed teams kept their
old one (J.J. McCarthy MIN -> NYG, Mike Washington Jr. MIN -> LV): wrong logos, wrong game lines, and roles from the
depth chart that didn't apply. This updates ONLY that column, matched by Sleeper ID (never by name), from Sleeper's
player database that build_depth_charts.py already fetches. Rank, position rank, tier, value, source and tier name
are never touched, so static_check --frozen-rankings still guards the scheduled run.

Every ranking set's block is kept in step (Oct 14, PR 4 of the boards work: RANKINGS_CSV and RANKINGS_CSV_PPR; the page
reads AM PPR's teams from RANKINGS_CSV by Sleeper ID, so this keeps the PPR block's own column, its snapshots and any
player only that board lists truthful).

Rules: a player Sleeper lists without a team becomes FA; a player Sleeper doesn't know keeps his team; a team code
must be 2-3 capital letters; more than MAX_MOVES changes in one block in one run is treated as a bad response for
that block: its sync is skipped with a warning (the block is left exactly as it was) while every other board still syncs
(Alan, Oct 14: the limit applies to each board on its own).

Use: from build_depth_charts.py --board ../index.html, or  python sync_teams.py <players.json> <index.html>
"""
import json, re, sys

MAX_MOVES = 25
BLOCKS = ("RANKINGS_CSV", "RANKINGS_CSV_PPR")   # every board's block (BOARDS in index.html); a missing optional one is skipped
def block_re(name): return re.compile(r"(const " + name + r" = `\n)([\s\S]*?)(\n`;)")
BLOCK = block_re("RANKINGS_CSV")
TEAM = re.compile(r"^[A-Z]{2,3}$")


def split_csv(line):
    out, cur, q = [], "", False
    for ch in line:
        if ch == '"': q = not q; cur += ch
        elif ch == "," and not q: out.append(cur); cur = ""
        else: cur += ch
    out.append(cur)
    return out


class OverLimit(ValueError):
    """More than MAX_MOVES team changes in one block: that board's sync is skipped."""


def sync_block(html, players, name="RANKINGS_CSV"):
    """One block: returns (new_html, [(name, old, new)]). Raises OverLimit over the limit, ValueError on anything else."""
    rx = block_re(name)
    m = rx.search(html)
    if not m or len(rx.findall(html)) != 1:
        raise ValueError(f"expected exactly one {name} block")
    lines = m.group(2).split("\n")
    cols = split_csv(lines[0])
    ti, si, ni = cols.index("team"), cols.index("sleeper_id"), cols.index("player")
    moves = []
    for k in range(1, len(lines)):
        if not lines[k].strip():
            continue
        row = split_csv(lines[k])
        p = players.get(row[si]) if row[si] else None
        if not isinstance(p, dict):
            continue
        new = p.get("team") or "FA"
        if not TEAM.match(new) or new == row[ti]:
            continue
        moves.append((row[ni], row[ti], new))
        row[ti] = new
        lines[k] = ",".join(row)
    if len(moves) > MAX_MOVES:
        raise OverLimit(f"{len(moves)} team changes in {name} in one run (limit {MAX_MOVES}): not trusting this response")
    return html[:m.start(2)] + "\n".join(lines) + html[m.end(2):], moves


def sync(html, players):
    """The main board's block only (as before): (new_html, [(name, old, new)])."""
    return sync_block(html, players, "RANKINGS_CSV")


def sync_all(html, players, skipped=None):
    """Returns (new_html, {block: [(name, old, new)]}). The main block must exist; other boards' blocks are optional.
    A block over the limit is left exactly as it was and named in `skipped` ({block: reason}); the others still sync.
    A malformed page raises ValueError and nothing is written."""
    out = {}
    for name in BLOCKS:
        if name != "RANKINGS_CSV" and not block_re(name).search(html):
            continue
        try:
            html, out[name] = sync_block(html, players, name)
        except OverLimit as e:
            if skipped is not None: skipped[name] = str(e)
    return html, out


def apply(path, players):
    html = open(path, encoding="utf-8").read()
    skipped = {}
    new, by_block = sync_all(html, players, skipped)
    if new != html:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    for name, moves in by_block.items():
        for n, a, b in moves:
            print(f"Team updated from Sleeper ({name}): {n} {a} -> {b}")
        print(f"{name} teams: {len(moves)} change(s)")
    for name, why in skipped.items():   # a GitHub Actions warning annotation, so the run summary shows it
        print(f"::warning title=Team sync skipped for {name}::{why}; {name} left unchanged, other boards synced")
    return by_block


if __name__ == "__main__":
    apply(sys.argv[2], json.load(open(sys.argv[1])))
