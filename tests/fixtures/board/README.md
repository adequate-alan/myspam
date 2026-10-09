# Frozen test board

The board as published at commit `ae79eeb` (Oct 13, 2026; Architecture C, value model `state-baseline-v1`), kept as a
deterministic fixture for tests of how the editor, the ranking history and the market layer behave:

- `rankings.csv`: the `RANKINGS_CSV` block (259 players)
- `rank_history.json`, `rank_snapshots/2026-10.json`: the history and exact board snapshots from the same commit

`tests/fixture_board.py` builds the page under test from the **current** `index.html` with only this block swapped in,
and serves these two data files in its place, so the code is always the current code and the board never changes with
a ranking publish. Nothing here is ever written to `index.html` or `data/`; the live rankings stay the only production
data. Tests of data validity (`static_check`, migration identity, the pre-publish checks on the live block) use the
current rankings, not this fixture. Don't edit these files to make a test pass: a behaviour test that needs another
board should build it from this one in the test.
