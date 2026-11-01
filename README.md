# Adequate · Fantasy Football Rankings

Fantasy football rankings, league-adjusted values and trade tools for redraft leagues. **Adequate** is the site; **AM** is Alan's ranking system behind it (AM Board, AM rank, AM value). Rankings, tiers and values are set by hand by Alan ([adequate-alan](https://github.com/adequate-alan)) and stored in the page; everything league-specific is derived from them in the visitor's browser.

**Live site:** https://adequate-alan.github.io/myspam/ (rankings: `#rankings`)

**Working on the code (people or AI assistants): read [`CLAUDE.md`](CLAUDE.md) first.** It is the authoritative handoff: product rules that must not be undone, the value model, data flow, publishing, scheduled jobs, tests and CI. This README is a short overview and defers to it wherever they differ. [`PRODUCT.md`](PRODUCT.md) describes who the site is for; [`DESIGN.md`](DESIGN.md) is the visual system (tokens, type, components).

## What's on the site

- **Rankings** with two boards: **AM SF PPR TE+** (12-team Superflex, full PPR, TE premium +0.5, positional tiers) and **AM PPR** (12-team 1QB, full PPR, overall tiers). A connected league picks its board by QB format. Views: **AM Board** (the stored values) and **League-adjusted** (re-priced for your league or custom format), Week / Season stat tables, production and Market edge sorts, risers and fallers, Ranking insights.
- **Player drawer:** Overview (AM rank and value, ROS PPG, Next 4, this week's matchup), Game Log, Schedule, Stats, Fantasy Performance, Ranking History, Trade Value (with FantasyCalc / Flock market comparison), Depth Chart, Practice Report, Compare.
- **My Team**, and a **League** hub (Power Rankings, Standings with playoff odds, Matchups, Rosters, Transactions with Then vs Now trade verdicts, Waiver Wire with Waiver upgrades) for Sleeper leagues; ESPN, Yahoo and other sites import by API or paste.
- **Trade Finder** (Shop my players, Target a player, Find targets, Any team; Market Leverage) and **Trade Calculator** (2- or 3-team; raw and package-adjusted value, Roster Impact, Trade rationale, Acceptance Plausibility, Balance this trade).
- An **editor** (currently open to every visitor) for reordering, re-tiering and valuing players; only a GitHub token with write access to this repo can publish.

## How values work (summary)

- **Values are stored state** (since Oct 12, 2026). Each player's AM value is the `value` column of the board's CSV block in `index.html`; loading the page never recomputes it. An edit reprices only the player you touch, on his position's curve, fitted between his untouched neighbours. Values always descend down the overall rank, and no two players share a value (except 0). Details: CLAUDE.md §2.4–2.5.
- **League-adjusted values** are computed in the browser from the board: scoring re-scores points-by-finish curves, league size and lineup set replacement levels, tiers are re-priced as blocks with eased boundaries, and the board's order inside each position is always kept. A league in the board's own format gets exactly the board's values. Nothing here is ever written back. Details: CLAUDE.md §9.
- **Projections** (rest-of-season PPG, Next 4, the weekly projection) come from AM's stat-line model (`pipeline/ros_model.py`), scored per league in the browser. They never change ranks, tiers or base values. Details: CLAUDE.md §8.
- **Market data** (FantasyCalc, Flock) is a separate reference layer shown beside AM values, never blended into them.

## Trade verdicts

The headline compares the league-adjusted value each side receives, read two ways (raw and package-adjusted), against at least an average starter's value in that format. When the readings disagree the verdict says so (**Split verdict**, **Package-sensitive**). Gap bands, from `TRADE_VERDICTS` in `index.html`:

| Gap | Verdict |
|---|---|
| under 1% | Basically even |
| 1–3% | Fair trade |
| 3–7% | Slight edge |
| 7–12% | Wins the trade |
| 12–20% | Clearly wins |
| 20–30% | Getting a steal |
| 30% and up | Getting robbed |

Roster needs never change who wins: Roster Impact, Trade rationale and Acceptance Plausibility are separate reads (CLAUDE.md §2.18).

## Running it locally

One static HTML file plus JSON data; no build step, framework or npm.

```bash
git clone https://github.com/adequate-alan/myspam.git && cd myspam
python3 -m http.server 8000          # open http://localhost:8000/
```

Tests: `python3 tests/run_ci.py fast` (static, pipeline and smoke checks, about 30 s). The browser suites in `tests/` (about 60) run in CI by release lane; see CLAUDE.md §3.

## Data and jobs

| Data | Where | Updated by |
|---|---|---|
| Rankings (rank, position rank, tier, value, source) | `RANKINGS_CSV` (AM SF PPR TE+) and `RANKINGS_CSV_PPR` (AM PPR) in `index.html` | the editor's Publish; scheduled jobs change only the team column |
| Ranking history and exact board snapshots | `data/rank_history.json`, `data/rank_snapshots/`, `data/boards/ppr/` | each publish (same commit) and the Tuesday job |
| Game stats, schedules, injury and practice reports | `data/stats/<season>.json` | stats runs after every NFL game day, plus midweek and Saturday injury/practice runs |
| Projections and stored weekly forecasts | `data/projections.json`, `data/projections/<season>/`, `proj_*` columns | weekly job (Tuesdays, with a catch-up if GitHub drops the run) |
| Who is expected to play, depth charts | `data/roles.json`, `data/depth_charts.json` | every stats run |
| Expected points from opportunity (xFP) | `data/opportunity/<season>.json` | every stats run |
| Market values | `data/market/redraft.json` (FantasyCalc), `data/market/flock_*.json` (Flock) | every 8 hours and every stats run; Flock lists published from the site's list manager |
| Player identity | `data/sleeper_players.json`, `data/platform_ids.json` | weekly job |
| League data (rosters, scoring, matchups, transactions) | the visitor's browser only (`spm_sleeper`) | Connect / Refresh |

Every scheduled run is in `.github/workflows/site.yml`; the full schedule and what each run writes is CLAUDE.md §8. Stats and data refreshes never change rankings, tiers or values.

## Publishing and deploying

- **Rankings:** edit in the site's editor, **Save changes**, then **Publish to live site** (or Save publishes directly once the browser holds a token). A publish writes the board's block, its history and its snapshot in one commit through GitHub's Git Data API. Tokens: a fine-grained token for `adequate-alan/myspam` with **Contents: Read and write** (plus **Actions: Read and write** for the Refresh stats button), or a classic token with `repo` scope. Tokens stay in that browser (this tab only unless **Remember on this browser** is ticked) and never go in the repo. Details: CLAUDE.md §6.
- **Code:** push to `main` (see CLAUDE.md for the workflow). GitHub Actions checks every push through a release lane (fast, targeted or full) and then deploys to GitHub Pages; Pages is served from that workflow, not from a branch. `BUILD_ID` stays `"dev"` in the repo and the deploy stamps a hash of the page's code into it, so open tabs get "A new version of Adequate is available" only when the code changed. Never edit it by hand.

## Hosting and a custom domain

Every asset, data file and link is a relative path, so the site works unchanged at any address. The public address appears only in the `canonical` link and `og:url`. To move to a custom domain: point DNS at GitHub Pages, set the domain under Settings → Pages (then **Enforce HTTPS**), and update those two lines. Browser-saved data (`spm_*`: leagues, theme, editor token, unpublished edits) is per web address, so publish browser edits before switching.

## History

Adequate began as **SPAM** (later **AM**) on the shared `spamfantasy/spamfantasy.github.io` and was split into this repository on Oct 8, 2026 (history kept); the brand became Adequate on Oct 9. Older names survive only in code identifiers and the `spm_` storage keys, which are deliberately not renamed (renaming them would wipe visitors' saved data). CLAUDE.md keeps the dated decision log.
