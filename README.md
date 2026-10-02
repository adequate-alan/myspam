# SPMetrics Fantasy Rankings

Fantasy football rankings and a trade calculator for a 12-team, full-PPR, TE-premium, superflex redraft league. Rankings by Steven ([@SPMetrics](https://github.com/stevenp36)) and Alan; player values come from a model that blends those rankings with this season's usage and betting-market team outlooks.

**Live site:** https://stevenp36.github.io/spmetrics-fantasy/

## How player values work

1. **Positional rank → points per game.** Each rank (WR1, WR2, …) maps to the average points per game that finish produced in 2023–2025 under this league's scoring (pass yd 0.04, pass TD 4, INT −2, rush/rec yd 0.1, TD 6, reception 1, TE reception +0.5, fumble lost −2). Source: [nflverse](https://github.com/nflverse/nflverse-data).
2. **Projection as a second opinion.** This season's targets, carries and pass attempts (converted to expected points), blended with actual points and scaled by each team's rest-of-season scoring outlook from betting lines. The projection re-orders the ranked players at each position; its weight grows with games played.
3. **Value over replacement.** Points above the last starter at the position (full credit) plus points between waiver level and the last starter (25% credit), with replacement and waiver levels set by the league's lineup (1QB 2RB 3WR 1TE 1FLEX 1SF, 6 bench).
4. **Rank order and tiers.** Values never break the positional ranking; players in a tier are pulled together and each tier drop costs value. Scaled so the top player is 10,000.

## Trade verdicts

The calculator compares the adjusted value each side receives: raw player value plus a small roster adjustment (a capped bonus for getting the best player and for taking on fewer roster spots, applied only when player counts differ). The verdict comes from how much more value the side ahead gets:

| Gap | Verdict |
|---|---|
| under 1% | Basically even |
| 1–3% | Fair trade |
| 3–7% | Slight edge |
| 7–12% | Wins the trade |
| 12–20% | Clearly wins |
| 20–30% | Getting a steal |
| 30% and up | Getting robbed |

The exact gap is shown under the verdict, along with the raw player value gap when the roster adjustment changed it. With a Sleeper league connected, verdicts use the team names. Tiers and wording are in `TRADE_VERDICTS` in `index.html`.

## Player details

Click any player's name or photo anywhere on the site (rankings, My Team, team pages, free agents, trade calculator, Trade Finder) to open his details in a pop-up over the current page. Nothing underneath changes: your place in the rankings and any trade you're building stay exactly as they were. Close it with ×, Escape or a click outside. Clicking another player inside the pop-up switches to him (← goes back). On phones it opens as a nearly full-screen panel.

- **Top:** photo, team, position, age, overall rank, position rank, SPMetrics value, points per game, Sleeper owner. Actions: **Add to trade** (goes to the side away from the team that owns him), **Find trades**, **Compare player** (side-by-side, better number in gold) and close.
- **Overview:** ranks, value, season points, PPG, recent games, last 3 and last 5 averages, season trend, next opponent, Sleeper owner and roster status (starting, bench, IR, taxi), plus a weekly points chart.
- **Game log:** each week of 2026, 2025 or 2024 with position-specific columns, byes and missed games. Gold rows are big weeks (1.75× the position's starter line), dim rows are under half of it.
- **Stats:** season totals and usage/efficiency (target share, catch rate, yards per touch/carry/catch, completion %, yards per attempt).
- **Fantasy performance:** weekly points chart for Last 5, Last 10, 2026, 2025 or 2024, with average and starter lines.
- **Ranking history:** overall rank, position rank and value over time from the published snapshots.
- **Trade value:** current value, movement since the last snapshot, similar-value players, trade-up and trade-down targets (players on other teams when a league is connected, with owners) and **Find trades for this player**.

Fantasy points are calculated in the browser from the raw stats, using the connected league's scoring (including yardage bonuses and first downs) or the site's format otherwise.

### Data layers

| Layer | Where | Updated by |
|---|---|---|
| Player identity (Sleeper ID, nflverse ID, name, position, team, birthdate) | `data/sleeper_players.json` | weekly workflow |
| Photos | Sleeper's CDN by Sleeper ID (initials when missing) | – |
| Stats (weekly game logs, schedules) | `data/stats/<season>.json` | weekly workflow (current season) |
| Rankings (rank, position rank, value) | `RANKINGS_CSV` in `index.html` | you (editor) |
| Ranking history | `data/rank_history.json` | each publish |
| League (ownership, scoring, rosters) | Sleeper data in the browser | Connect / Refresh |

The stats refresh never writes to the rankings, and nothing from Sleeper or stats changes your ranks or custom values. Each new season: add it to `STATS_SEASONS` in `index.html` and run `python build_stats.py <season>`.

## Trade calculator modes

**League context** at the top of the calculator picks the mode. Changing it never clears the trade.

- **Universal mode** (*No league context*): the two sides are **You get** and **They get**, and verdicts read from your point of view ("Slight edge to you", "You're getting robbed"). Search any players; base SPMetrics values and the small roster adjustment. Works without Sleeper.
- **League mode** (a synced Sleeper league): pick the two teams (the sides, verdicts and notes then use their Sleeper team names), then click players straight from their real rosters (a player clicked on Team A's roster goes to Team B, and the reverse). *Search any player* still works for hypothetical trades. Values are league-adjusted. Choosing a different league switches the site's active league; players in the trade who aren't on the selected rosters are flagged and kept as hypothetical until you remove them.

In league mode with both teams picked, the calculator answers two questions separately:
1. **Value verdict:** is it fair in SPMetrics value? (the same descriptive verdicts as always)
2. **Roster context:** does it make sense for these two teams? Each team's best lineup is rebuilt before and after the trade in this league's slots (superflex, flex count, TE premium through league values, bench depth, roster spots), giving each a **roster impact** %. The **league-adjusted verdict** is the value margin plus 0.4 × the difference in roster impact, capped at ±4 points, so need can push a fair trade to a slight edge but never overrides a clearly lopsided one. A short written explanation covers positional needs, starters gained or lost, holes and consolidation, and **Lineup changes** lists who becomes RB1, who moves to FLEX or the bench, who gets cut and which starters each team loses.

**Best fits to balance the trade** come from the real roster of the team that's getting more value: closest to fair first, then expendable depth over starters, never a player whose loss leaves a starting spot empty, and at most two-player packages (only when a single player can't do the job about as well).

### Roster needs

Four sliders above the trade (QB, RB, WR, TE) say how your team stands at each position: 1 Desperately need, 2 Need, 3 Average, 4 Good, 5 Set. Every player at that position in the trade, on either side, counts as a multiplier × his value: ×1.08, ×1.04, ×1.00, ×0.96, ×0.92. A position you need helps whichever side receives it, a position you're set at counts for less, and Average changes nothing. The result shows as a **Need adjustment** next to the waiver adjustment. Settings are saved in your browser; the multipliers are `NEED_MULTIPLIERS` in `index.html`. The Trade Finder doesn't use the sliders.

## Trade finder

With a Sleeper league connected, **Trade Finder** searches every other roster for trades around one of your players (or, from another team's player page, ways to get him):
- 1-for-1, 2-for-1, 1-for-2 and 2-for-2 within the chosen value difference, using the trade calculator's adjusted values and verdicts. A second player in a package must be worth at least 20% of the first, so there are no filler add-ons.
- Value closeness comes first. Among close trades, the ones that make both teams' best lineups better rank higher: it fills each team's lineup in this league's slots (superflex, flex, TE premium through league values), counts bench depth, and charges for roster spots when a team takes back more players.
- Each idea shows what you give and get, raw and adjusted values, the difference, the verdict, whether incoming players would start for you, and why it works (position-room ranks before → after for both teams).
- Filters: position wanted, team, max value difference, 1-for-1 only / packages allowed, fair trades only. **Open in trade calculator** loads the idea into the calculator.

## Repository

| Path | What it does |
|---|---|
| `index.html` | The whole site: rankings data (`RANKINGS_CSV`), tier names, value model settings, and the page itself |
| `pipeline/build_curves.py` | Builds the points-by-finish curves and replacement/waiver levels → `curves.json` (rerun only if league settings change) |
| `pipeline/team_ratings.py` | Fits team offense/defense ratings from posted spreads and totals; projects every remaining game |
| `pipeline/project_players.py` | Rest-of-season projections from usage, actual points and team environment → `projections.csv` |
| `pipeline/merge_projections.py` | Writes projection columns into `index.html` for every ranked player |
| `pipeline/build_sleeper_ids.py` | Sleeper player IDs: `data/sleeper_players.json` and the `sleeper_id` column |
| `pipeline/build_stats.py` | Weekly game logs and schedules → `data/stats/<season>.json` (stats only; never touches rankings) |
| `pipeline/stamp_date.py` | Sets the "Updated" date on the site |
| `data/stats/<season>.json` | Weekly stat lines (Sleeper scoring keys) and team schedules for 2024–2026 |
| `data/rank_history.json` | Ranking snapshots, one per publish day: `{sleeper_id: [overall rank, position rank, base value]}` |
| `data/curve_components.json` | Stat breakdown per positional finish (from `build_curves.py`), used for league-adjusted values |
| `.github/workflows/site.yml` | Deploys on every push; every Tuesday it also refreshes projections, player IDs and this season's stats, commits, and redeploys |

## Editor mode (temporary: open to everyone)

While the rankings system is being built, the editing controls are on for every visitor; there is no sign-in to edit. Proper authentication is planned.

- **Reorder:** drag a player by the ⠿ handle or nudge with ▲ ▼, in the **All** view or any position tab. The All rankings (the `rank` column) are the source of truth: position ranks are each player's place among same-position players in the overall order. Moving someone in a position tab swaps him with players at his position, keeping the same overall spots. A player who lands in a new position spot takes that spot's tier.
- **Values** come from each player's position rank (the value model), then are kept in order down the All rankings: if you put a player above someone with a higher value, their values meet in the middle.
- **Custom values:** click any value to type a number (marked **Custom** with a striped bar). **Auto** switches back to the model value for his current rank.
- **Save changes / Cancel changes:** Save keeps your edits in *this browser* (they survive reloads and feed the trade calculator). Cancel throws away unsaved changes. A visitor who edits only changes their own copy, never the live board.
- **Ranking history:** every publish also saves a snapshot of the published board (rank, position rank and base value per player) to `data/rank_history.json`, one per day. Player pages chart it.
- **Publish to live site:** writes the browser-saved edits to `index.html` on GitHub so everyone sees them (site redeploys in about a minute). Publishing needs a GitHub fine-grained token for an account with write access (**Contents: Read and write**, this repository only); the page asks once and remembers it in that browser. Only the edited fields are merged onto the latest version, so the weekly projection refresh is kept.
- **Discard browser edits:** drops everything saved in the browser and shows the live rankings again.

## Sleeper leagues

**Connect Sleeper** (top right) asks for a Sleeper username, lists that account's leagues for the current season, and imports the one you pick. It uses Sleeper's public API, so no password is needed. Everything is kept in the visitor's browser.

Data is kept in three separate layers:
1. **Base rankings:** `RANKINGS_CSV` plus editor edits. Sleeper never changes these.
2. **Sleeper league data:** league settings, scoring, lineup, managers and rosters, saved in the browser (`spm_sleeper`). **Refresh from Sleeper** re-downloads it; rankings and edits are untouched.
3. **League-adjusted values:** calculated on the fly. `data/curve_components.json` holds the per-game stat breakdown behind each positional finish; the site re-scores it with the league's scoring settings, sets replacement and waiver levels from the league's lineup (teams, starters, flex, superflex, bench), and moves each player's base value by the difference between that league model and the base model at his position rank. A league in the base format gets exactly the base values.

With a league connected:
- The header shows the league and its format; click it to switch leagues, refresh, change account or disconnect.
- Rankings get a **Base / League-adjusted** toggle, an owner label on each player (My Team, manager name, FA), and an owner filter. Editing works in the Base view.
- **My Team:** lineup by slot, bench, IR and taxi with overall rank, position rank and value; roster strength by position and power rank (same calculation as the League tab); **Trade with** buttons that open the trade calculator with both rosters.
- **League:** power rankings for every team, strongest to weakest. Team score = the best lineup the team's healthy roster can field in the league's starting slots (SPMetrics values) + 25% of its bench depth; IR and taxi are left out. Each row shows manager, record, PF/PA, team score, best and weakest position (place in the league) and top starters. Click a team for its breakdown: position strength vs the league (QB, RB, WR, TE rooms and bench depth, each with total value, place and difference from the league average), its best lineup, and the roster grouped by position with role, overall rank, position rank and value. Uses whichever view (Base or League-adjusted) is on.
- **Free Agents:** ranked players nobody rosters, sorted by SPMetrics values, filterable by position.
- **Trade calculator:** see *Trade calculator modes* below. Uses the league-adjusted values when that view is on.

Player photos come from Sleeper's image CDN by Sleeper ID (initials show when a photo is missing); manager avatars come from Sleeper too. The site refreshes league data in the background when it's more than 6 hours old.

`data/sleeper_players.json` (names for any rostered player) and the `sleeper_id` column in `RANKINGS_CSV` come from `pipeline/build_sleeper_ids.py` (DynastyProcess player IDs) and are refreshed by the weekly workflow.

## Updating

- **Rankings:** use editor mode on the site, or edit `RANKINGS_CSV` in `index.html` (columns `player, pos, team, rank, pos_rank, tier`, optional `value` for a custom value; `rank` is the overall order) and push.
- **Projections:** automatic every Tuesday. To run it now: Actions → *Build and deploy site* → *Run workflow*.
- **End of season:** after week 17, disable the workflow's schedule (or the whole workflow) under Actions.
