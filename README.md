# Adequate · Fantasy Football Rankings

Fantasy football rankings and a trade calculator for a 12-team, full-PPR, TE-premium, superflex redraft league. Rankings by Alan ([adequate-alan](https://github.com/adequate-alan)), starting from the board he built with Steven ([stevenp36](https://github.com/stevenp36)); player values come from a model that blends those rankings with this season's usage and betting-market team outlooks.

**Live site:** https://adequate-alan.github.io/myspam/ (rankings: https://adequate-alan.github.io/myspam/#rankings)

**Working on the code (people or AI assistants):** start with [`CLAUDE.md`](CLAUDE.md), the project handoff: product rules, data flow, publishing, scheduled jobs and what must never be overwritten.

### Hosting and moving to a custom domain
The site is one static `index.html` served by GitHub Pages from the `main` branch of `adequate-alan/myspam` (copied from `spamfantasy/spamfantasy.github.io` on Oct 8, 2026). Every asset, data file, script and link is a relative path (`data/…`, `favicon.svg`, `manifest.webmanifest`, `#rankings`), so the site works unchanged at `adequate-alan.github.io/myspam/`, at the root of a user site, or at the root of any domain. The public address appears in only two places, the `canonical` link and `og:url` in the page head. To move to a custom domain later:
1. Buy the domain and point DNS at GitHub Pages (a `CNAME` record for `www` to `adequate-alan.github.io`, and/or `A` records for the apex as listed in GitHub's Pages docs).
2. In the repo: Settings → Pages → Custom domain, enter it (GitHub adds a `CNAME` file to the repo), then tick **Enforce HTTPS** once it's offered.
3. Update the `canonical` and `og:url` lines to the new address.
Browser-saved data (league connection, theme, editor token and unpublished edits) is stored per web address, so visitors and editors start fresh on a new domain: publish any browser edits before switching.

## Updates reaching visitors

GitHub Pages can keep serving a browser its cached copy of the page for a few minutes after an update. `BUILD_ID` near the top of the main script changes with every code update; a few seconds after the page loads (and whenever the tab comes back into view, at most every 5 minutes) the site checks the live copy and, if it's newer, shows "A new version of SPAM is available" with a Refresh button. Update `BUILD_ID` whenever the code changes (rankings edits published from the editor don't need it).

## Brand

The product name is **SPAM** (SPAM Rankings, SPAM Values, SPAM Board). The wordmark is one word in the brand color (deep burgundy in light mode, cream in dark mode) with a small accent square (coral / warm gold). `SITE.name` and `SITE.author` at the top of `index.html` set it; the favicon is `favicon.svg` and the install name comes from `manifest.webmanifest`.

## Light and dark themes

Dropdowns: every `<select>` on the site is upgraded on load to a themed SPAM dropdown (`SpamSelect`, at the end of `index.html`). The native select stays hidden in the page and keeps the value, so code keeps using `.value` and `change` events. Groups become section labels, lists of 12+ options get a search box, and the menu supports arrow keys, Home/End, type-ahead, Enter, Escape and click-outside. Add `data-native-select` on a container to opt out.

The sun/moon button in the header switches between light mode (warm cream + burgundy) and dark mode (near-black + burgundy surfaces + cream + warm gold). The choice is saved in the browser (`spm_theme`) and applied before the page draws, so every tab, dialog, dropdown, table, chart and the editor match on every load; with no saved choice the device's light/dark setting decides.

All colors come from one set of theme tokens at the top of the stylesheet (`:root` for dark, `:root[data-theme="light"]` for light): page background, header, surface, raised surface (modals and dropdowns), table header, row hover, tier rows, controls, text (primary, strong, secondary, muted), headings, borders, primary and secondary accents, hover and active states, buttons, danger, editor panels, the QB/RB/WR/TE colors, shadows and the modal backdrop. Older names used across the stylesheet (`--bg`, `--surface`, `--gold`, `--cream`…) are aliases of those tokens. Charts draw with the same variables, so they switch with the theme. To adjust a color, change it in the token block for that theme.

## How player values work

1. **Positional rank → points per game.** Each rank (WR1, WR2, …) maps to the average points per game that finish produced in 2023–2025 under this league's scoring (pass yd 0.04, pass TD 4, INT −2, rush/rec yd 0.1, TD 6, reception 1, TE reception +0.5, fumble lost −2). Source: [nflverse](https://github.com/nflverse/nflverse-data).
2. **Projection as a second opinion.** This season's targets, carries and pass attempts (converted to expected points), blended with actual points and scaled by each team's rest-of-season scoring outlook from betting lines. The projection re-orders the ranked players at each position; its weight grows with games played.
3. **Value over replacement.** Points above the last starter at the position (full credit) plus points between waiver level and the last starter (25% credit), with replacement and waiver levels set by the league's lineup (1QB 2RB 3WR 1TE 1FLEX 1SF, 6 bench).
4. **Tiers first, then rank order.** Tiers decide how big the gaps are: each positional tier is pulled 80% of the way to its average (`tierBlend`), and no tier spans more than 15% top to bottom (`tierMaxSpread`), so tiermates stay close however many rank spots apart they are. The real drops happen where a tier ends (at least 5%, `tierMinDrop`). Rank order inside a tier sets the order and the small gaps. The overall board can nudge a value by at most 2% (`overallMaxShift`), so where your overall order and your tiers disagree (e.g. an RB tier-2 player ranked overall below a QB tier-3 player), the tier value wins and the All list can show a higher value below a lower one. Scaled so the top player is 10,000.
5. **Other formats keep your tiers.** A league or hand-picked settings re-price each tier as a block (the average of what its rank spots are worth in that format vs the base board), and everyone in the tier moves by the same factor. The format changes how much a tier is worth, never where the drops are or how close tiermates sit.

## Auto-ranked players (the board's tail)

The board has two kinds of players, marked in the `source` column of the rankings CSV:

- **manual**: the players you ranked yourself (overall #1–183 when this was added). They are locked: nothing automatic ever moves or re-values them.
- **auto**: supplemental players (70 added 2026-10-02: backup and stopgap QBs for superflex, rotational and handcuff RBs, WR3/WR4 types, starting and emerging TEs) ranked underneath every manual player, from #184 down. They get a position rank, tier, value, team and Sleeper ID like everyone else and appear everywhere on the site (rankings, search, player pages, trade calculator, trade finder, free agents, league rosters, power rankings, comparisons).

How the tail is valued:
- Auto players run through the same curve and tiers; their tiers continue each position's tier numbers under yours (QB 7–9, RB 11–13, WR 10–12, TE 7–9). They are handled separately from your players, so adding them changes none of your values: projections only re-order auto players among auto spots, rank order never lets an auto player pull one of yours down, and the overall-order pass stops where the tail starts.
- Deep in a position the curve reaches zero (below waiver level), so the tail also has a floor: it starts just under the lowest value ranked above it and eases down 2.2% per spot (`autoDecay`). In superflex the curve still values backup QBs, so the first few auto QBs keep a real value.
- In other formats and leagues, each position's tail moves by the same share as your last player at that position and stays under him; overall, the tail is always listed after every manual player.

Editing: auto players show an **Auto** tag in editor mode and can be dragged or nudged like anyone. The player you move, or whose value you set, becomes **manual** when you save (players who only shift because someone else moved stay auto; one moved back to exactly where he was stays auto).

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

## Player stats refresh
Each player page has a **Depth Chart** tab: his NFL team's depth chart from Sleeper (offense by default with him highlighted and who's ahead of him; "Full depth chart" adds the line, defense and special teams; Sleeper's injury status on each player). `pipeline/build_depth_charts.py` writes `data/depth_charts.json` from Sleeper's player database with every stats refresh.

Player game logs, season totals, fantasy points and performance charts come from `data/stats/<season>.json` (`pipeline/build_stats.py`, nflverse). A stats-only run of the site workflow fires after every NFL game day (Friday after Thursday night, Sunday after Saturday games, Monday after Sunday, Tuesday after Monday night, each with a retry, plus Thursday for stat corrections). It only rewrites the stats file; rankings, tiers and values are never touched. The Tuesday job still refreshes projections and the ranking-history snapshot. Player pages show "Stats updated …" and, for editors with a GitHub token that has **Actions: Read and write**, a **Refresh stats** button that starts the stats-only run.

## Ranking history

Every player's Ranking History (player pop-up → Ranking history) is a log of **committed changes**, stored in `data/rank_history.json` as `[timestamp, overall rank, position rank, tier, base SPAM value, source]` per player:
- **Manual edit:** when you commit with **Save changes**, every player whose overall rank, position rank, tier or value changed gets one entry at his final spot (dragging around before saving doesn't count; several moves = one entry). Saved entries show "not published" in your browser and go into the shared file with **Publish to live site** (along with anything else that changed). A second edit published later the same day is a second entry. **Discard browser edits** drops unpublished entries too.
- **Scheduled update:** the Tuesday workflow loads the site in a headless browser and runs `pipeline/snapshot_history.py`, adding an entry only for players whose rank, tier or value changed since their last entry.
- **Published update:** any other published change (e.g. a value-model update).
No duplicates: a player gets a new entry only when his overall rank, position rank or tier changed, or his value moved by at least 10 points and 0.5% (`HISTORY_VALUE_MIN`). The charts use every entry; the table shows the date and time, both rank moves, tier, value change and source.

## Player details

Click any player's name or photo anywhere on the site (rankings, My Team, team pages, free agents, trade calculator, Trade Finder) to open his details in a pop-up over the current page. Nothing underneath changes: your place in the rankings and any trade you're building stay exactly as they were. Close it with ×, Escape or a click outside. Clicking another player inside the pop-up switches to him (← goes back). On phones it opens as a nearly full-screen panel.

- **Top:** photo, team, position, age, overall rank, position rank, SPAM Value, points per game, Sleeper owner. Actions: **Add to trade** (goes to the side away from the team that owns him), **Find trades**, **Compare player** (side-by-side, better number in gold) and close.
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

The toolbar at the top holds the league picker and, in league mode, the two team pickers. Changing them never clears the trade.

Layout, in order: the two sides (team name, total, players, search, a collapsed **Add from roster** picker and a subtle *Needs / Strong* line), then the verdict (label, value difference, one-line explanation, balance bar). **Balance this trade** opens 3–4 suggestions on request. Three collapsed sections hold the details: **Why?** (plain-English reasoning), **Roster impact** (roster fit, lineup changes and your roster-need sliders) and **Value breakdown** (raw values, best-player bonus, waiver adjustment, roster needs, adjusted totals). Small ⓘ icons explain the math.

- **Universal mode** (*No league context*): the two sides are **You get** and **They get**, and verdicts read from your point of view ("Slight edge to you", "You're getting robbed"). Search any players; base SPAM Values and the small roster adjustment. Works without Sleeper.
- **League mode** (a synced Sleeper league): pick the two teams (the sides, verdicts and notes then use their Sleeper team names), then click players straight from their real rosters (a player clicked on Team A's roster goes to Team B, and the reverse). *Search any player* still works for hypothetical trades. Values are league-adjusted. Choosing a different league switches the site's active league; players in the trade who aren't on the selected rosters are flagged and kept as hypothetical until you remove them.

In league mode with both teams picked, the calculator answers two questions separately:
1. **Value verdict:** is it fair in SPAM Value? (the same descriptive verdicts as always)
2. **Roster context:** does it make sense for these two teams? Each team's best lineup is rebuilt before and after the trade in this league's slots (superflex, flex count, TE premium through league values, bench depth, roster spots), giving each a **roster impact** %. The **league-adjusted verdict** is the value margin plus 0.4 × the difference in roster impact, capped at ±4 points, so need can push a fair trade to a slight edge but never overrides a clearly lopsided one. A short written explanation covers positional needs, starters gained or lost, holes and consolidation, and **Lineup changes** lists who becomes RB1, who moves to FLEX or the bench, who gets cut and which starters each team loses.

**Best fits to balance the trade** come from the real roster of the team that's getting more value: closest to fair first, then expendable depth over starters, never a player whose loss leaves a starting spot empty, and at most two-player packages (only when a single player can't do the job about as well).

### Team-specific value (league mode)

A player's SPAM Value never changes, but what he's worth **to a roster** depends on whether he'd start there. With a league and both teams picked, every incoming player gets a team-specific value from his role in the new lineup, and every outgoing player a cost from his role before the trade (`TEAM_FIT` in `index.html`, capped at 0.60–1.10 so a good player never becomes worthless):

| Role | Incoming | Outgoing |
|---|---|---|
| Big upgrade at a weak spot, or the new QB/TE/RB1/WR1 | ×1.06 (+0.03 for a TE in TE premium) | – |
| Starter at QB/RB/WR/TE | ×1.00 | ×1.00 (×1.05 if it leaves a hole) |
| Superflex / FLEX starter | ×0.98 / ×0.93–1.00 | ×0.95 |
| Bench, first in line | ×0.82 | ×0.85 |
| Bench, one backup ahead | ×0.72 | ×0.75 |
| Buried | ×0.62 | ×0.65 |
| QB3 in superflex / backup QB in 1QB | ×0.74 / ×0.62 | – |
| No roster spot | ×0.60 | – |

The calculator shows both layers: the raw (market) difference and each team's **roster-adjusted** net. When they disagree the headline says so ("Fair on value, bad fit for X"), with the reason ("Geno Smith would be X's QB3 and wouldn't start…"). Each incoming player shows "To {team}: value · role". **Market value / League fit** switches the totals, balance bar and player values between the two. *Value breakdown* and *Roster impact* list every player's team-specific value. The Trade Finder ranks Best Match by roster-adjusted value (both teams must get useful players), drops trades where one side's roster-adjusted net is worse than −20%, and shows both layers on every card.

### Roster needs

Four sliders under **Roster impact** (QB, RB, WR, TE) say how your team stands at each position: 1 Desperately need, 2 Need, 3 Average, 4 Good, 5 Set. Every player at that position in the trade, on either side, counts as a multiplier × his value: ×1.08, ×1.04, ×1.00, ×0.96, ×0.92. A position you need helps whichever side receives it, a position you're set at counts for less, and Average changes nothing. The result shows as a **Need adjustment** next to the waiver adjustment. Settings are saved in your browser; the multipliers are `NEED_MULTIPLIERS` in `index.html`. The Trade Finder doesn't use the sliders.

## Trade finder

A league-wide trade discovery tool (needs a connected Sleeper league).

- **Player:** *My team* (your roster), *Any player* (search the whole SPAM database; each result shows who owns him) or *By team* (pick a team, then a player).
- **From team** is the team whose side the finder takes. It defaults to the player's owner, so picking a player on Gabriel's team finds trades *Gabriel* could make with him. Pick a different team to find ways that team could get him from his owner. **Against** limits the partner to one team.
- **Position wanted** and **Trade type**: 1-for-1, 1-for-2, 2-for-1 or All packages (all of those plus 2-for-2), counted from the starting team's side (1-for-2 = it gives one player and gets two). With a 2-player package picked, only the shapes that fit it are available. **More filters:** max value difference and fair trades only.
- **Sort:** best match, fairest, best for the starting team, biggest roster improvement, 1-for-1 first, fewest players.
- Value closeness comes first; among close trades, the ones that make both teams' best lineups better rank higher (league slots, superflex, flex count, TE premium through league values, bench depth, roster spots). A second player in a package must be worth at least 20% of the first.
- Each card leads with the partner, what each side gives and receives (with the owner of every player), the verdict, the value difference and a one-line reason. **View full analysis** shows position-room ranks before → after, lineup roles and raw/adjusted values. **Open in trade calculator** loads the idea.
- **Include 3-team trades** (off by default) adds 1-for-1-for-1 ideas below the normal ones, only when every team's lineup improves and a straight 2-team swap wouldn't work for the partner (it has no use for what the starting team sends, but a third team does).

## 3-team trades in the calculator

**+ Add third team** (under the two cards) adds Team C; **Remove third team** goes back to two. Each player's row gets a **from** menu for the team sending him (in league mode it defaults to his owner), and roster pickers have a button for each destination. Every team is judged on its own: value received vs value sent, its own verdict (Slight win, Fair, Clear loss…), roster impact and lineup changes in league mode, and balancing suggestions redirect players from the other two teams to the team giving up the most.

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
- **Auto players** (see *Auto-ranked players*) carry an **Auto** tag; moving one or setting his value makes him manual when you save.
- **Tiers (QB / RB / WR / TE tabs):** hover a tier header to rename it (click the name and type anything), add a tier above or below, or delete it (you choose whether its players join the tier above or below; nothing is dropped). New tiers start empty: drag players onto the header or the dashed "Empty tier" row. Dropping a player next to someone puts him in that player's tier. Tier numbers and names (`tier_name` column) are saved and published like ranks, and tier moves show up in Ranking History. Empty tiers only last until you save. Tags such as Hurt use tier numbers 90+.
- **Custom vs official:** a typed value shows **Custom** (striped bar, **Auto**/**Reset** button) only until it's published. After publishing it is the player's official SPAM value and looks like any other; edit it again and it shows Custom until the next publish (**Reset** goes back to the published value).
- **Custom values:** click any value to type a number (marked **Custom** with a striped bar). **Auto** switches back to the model value for his current rank.
- **Save changes / Cancel changes:** Save keeps your edits in *this browser* (they survive reloads and feed the trade calculator). Cancel throws away unsaved changes. A visitor who edits only changes their own copy, never the live board.
- **Ranking history:** every publish also saves a snapshot of the published board (rank, position rank and base value per player) to `data/rank_history.json`, one per day. Player pages chart it.
- **Saving publishes automatically** once this browser is connected to GitHub: Save changes records the ranking history and publishes straight to the live site, so a save becomes the new master rankings everywhere (rankings, trade calculator, trade finder, league values, power rankings, player pages). Without a token, Save keeps edits in the browser until you publish.
- **Publish to live site:** writes the browser-saved edits to `index.html` on GitHub so everyone sees them (site redeploys in about a minute). Publishing needs a GitHub fine-grained token for an account with write access (**Contents: Read and write**, this repository only); the page asks once and remembers it in that browser. Only the edited fields are merged onto the latest version, so the weekly projection refresh is kept.
- **Discard browser edits:** drops everything saved in the browser and shows the live rankings again.

## League settings (no league connected, or Custom format)

With a league connected, League settings offers **Synced league** (the league's own settings) or **Custom format** (pick everything by hand; your rosters stay, only values change). The active setup is shown above the rankings. Options: league size 6–32, 1QB / Superflex (1 or 2 spots) / 2QB, RB/WR/TE/FLEX starters, bench, points per catch (standard, half, full or custom), TE premium amount, and passing/turnover/first-down scoring. League size and lineup set replacement level, so the same player is worth more in a deep league than a shallow one; tiers are priced as blocks.

**League settings** (top right) lets anyone pick their format without connecting a league: teams, 1QB / superflex / 2QB, RB/WR/TE/FLEX starters, bench, points per catch, TE premium, passing TD and yardage points, interceptions, fumbles lost and first-down points, plus one-click presets. The rankings, values, player pages and trade calculator then use those settings. The choice is saved in the browser and in the page address (`?fmt=…`), so a shared link opens with the same settings. A connected league's own settings always take over.

How values and order change for any non-base settings (league or hand-picked), tunable in `FORMAT_ADJUST` at the top of `index.html`:
1. **Tier values** move with the scoring and lineup (re-scored value curves, replacement and waiver levels), one tier at a time: every player in a tier moves by the same factor, so tiermates stay as close as on the board and the drops stay at the tier breaks. This step never reorders players within a position.
2. **A personal nudge** per player: his last 17 games are scored with the league's settings and with the site's, compared with his position's average, shrunk toward zero for small samples and capped at ±10%. A back who gets most of his points from catches loses a little in standard scoring, etc.
3. **Order stays the SPAM Board** unless a player's adjusted value passes the player above him by more than 3%, and nobody moves more than 2 spots within his position. Across positions the same 3% rule applies, so in a 1QB league quarterbacks slide down the overall board. ▲/▼ next to the rank shows each move; the **SPAM Board** toggle shows the unadjusted board.

### League depth (shallow vs deep leagues)

Shallow leagues (few teams and/or few starters, e.g. 10 teams starting 7, or any 8-team league) have good players on waivers and strong lineups everywhere, so depth is worth less and high-end talent more. Depth = (teams × starting QB/RB/WR/TE/FLEX/SF spots) ÷ 108 (the site's 12 × 9), softened and capped (`DEPTH_ADJUST`): 12×9 = 1.00, 12×8 (1QB) ≈ 0.92, 10×7 ≈ 0.72, 8×9 ≈ 0.74, 8×7 ≈ 0.61, 14×9 ≈ 1.12. It scales:
- **Values:** the bench share of a player's value is benchWeight × depth (on top of replacement levels already rising in shallow leagues). In 10 teams × 7 starters, RB24 is worth 7% of RB1 (18% in the base format).
- **Lineup scores, power rankings and position rooms:** bench depth counts benchWeight × depth.
- **Trade model:** the consolidation bonus and roster-spot cost are divided by depth, so getting the best player in a 2-for-1 counts more.
- **Team-specific value:** a bench player's discount is divided by depth.

Leagues with depth under 0.85 are labeled "shallow league", and over 1.05 "deep league".

## Connecting a league: Sleeper, ESPN, Yahoo, other sites

**Connect league** offers four sources. Each import is converted to the same shape as a Sleeper league, so everything below works the same for all of them. Everything stays in the visitor's browser.
- **Sleeper:** username, one click (below).
- **ESPN:** paste the league page address or league ID. Public leagues are read straight from ESPN's league API. Private leagues (or if ESPN blocks the request) switch to copy and paste: the visitor opens the same ESPN address in a tab where they're signed in, copies the page and pastes it (or uploads it as a file). Scoring (including TE-premium overrides and big-game bonuses), lineup, teams, records and rosters come across; players map by ESPN ID (`data/platform_ids.json`) and then by name. Then they pick their team.
- **Yahoo:** Yahoo only shares league data with apps that sign people in through a server, which a static site can't do, so this is copy and paste: the League → Settings page (scoring, lineup, team count) and each team's roster page. The site finds the players in the pasted text and shows them as chips that can be removed before connecting. **Update rosters** in the league menu re-opens it with the current teams.
- **Another site** (NFL.com, CBS, Fleaflicker…): the same roster paste, with scoring and lineup from League settings.

## Position grades

The QB / RB / WR / TE "rooms" (power rankings, team breakdowns, trade analysis, Trade Finder) are graded from that position's players only: 1 for each dedicated starting slot, a share of each flex slot (FLEX ≈ 45% RB / 45% WR / 10% TE, superflex ≈ 90% QB), then bench depth at the bench weight, using the whole healthy roster. A trade with no QBs can't change any team's QB grade. Every trade read also double-checks this and logs a warning if it ever happens.

## Sleeper leagues

**Connect Sleeper** (top right) asks for a Sleeper username, lists that account's leagues for the current season, and imports the one you pick. It uses Sleeper's public API, so no password is needed. Everything is kept in the visitor's browser.

Data is kept in three separate layers:
1. **Base rankings:** `RANKINGS_CSV` plus editor edits. Sleeper never changes these.
2. **Sleeper league data:** league settings, scoring, lineup, managers and rosters, saved in the browser (`spm_sleeper`). **Refresh from Sleeper** re-downloads it; rankings and edits are untouched.
3. **League-adjusted values:** calculated on the fly. `data/curve_components.json` holds the per-game stat breakdown behind each positional finish; the site re-scores it with the league's scoring settings, sets replacement and waiver levels from the league's lineup (teams, starters, flex, superflex, bench), and moves each player's base value by the difference between that league model and the base model at his position rank. A league in the base format gets exactly the base values.

With a league connected:
- The header shows the league and its format; click it to switch leagues, refresh, change account or disconnect.
- Rankings get a **SPAM Board / League-adjusted** toggle, an owner label on each player (My Team, manager name, FA), and an owner filter. Editing works in the Base view.
- **My Team:** lineup by slot, bench, IR and taxi with overall rank, position rank and value; roster strength by position and power rank (same calculation as the League tab); **Trade with** buttons that open the trade calculator with both rosters.
- **League:** three views.
  - **Power Rankings:** a compact list (rank, team, manager, record, PF/PA, team score, best and weakest position, top players). Click a row (or its arrow) to open that team right underneath: power rank, team score, its QB/RB/WR/TE ranks in the league with strength / weak-spot flags and value vs the league average, then a roster board by position (photo, name, NFL team, position rank, overall rank, starting slot or BN, SPAM Value), plus kickers/defenses, IR and taxi. Buttons: **Trade with** (calculator with both teams) and **Find trades** (Trade Finder against that team). One team opens at a time; tick **Keep teams open to compare** or hold Shift/Cmd/Ctrl to open several.
  - **Trade History:** completed trades from Sleeper's transaction log, newest first, with what each team received (players, draft picks, FAAB), totals and the calculator's verdict and difference. 3-team trades get a verdict per team (received vs sent). Values are the SPAM values from the trade date when ranking history covers every player (closest entry at or before the trade, or within 3 days after); otherwise current values, labeled "Evaluated using current SPAM values". Draft picks are listed but not valued. **Full analysis** shows the adjustments, the verdict text and how the players are valued now; **Analyze trade** loads the trade into the calculator. Sleeper leagues only.
  - **Standings:** record order with PF, PA, streak, SPAM power rank and how far the roster is ahead of (▲) or behind (▼) the record. Click a team to open it in Power Rankings. Leagues with Sleeper divisions are grouped under each division's name and ranked inside it (wins, then points for), with a **By division / League** switch. **Playoff odds** (last column): 10,000 simulations of the rest of the regular season on the league's real Sleeper schedule (so strength of schedule counts), each team's weekly score drawn around a blend of its SPAM team strength and its points per game so far, then the league's playoff settings (number of playoff teams, division winners in, ties on points for). Hover for projected wins and remaining schedule rank.
  - **Matchups**: kickers and team defenses get Sleeper's weekly projection (fetched by your browser, scored with the league's K/DEF settings), so lineup totals include them; QB/RB/WR/TE use SPAM's projection.
  - **Matchups** work on phones: team names wrap, each lineup row shows slot, player with his game underneath, and points/projection on the right; nothing is cut off.
- **Free Agents:** ranked players nobody rosters, sorted by SPAM Values, filterable by position.
- **Trade calculator:** see *Trade calculator modes* below. Uses the league-adjusted values when that view is on.

Player photos come from Sleeper's image CDN by Sleeper ID (initials show when a photo is missing); manager avatars come from Sleeper too. The site refreshes league data in the background when it's more than 6 hours old.

`data/sleeper_players.json` (names for any rostered player), `data/platform_ids.json` (ESPN and Yahoo IDs → Sleeper IDs) and the `sleeper_id` column in `RANKINGS_CSV` come from `pipeline/build_sleeper_ids.py` (DynastyProcess player IDs) and are refreshed by the weekly workflow.

## Updating

- **Rankings:** use editor mode on the site, or edit `RANKINGS_CSV` in `index.html` (columns `player, pos, team, rank, pos_rank, tier`, optional `value` for a custom value; `rank` is the overall order) and push.
- **Projections:** automatic every Tuesday. To run it now: Actions → *Build and deploy site* → *Run workflow*.
- **End of season:** after week 17, disable the workflow's schedule (or the whole workflow) under Actions.
