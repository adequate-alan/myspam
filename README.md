# SPMetrics Fantasy Rankings

Fantasy football rankings and a trade calculator for a 12-team, full-PPR, TE-premium, superflex redraft league. Rankings by Steven ([@SPMetrics](https://github.com/stevenp36)) and Alan; player values come from a model that blends those rankings with this season's usage and betting-market team outlooks.

**Live site:** https://stevenp36.github.io/spmetrics-fantasy/

## How player values work

1. **Positional rank → points per game.** Each rank (WR1, WR2, …) maps to the average points per game that finish produced in 2023–2025 under this league's scoring (pass yd 0.04, pass TD 4, INT −2, rush/rec yd 0.1, TD 6, reception 1, TE reception +0.5, fumble lost −2). Source: [nflverse](https://github.com/nflverse/nflverse-data).
2. **Projection as a second opinion.** This season's targets, carries and pass attempts (converted to expected points), blended with actual points and scaled by each team's rest-of-season scoring outlook from betting lines. The projection re-orders the ranked players at each position; its weight grows with games played.
3. **Value over replacement.** Points above the last starter at the position (full credit) plus points between waiver level and the last starter (25% credit), with replacement and waiver levels set by the league's lineup (1QB 2RB 3WR 1TE 1FLEX 1SF, 6 bench).
4. **Rank order and tiers.** Values never break the positional ranking; players in a tier are pulled together and each tier drop costs value. Scaled so the top player is 10,000.

## Repository

| Path | What it does |
|---|---|
| `index.html` | The whole site: rankings data (`RANKINGS_CSV`), tier names, value model settings, and the page itself |
| `pipeline/build_curves.py` | Builds the points-by-finish curves and replacement/waiver levels → `curves.json` (rerun only if league settings change) |
| `pipeline/team_ratings.py` | Fits team offense/defense ratings from posted spreads and totals; projects every remaining game |
| `pipeline/project_players.py` | Rest-of-season projections from usage, actual points and team environment → `projections.csv` |
| `pipeline/merge_projections.py` | Writes projection columns into `index.html` for every ranked player |
| `pipeline/stamp_date.py` | Sets the "Updated" date on the site |
| `.github/workflows/site.yml` | Deploys on every push; every Tuesday it also refreshes projections, commits, and redeploys |

## Editor mode (temporary: open to everyone)

While the rankings system is being built, the editing controls are on for every visitor; there is no sign-in to edit. Proper authentication is planned.

- **Reorder:** drag a player by the ⠿ handle or nudge with ▲ ▼, in the **All** view or any position tab. The All rankings (the `rank` column) are the source of truth: position ranks are each player's place among same-position players in the overall order. Moving someone in a position tab swaps him with players at his position, keeping the same overall spots. A player who lands in a new position spot takes that spot's tier.
- **Values** come from each player's position rank (the value model), then are kept in order down the All rankings: if you put a player above someone with a higher value, their values meet in the middle.
- **Custom values:** click any value to type a number (marked **Custom** with a striped bar). **Auto** switches back to the model value for his current rank.
- **Save changes / Cancel changes:** Save keeps your edits in *this browser* (they survive reloads and feed the trade calculator). Cancel throws away unsaved changes. A visitor who edits only changes their own copy, never the live board.
- **Publish to live site:** writes the browser-saved edits to `index.html` on GitHub so everyone sees them (site redeploys in about a minute). Publishing needs a GitHub fine-grained token for an account with write access (**Contents: Read and write**, this repository only); the page asks once and remembers it in that browser. Only the edited fields are merged onto the latest version, so the weekly projection refresh is kept.
- **Discard browser edits:** drops everything saved in the browser and shows the live rankings again.

## Updating

- **Rankings:** use editor mode on the site, or edit `RANKINGS_CSV` in `index.html` (columns `player, pos, team, rank, pos_rank, tier`, optional `value` for a custom value; `rank` is the overall order) and push.
- **Projections:** automatic every Tuesday. To run it now: Actions → *Build and deploy site* → *Run workflow*.
- **End of season:** after week 17, disable the workflow's schedule (or the whole workflow) under Actions.
