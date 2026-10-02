# Tanki Stats - Tanki Online Discord Bot

## Complete Documentation

**Documentation updated:** October 2, 2026

**Project format:** Python application with a Discord bot interface

**Interface languages:** Russian, English (US), and English (UK)

**Daily collection:** 02:00 UTC / 05:00 Moscow time

**Persistent storage:** Local JSON files with atomic file replacement

Tanki Stats tracks public Tanki Online profile statistics and sends personal progress reports through Discord. This document describes the current implementation, installation, commands, proxy infrastructure, profile widgets, deployment, and maintenance procedures. Features and limitations below refer to the source in this project; examples contain placeholders rather than production credentials or user records.

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Technical Requirements](#technical-requirements)
4. [Quick Start](#quick-start)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [User Commands](#user-commands)
   - [Adding an Account](#adding-an-account)
   - [Removing an Account](#removing-an-account)
   - [Listing Accounts](#listing-accounts)
   - [Language Selection](#language-selection)
   - [Help and Bot Information](#help-and-bot-information)
8. [Administrator Commands](#administrator-commands)
9. [Statistical Model and Reports](#statistical-model-and-reports)
10. [Discord Profile Widget](#discord-profile-widget)
11. [Proxy System](#proxy-system)
12. [Scheduling and Report Delivery](#scheduling-and-report-delivery)
13. [Data Storage and Account Scope](#data-storage-and-account-scope)
14. [Privacy and Credential Handling](#privacy-and-credential-handling)
15. [Module Documentation](#module-documentation)
    - [Account Commands Module](#account-commands-module)
    - [Views Module](#views-module)
    - [Localization Module](#localization-module)
    - [Reports Module](#reports-module)
    - [Collection Module](#collection-module)
    - [Delivery Module](#delivery-module)
    - [Widget Module](#widget-module)
    - [Proxy Tasks Module](#proxy-tasks-module)
    - [Administrator Module](#administrator-module)
16. [Architecture and Project Structure](#architecture-and-project-structure)
17. [Linux Server Deployment](#linux-server-deployment)
18. [Updates, Backups, and Recovery](#updates-backups-and-recovery)
19. [Testing and Verification](#testing-and-verification)
20. [Compatibility and Known Limitations](#compatibility-and-known-limitations)
21. [Troubleshooting](#troubleshooting)
22. [Release and GitHub Publication](#release-and-github-publication)
23. [Maintenance Guidelines](#maintenance-guidelines)
24. [License and Project Status](#license-and-project-status)
25. [References and Acknowledgements](#references-and-acknowledgements)

## Overview

Tanki Stats is a Discord bot for monitoring changes in public Tanki Online player profiles. A user subscribes to a nickname, optionally chooses a personal alias, and receives scheduled direct messages containing the difference between consecutive saved snapshots.

The bot retrieves cumulative statistics from the Tanki Ratings profile API. It does not connect to the game client, require a Tanki password, inspect live battles, or retrieve an independent history of every match. Its reporting period is determined by the snapshots it successfully saves.

Each Discord user can track up to three game accounts. Several users can subscribe to the same nickname: the bot stores one shared game-account record and delivers the resulting report to each subscriber. Aliases belong to individual subscribers, while the snapshot baseline belongs to the tracked game account.

The implementation includes nine slash commands, administrator prefix commands, scheduled collection, a persistent delivery queue, optional Discord profile widget integration, and optional VLESS proxies managed through Xray. Basic tracking and reports can operate without configuring the widget or proxy subsystem.

The application runs as one Python process with local files. There is no database server, browser extension, web dashboard, public HTTP listener, or separate snapshot-collector service to deploy.

## Key Features

| Area | Current functionality |
|------|-----------------------|
| Account subscriptions | Up to three tracked nicknames per Discord user, with personal aliases |
| Shared collection | One baseline and collection record for a nickname followed by multiple users |
| Scheduled reports | Daily collection at 02:00 UTC and personal Discord messages |
| Progress calculation | Differences in cumulative counters, game modes, equipment, resistance modules, and supplies |
| Language preferences | Russian, US English, UK English, and automatic locale selection |
| Persistent delivery | Pending reports survive restarts and are retried every five minutes |
| Profile widget | OAuth authorization, account binding, identity selection, and profile updates |
| Network routing | Direct API access or a local Xray-backed VLESS proxy pool |
| Proxy maintenance | Startup loading, health checks, cooldowns, automatic checks, and bounded recovery |
| Administrator tools | Dry-run collection, forced reports, proxy filtering, and command blacklisting |
| Storage reliability | JSON serialization followed by atomic replacement of individual files |
| Verification | Regression tests, synthetic report fixtures, Ruff checks, and a prepared CI matrix |

Successful API collection, successful widget publication, and successful message delivery are separate events. A stored report can remain pending when a recipient has closed direct messages, even though the game statistics were collected successfully.

## Technical Requirements

### Python and Dependencies

Use Python 3.12 or 3.13. The prepared CI workflow targets both versions on Windows and Ubuntu. Local verification has been performed with Python 3.12; a configured CI matrix is not evidence that a remote run has already passed.

Production dependencies are pinned in [requirements.lock](requirements.lock). The application uses `discord.py`, `aiohttp`, `python-dotenv`, and supporting packages. Development tools are listed in [requirements-dev.txt](requirements-dev.txt). The broader ranges in [requirements.txt](requirements.txt) are available for dependency maintenance; the lock file is the preferred installation input for a reproducible deployment.

The Discord interface uses modern UI components, including `LayoutView` and containers. Installing an older Discord library simply because it supports traditional embeds can leave these commands unusable. Use the pinned dependency set.

### Discord Application

You need a Discord application with a bot token and permission to install the bot in the intended server. Use the Developer Portal installation settings for the bot and application commands. The process synchronizes global slash commands during startup.

Enable **Message Content Intent** in the application's Bot settings to use commands beginning with `!`. The source requests this intent. Discord documents the privileged-intent requirements in its [Gateway documentation](https://docs.discord.com/developers/events/gateway#privileged-intents).

Users must permit direct messages from the bot. Registration checks DM availability for a first-time subscriber, but a user can change that setting later.

### Network and Filesystem

The runtime needs outbound connectivity to Discord and the Tanki Ratings API. Proxy mode additionally needs access to configured subscriptions and VLESS servers. The bot must be able to write its account directory, log files, and generated proxy configuration.

A virtual environment is specific to its operating system and Python installation. Recreate it when moving from Windows to Linux.

### Optional Xray Runtime

Proxy mode requires an Xray binary matching the server's operating system and CPU architecture. Windows normally uses `xray.exe`; Linux normally uses `xray`. The project does not automatically download or install Xray.

The Windows runtime verified during local setup was Xray v26.3.27, available from the [official Xray release](https://github.com/XTLS/Xray-core/releases/tag/v26.3.27). Choose the appropriate official build for a different host. A Linux x86_64 binary cannot run on Windows or on a Linux ARM host.

## Quick Start

This minimal configuration uses direct API requests. Complete the Discord application setup before starting the bot.

1. Install Python 3.12 or 3.13.
2. Open a terminal in the project directory.
3. Create a virtual environment and install the locked dependencies.
4. Copy `.env.example` to `.env`.
5. Set `BOT_TOKEN` and `XRAY_ENABLED=false` in `.env`.
6. Run `bot.py` using the virtual environment's Python.
7. Wait for startup synchronization, then use `/add` in Discord.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
Copy-Item .env.example .env
# Edit .env before starting the bot.
.\.venv\Scripts\python.exe bot.py
```

Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
# Edit .env before starting the bot.
.venv/bin/python bot.py
```

Use the installed interpreter's actual name if it differs from `python3.12`. On an existing installation, preserve the current `.env` instead of replacing it with the example.

Minimal `.env` contents:

```dotenv
BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN
XRAY_ENABLED=false
```

After startup, try:

```text
/add nickname:ExamplePlayer account_name:Main
/list
/language language:English (US)
```

These lines illustrate slash-command options. Select the actual commands and language choices through Discord's command interface.

## Installation

### Prepare the Project

Keep [bot.py](bot.py), the complete `commands/`, `utils/`, and `proxy/` packages, the dependency files, and the bundled PNG assets together. Moving only `bot.py` and `commands/stats.py` is insufficient: the command cog imports its feature modules and storage, collection, and proxy helpers.

Run installation commands from the directory containing `bot.py`. Paths for application data are anchored to the project directory, but using that directory as the working directory also makes administration and diagnostics easier.

### Configure the Discord Bot

Create or select the intended application in the [Discord Developer Portal](https://discord.com/developers/applications). Copy its bot token into the local `.env`, enable Message Content Intent, and install the bot with application-command access in the intended server.

Administrator authorization is configured separately in the source. Being a Discord server administrator does not automatically grant access to the maintenance commands described below.

For ordinary tracking, leave `DISCORD_CLIENT_SECRET` empty. Configure it only when enabling the profile widget. The secret must belong to the same application as the running bot token.

### Choose a Network Mode

For direct access, use `XRAY_ENABLED=false`. This avoids the need for an Xray binary and proxy source file.

For proxy access, use `XRAY_ENABLED=true`, provide a compatible Xray binary, and create `proxies_sources.txt`. Place one VLESS URI or subscription URL on each line. The [Proxy System](#proxy-system) section explains loading and health checks.

### First Startup

Start the process in a terminal and inspect its output. A valid startup should reach Discord login, extension loading, and slash-command synchronization. When proxies are enabled, startup uses a usable local cache; source downloads and health checks run separately after Discord readiness.

The application loads its command extension during `setup_hook`; a normal Discord reconnect does not load it again. If proxy initialization fails, the error is logged and the bot can continue with no active pool. Profile requests then use direct access.

Keep the first startup interactive until the token, dependencies, permissions, paths, and optional proxy configuration are confirmed. After that, use a service manager for continuous operation.

## Configuration

### Environment File

Copy [.env.example](.env.example) to `.env` and set values for the intended installation. The bot reads this file from the project directory. Environment variables already supplied by the process take precedence over values loaded from `.env`.

Boolean proxy settings recognize `1`, `true`, and `yes` as enabled. Use the examples' `true` and `false` spelling for clarity. Numeric settings should contain valid numbers without units; malformed values can fail configuration parsing.

### Credentials and Runtime Paths

| Variable | Default | Purpose |
|----------|---------|---------|
| `BOT_TOKEN` | Unset; required | Token used to authenticate the Discord bot |
| `DISCORD_CLIENT_SECRET` | Unset | Application secret for widget authorization-code exchange and token refresh |
| `XRAY_ENABLED` | `true` | Enable loading and managing the proxy subsystem |
| `XRAY_BINARY_PATH` | Automatic platform selection | Explicit Xray executable path; a relative path is resolved from the project directory |
| `PROXIES_SOURCES` | `proxies_sources.txt` | Source file containing VLESS links and subscription URLs |
| `PROXIES_JSON` | `proxies.json` | Normalized proxy cache |
| `XRAY_CONFIG_PATH` | `xray_config.runtime.json` | Generated Xray runtime configuration |
| `REFRESH_PROXIES_ON_START` | `true` | Legacy setting retained for compatibility; source refresh runs in the background after Discord readiness |
| `PROXY_BASE_PORT` | `18001` | First local HTTP inbound port assigned to the proxy list |
| `MAX_PROXIES` | `0` | Maximum loaded proxies; `0` keeps all available entries |

Startup uses the local cache without downloading sources or saving unverified candidates. A missing, empty, or oversized cache leaves the pool inactive until the background check finds working routes. Automatic refresh runs after Discord readiness regardless of the legacy `REFRESH_PROXIES_ON_START` value. Generated proxy files contain configuration details and should be treated as private runtime data.

### Collection Settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `DAILY_STATS_WORKERS` | `20` | Concurrent account workers in a collection round |
| `DAILY_STATS_DELAY` | `0` | Configured delay between account work in the collector, in seconds |
| `DAILY_STATS_RETRY_DELAY` | `2` | Delay used before another account attempt, in seconds |
| `DAILY_STATS_MAX_ATTEMPTS` | `5` | Maximum account-level attempts in a collection round |
| `DAILY_STATS_RETRY_MAX_WAIT` | `65` | Upper wait for proxy availability before an account retry, in seconds |
| `DAILY_STATS_MAX_RECOVERIES` | `2` | Maximum emergency pool recoveries during one full collection |
| `PROFILE_API_TIMEOUT_TOTAL` | `5` | Total timeout for an individual profile HTTP request, in seconds |
| `PROFILE_API_CONNECT_TIMEOUT` | `3` | Connection timeout, limited to the configured total timeout |
| `PROFILE_FETCH_MAX_RETRIES` | `10` | Maximum proxy attempts within a profile fetch, capped by pool size |
| `PROFILE_FETCH_429_ABORT` | `3` | Repeated rate-limit threshold used to end a profile fetch |

`SNAPSHOT_WORKERS` and `SNAPSHOT_DELAY` are legacy fallbacks when their corresponding `DAILY_STATS_*` variables are absent. Prefer the current names. Their presence does not require the old `snapshot_collector.py` file.

Despite its name, `PROFILE_FETCH_MAX_RETRIES` controls the fetch attempt limit in proxy mode. A value at or below zero uses the pool size. Direct-mode fetching makes one HTTP attempt per account-level attempt.

Account-level retries, proxy-level attempts, timeouts, and emergency recovery all contribute to collection duration. Raising every limit at once can substantially lengthen a failed run.

### Proxy Health and Cooldowns

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROXY_RATE_LIMIT_COOLDOWN` | `60` | General failing-connection cooldown, in seconds |
| `PROXY_429_COOLDOWN` | `2` | Separate cooldown for a proxy receiving HTTP 429, in seconds |
| `PROXY_CHECK_WORKERS` | `25` | Concurrent profile probes during proxy filtering |
| `PROXY_CHECK_TIMEOUT` | `20` | Total timeout for each health-check HTTP attempt, in seconds |
| `PROXY_CHECK_CONNECT_TIMEOUT` | `10` | Connection timeout, capped by the total health-check timeout |
| `PROXY_CHECK_READ_TIMEOUT` | `15` | Socket-read timeout, capped by the total health-check timeout |
| `PROXY_CHECK_ATTEMPTS` | `2` | Attempts per route for temporary timeouts or connection failures; range 1-5 |
| `PROXY_CHECK_START_TIMEOUT` | `10` | Deadline for the checker Xray to open its local ports |
| `PROXY_SUBSCRIPTION_TIMEOUT` | `30` | Total timeout per subscription download; a timed-out source does not abort the remaining downloads |
| `PROXY_CHECK_XRAY_WARMUP` | `1.5` | Warmup after starting a health-check Xray configuration, in seconds |
| `PROXY_CHECK_BATCH_SIZE` | `400` | Number of configurations checked in an Xray batch |
| `PROXY_CHECK_INTERVAL_HOURS` | `6` | Automatic refresh interval in hours; must be positive and finite; applied on restart |
| `PROXY_WORKING_TARGET` | `50` | Desired working routes for automatic and emergency refreshes; `0` checks every candidate |
| `PROXY_CHECK_API_URL` | `https://ratings.tankionline.com/api/eu/profile/` | Endpoint used for health probes |
| `PROXY_CHECK_TEST_USER` | `Tenobyte` | Profile nickname requested during a health probe |

Not every advanced variable is included in `.env.example`; supported variables can be added explicitly. The general cooldown variable retains its historical name even though HTTP 429 has a separate setting.

### Settings Defined in Source

| Setting | Current location | Behavior |
|---------|------------------|----------|
| Administrator Discord IDs | `commands/stats_features/constants.py` | Explicit allowlist for maintenance commands |
| Account limit | `utils/accounts_manager.py` | Three subscriptions per Discord user |
| Daily schedule | `commands/stats_features/collection.py` | 02:00 UTC |
| Pending-report retry interval | `commands/stats_features/delivery.py` | Five minutes |
| OAuth redirect URI | `commands/stats_features/widget.py` | `https://discord.com` |
| Report rank thresholds and emoji references | `commands/stats_features/reports.py` | Current presentation tables |
| Help and information links | `commands/stats_features/views.py` | Project-specific external destinations |

There is no `ADMIN_IDS`, `ACCOUNTS_DIR`, or schedule-time environment option in the current implementation. Setting the host timezone does not change the daily UTC schedule. Application ID is derived from the connected Discord application rather than a separate configurable client ID.

## User Commands

### Command Reference

| Command | Options | Purpose |
|---------|---------|---------|
| `/add` | Required `nickname`; optional `account_name` | Subscribe to a Tanki Online account |
| `/remove` | Required `account_name` | Remove one of your subscriptions |
| `/list` | None | Show your tracked accounts and aliases |
| `/language` | Required language choice | Set Russian, US English, UK English, or automatic mode |
| `/help` | None | Display user-facing command guidance |
| `/info` | None | Display bot information and links |
| `/widget_setup` | None | Begin widget authorization |
| `/widget_token` | Required `code` | Exchange a copied OAuth authorization code |
| `/widget_refresh` | Optional `account_name` and `provider_user_id` | Publish saved statistics to a profile identity |

Command responses are designed to be ephemeral. Daily reports arrive as direct messages, so successful command interaction and successful future DM delivery require different Discord permissions.

### Adding an Account

**Purpose:** Create a personal subscription and establish a baseline for a previously untracked game account.

```text
/add nickname:ExamplePlayer account_name:Main
```

If `account_name` is omitted, the nickname becomes the alias. The nickname must be nonempty and contain letters, digits, underscores, or hyphens. The implementation accepts Unicode alphanumeric characters, but the remote API determines whether the player actually exists.

The command checks the user's three-account limit, duplicate nicknames, and duplicate aliases without case sensitivity. An alias must contain non-whitespace characters. Registration is serialized to prevent concurrent requests from bypassing the subscription checks.

For a first-time subscriber, the bot checks whether it can send a DM. If Discord forbids that message, registration stops and the user receives guidance to allow DMs.

For a new game-account record, the bot fetches public statistics and saves the initial baseline together with the subscription. HTTP 404 is reported as a missing player; network and other API failures are reported as temporary failures.

If another user already follows the same nickname, the new subscriber joins that existing record. The bot does not reset the shared baseline or create a second independent polling record.

### Removing an Account

**Purpose:** Stop following a game account under your personal alias.

```text
/remove account_name:Main
```

Alias lookup is case-insensitive. Removing your subscription does not remove other followers. When the last follower leaves, the bot deletes that game-account JSON file, including its stored baseline and any pending reports.

Removing an account is therefore different from temporarily preventing messages. Re-adding a nickname after its last subscription was removed creates a new baseline rather than restoring the deleted history.

### Listing Accounts

**Purpose:** Display your aliases, original nicknames, registration dates, and account-limit information.

Use `/list` before removing an account or choosing the account for a widget. The alias is a display and selection label; it does not rename the player in Tanki Online.

### Language Selection

**Purpose:** Choose the language used for supported command responses and daily reports.

| Choice | Stored language | Behavior |
|--------|-----------------|----------|
| Russian | `ru` | Use Russian translations |
| English (US) | `en-US` | Use US English translations |
| English (UK) | `en-GB` | Use UK English translations |
| Automatic | `auto` with a detected locale | Follow the locale observed on Discord interactions |

Automatic detection maps British English to `en-GB`, other English locales to `en-US`, and other locales to Russian. Daily messages use the saved preference or last detected locale; they cannot observe a new client-language setting until the user interacts again.

Legacy `en` preferences are interpreted as US English. A manual preference remains selected when later interactions provide a different locale.

Localization covers the supported user interface and report text. Some administrative replies, logs, slash-command descriptions, and upstream equipment names remain in their source language.

### Help and Bot Information

`/help` provides a compact guide inside Discord. `/info` displays runtime information such as latency, server count, account information, and configured links.

These views use the bundled images when available. Keep `account_icon.png` and `rounded-in-photoretrica.png` with the deployment to preserve the intended presentation. The external policy and project links in these views are configured in source; a new operator should review them before using a different Discord application.

## Administrator Commands

### Authorization

Maintenance commands use Discord user IDs from `ADMIN_IDS` in [constants.py](commands/stats_features/constants.py). Replace the allowlist deliberately when transferring operation to a different owner. Server roles and administrator permissions are not used as substitutes for this allowlist.

`!sync` is separate: it uses the bot-owner check provided by `discord.py`. Access to the other maintenance commands does not automatically grant access to `!sync`.

### Command Reference

| Command | Access | Effects |
|---------|--------|---------|
| `!proxycheck` | Administrator allowlist | Probe and filter proxies, update the cache and pool, and rewrite raw source entries |
| `!statscheck` | Administrator allowlist | Fetch account statistics in dry-run mode and log results |
| `!stats_force <nickname>` | Administrator allowlist | Collect one tracked account, advance its baseline, and queue reports for its followers |
| `!stats_force_all` | Administrator allowlist | Run the full collection pipeline for all tracked accounts |
| `!blacklist_add <Discord ID>` | Administrator allowlist | Block that user from invoking bot commands |
| `!blacklist_remove <Discord ID>` | Administrator allowlist | Remove a command blacklist entry |
| `!sync` | Bot owner | Request application-command synchronization |

Blacklist aliases are `!bl_add` and `!ban` for adding, and `!bl_rm` and `!unban` for removing.

### Dry-Run Collection

`!statscheck` performs real network requests through the current routing configuration. It does not save new statistics, update widgets, queue daily reports, or send collection-failure notices to subscribers.

It can change in-memory proxy health and cooldown state as requests succeed or fail. It does not perform the emergency proxy-recovery path used by a normal collection run. Use this command to diagnose collection without consuming the saved report baseline.

### Forced Collection

Forced collection uses the same persistence and delivery path as scheduled collection. A successful forced run advances the shared baseline. The next scheduled report starts from that new snapshot and therefore covers a shorter interval.

A force command is not a private preview for the administrator: reports are queued for the account's followers, and eligible widgets are updated. Run it only when those effects are intended. Command output may report pending recipients because a successful collection does not imply that every DM was accepted.

### Proxy Filtering

`!proxycheck` reports progress while checking configurations. It keeps working raw VLESS entries and removes raw entries that did not pass that run. Subscription URLs and comments are retained so subscriptions can still provide new entries later.

Back up `proxies_sources.txt` before a manual filter if the original raw list must be preserved. Automatic refreshes do not rewrite that source list.

### Command Blacklist

Blacklisted users receive a localized refusal for slash commands; prefix messages from them are ignored. The blacklist controls command access only. It does not unsubscribe accounts, delete stored data, revoke widget authorization, or stop already scheduled report delivery to that user.

Most prefix-command replies and triggering messages are scheduled for deletion after five minutes where permissions allow. The proxy-check status reply has different handling so a long check can remain visible. Failure to delete an old message does not undo the maintenance operation.

## Statistical Model and Reports

### Snapshot Baseline

The calculation uses two cumulative snapshots:

```text
reported difference = current successful snapshot - previous saved snapshot
```

The initial registration snapshot establishes the baseline. Normal collection saves the next snapshot and its report together in the account file. All followers of that game account use the same baseline.

For example, if a stored snapshot has 100 kills and the next successful snapshot has 125, the report records 25 additional kills. If an intermediate collection failed, the later difference covers the entire interval since the last saved snapshot.

### Reporting Period

The daily trigger is a schedule, not a guarantee of an exact 24-hour game-data interval. API delays, downtime, forced collection, and a newly joined follower's shared baseline affect the period.

| Situation | Effect on the next report |
|-----------|---------------------------|
| Normal consecutive scheduled collections | Approximately one day between saved snapshots |
| API failure without a saved result | Baseline remains unchanged; the next success covers a longer interval |
| Forced collection between daily runs | Baseline advances; the next daily interval is shorter |
| New follower of an already tracked nickname | Follower inherits the existing shared baseline |
| Bot offline at the daily trigger | No independent historical snapshot is reconstructed for that missed time |
| Last follower removes the account | The record is deleted; a later registration begins again |

The bot does not query a separate calendar-day report endpoint or recover every missed day's individual history.

### Report Contents

| Section | Current behavior |
|---------|------------------|
| Profile header | Player nickname and current total score |
| Basic progress | Differences in earned crystals, kills, deaths, and caught gold boxes |
| Game modes | Score-earned differences by mode |
| Turrets | Score-earned differences for merged turret names |
| Hulls | Score-earned differences for merged hull names |
| Drones | Score-earned differences for individual drone entries |
| Resistance modules | Score-earned differences for merged module names |
| Supplies | Changes in reported supply usage |
| Timestamp | Creation time of the saved report, retained on a later retry |

The difference calculation also retains total score and supported time-played changes, while the embed presents total score and the progress sections listed above. Time differences and normalized grades are not separate displayed report fields. Paint statistics are not included in the current report renderer.

Mode and equipment sections display entries with nonzero score differences and sort their lists by that difference. Supplies display nonzero usage differences. Names and translation tables come from the current implementation; unknown equipment can fall back to the API's raw name.

### Equipment Normalization

Turrets, hulls, and resistance modules with the same name are merged before comparison. The normalization sums `scoreEarned` and `timePlayed` and preserves the highest grade. This avoids treating multiple entries for one equipment name as unrelated rows.

Drones and supplies are compared by item ID, while modes are compared by mode type. This behavior follows the current Tanki profile schema and may need adjustment if the API changes its identifiers or grouping.

### Missing and Decreasing Values

An item absent from the older snapshot is compared with a zero baseline for its relevant counters. When the API first introduces an item, the displayed difference can therefore include its already accumulated values.

Negative differences are preserved. They can reflect a corrected upstream counter, changed aggregation, or inconsistent source data. The bot does not silently replace every negative value with zero.

### Rank Presentation

The shared rank helper used by the widget calculates names from the score thresholds in [reports.py](commands/stats_features/reports.py). The table begins at Recruit and reaches Legend at 1,600,000 score. Further Legend levels use 200,000-point increments. The current daily-report embed does not display a separate rank field.

The rank table is local reference data rather than a separately fetched live ranking definition. Keep it aligned with the game when maintaining the project.

Report icons include hardcoded custom Discord emoji references. Their appearance depends on availability to the deployed application and Discord client. A new application may require its own emoji references.

## Discord Profile Widget

### Purpose and Requirements

The widget publishes a selected account's saved statistics to a Discord application identity profile. It is optional and does not replace the personal daily reports.

Set `DISCORD_CLIENT_SECRET` for the same application as `BOT_TOKEN`. Register the redirect URI `https://discord.com` for that application. The bot builds authorization URLs using its connected application ID and the `openid sdk.social_layer` scopes.

The authorization-code and refresh-token mechanisms are described in [Discord's OAuth2 documentation](https://docs.discord.com/developers/topics/oauth2). Profile writes also depend on Discord's identity authorization and endpoint rules; see the [Application Identity Profile resource](https://docs.discord.com/developers/resources/application-identity-profile).

### Authorization Workflow

1. Run `/widget_setup` and open the authorization link supplied by the bot.
2. Authorize the correct Discord application in the browser.
3. After redirection, copy the value of the `code` parameter from the URL.
4. Run `/widget_token code:<copied-code>`.
5. Run `/widget_refresh account_name:<your-alias>` to choose the game account and publish the profile.
6. Supply `provider_user_id` if automatic identity resolution cannot identify the appropriate record.

Copy only the code value after `code=` and before the next `&`, not the entire redirected URL. Treat the code as temporary authorization material and use it promptly. The project uses a manual code-copy flow; it does not run an OAuth callback web server.

### Application and Identity Scope

The application ID is derived from the connected bot. Changing the bot token to another application also requires that application's client secret and a new authorization flow.

`provider_user_id` identifies the Discord application identity selected for the profile write. It is not automatically the Tanki nickname, and an arbitrary value such as `0` should not be invented to bypass identity errors.

The command uses an explicitly supplied identity ID, an existing stored binding, or an attempted Discord identity lookup. If it cannot resolve one identity unambiguously, it asks for an explicit value rather than guessing.

### Account Selection

An explicitly selected account takes priority. Otherwise the command tries the previously bound nickname. If only one account is available, it can select that account; multiple unbound accounts require a choice.

After a successful profile update, the token record stores the nickname and identity binding. Scheduled updates use that binding so collecting another account does not accidentally replace the selected profile.

### Published Fields

| Field name | Value |
|------------|-------|
| `nickname` | Tracked Tanki nickname |
| `rank` | Rank calculated from the saved score |
| `score / scoreNext` | Current score and rank-progress presentation |
| `playTime` | Sum of saved mode play times, in seconds |
| `game` | Current configured game reference string |
| `kills` | Lifetime kill count from the saved snapshot |
| `deaths` | Lifetime death count from the saved snapshot |
| `kills/deaths` | Lifetime ratio; zero when the death count is zero |
| `BestTurret` | Raw turret entry with the highest score earned |
| `BestHull` | Raw hull entry with the highest score earned |

These field names match the payload produced by the current source. Some numeric values are sent as formatted strings; `playTime` uses a numeric dynamic-field type. The payload sets `username` to the nickname and replaces the profile data object through the profile API.

Widget values are cumulative saved profile values. `/widget_refresh` does not fetch fresh Tanki data: run collection first when a new snapshot is needed.

### Tokens and Refresh

OAuth access tokens, refresh tokens, expiry information, and bindings are saved in `accounts/user_tokens.json`. Refresh operations are serialized per Discord user to prevent concurrent refreshes from racing over rotating token state.

Refreshing a token preserves its existing account and identity binding. A failed profile update does not automatically erase a valid authorization record. Expired authorization without a usable refresh token requires renewed authorization.

Widget publication is not stored in the durable DM outbox. A failed widget update can be attempted on the next applicable collection or with `/widget_refresh`; it does not inherit the same persistent retry guarantee as a daily report.

## Proxy System

### Purpose

The proxy subsystem routes Tanki API requests through locally managed Xray HTTP inbounds. Python communicates with loopback ports; Xray establishes the corresponding VLESS connections to remote servers.

Discord gateway traffic and ordinary Discord API calls are not automatically routed through this Tanki proxy pool. Subscription downloads are also a separate network operation from profile requests.

Proxy support is optional. If no active pool is available, the profile client uses direct requests. Setting `XRAY_ENABLED=true` expresses the intended configuration but does not enforce a strict rule that every request must use a proxy after initialization fails.

### Source Format

Create `proxies_sources.txt` in the project directory, or configure another path with `PROXIES_SOURCES`. Each nonblank line contains a raw VLESS URI or an HTTP(S) subscription URL. Lines beginning with `#` are comments.

```text
# Subscription supplied by your proxy provider
https://subscription.example.invalid/YOUR_PRIVATE_SUBSCRIPTION

# A raw VLESS URI can be placed on its own line below.
# Use the complete URI supplied by your provider, including transport settings.
```

The example subscription is deliberately nonfunctional. Use your provider's actual address privately. A fabricated URI with missing REALITY keys is not a useful connectivity test.

Subscription responses can contain plain VLESS lines, Xray JSON profiles, arrays of profiles or VLESS URI strings, or Base64-encoded versions of those formats. JSON imports support VLESS outbounds inside `outbounds`, standalone VLESS outbounds, and profiles wrapped in `configs`. Other JSON formats are reported as unsupported. The loader combines these entries with raw sources and produces normalized proxy records. Subscription requests use their own timeout and application user agent.

JSON import retains stream settings, user encryption, transport parameters, and outbound options such as mux. Each server/user combination becomes a separate candidate. Outbounds that require another outbound through `proxySettings` or `sockopt.dialerProxy`, and VLESS reverse outbounds, are rejected with a reason instead of being flattened into an incomplete standalone route. Profile-wide inbounds, DNS, routing rules, and chained outbounds are not imported into the bot's generated runtime. A malformed neighboring profile or entry does not discard valid entries.

Base64 decoding validates the encoded input and UTF-8 output; other plain text is preserved instead of being partially decoded. Some public lists already contain placeholders such as `[emailprotected]` in place of a VLESS user ID and server address. These entries cannot be reconstructed from the placeholder and are skipped. Valid neighboring entries remain available. Download summaries identify the affected subscription by its position in the URL list and hostname, without printing its full URL.

### Parsing and Compatibility

The source parser retains addresses, ports, decoded user IDs, security, transport, and relevant TLS or REALITY parameters. WebSocket and HTTPUpgrade paths and hosts, gRPC service names and authorities, XHTTP paths/modes/extra settings, RAW HTTP headers, TLS ALPN, and REALITY spider paths are carried into the generated outbound. Explicit URI `allowInsecure` values are preserved; the parser does not enable that option implicitly. A compatibility filter removes configurations that the current generator cannot use.

The filter accepts `reality`, `tls`, and `none` security. An omitted URI security setting means `none`. Supported transports are RAW/TCP, WebSocket, gRPC, XHTTP/SplitHTTP, and HTTPUpgrade. Aliases are normalized before generation. For REALITY, only RAW, XHTTP, and gRPC are accepted. REALITY requires a public key; its short ID may be empty, matching Xray 26.3.27, or contain up to 16 hexadecimal characters with even length. Xray configuration validation and the API probe still determine whether an accepted candidate actually works.

Deduplication hashes the generated connection configuration instead of only the user ID, server address, and port. Routes with different SNI, transport paths, service names, REALITY keys/short IDs, encryption, or other effective settings remain separate candidates. Labels, local listening ports, and JSON tags do not affect identity. Logs distinguish exact duplicates from rejected entries and show when `MAX_PROXIES` stops parsing. Existing cache records remain readable; successful refreshes replace them with records containing the new transport fields and connection identities. Lost parameters in a legacy cache can only be restored by downloading the source again.

The supported VLESS flow values are empty, `xtls-rprx-vision`, and `xtls-rprx-vision-udp443`. Older values such as `xtls-rprx-origin` are rejected before Xray starts, including when loading an existing cache. The filter does not change an unsupported flow into another protocol setting.

User IDs are also validated before startup and cache loading. Validation follows the [Xray 26.3.27 UUID parser](https://github.com/XTLS/Xray-core/blob/v26.3.27/common/uuid/uuid.go): recognized UUID forms and nonempty custom IDs of at most 30 UTF-8 bytes remain supported. Malformed longer IDs are rejected, rather than allowing one invalid entry to trigger repeated batch splitting. IDs are not rewritten or guessed.

This filter describes the current implementation's accepted configurations. It is not a promise that every VLESS URI, every transport extension, or every Xray version is supported. A URI can parse successfully and still fail Xray configuration validation or an actual network probe.

Malformed and incompatible source entries are counted in one warning summary per parsing pass. Per-entry diagnostics use debug level and omit the original URI and parser exception text. This keeps damaged lists from producing thousands of warning lines containing connection credentials. A placeholder appearing only in a label or fragment does not invalidate an otherwise valid address.

### Generated Files and Local Ports

| File | Role |
|------|------|
| `proxies_sources.txt` | Private source list maintained by the operator |
| `proxies.json` | Normalized and filtered proxy records |
| `xray_config.runtime.json` | Generated inbounds, outbounds, and routing configuration |
| `.xray-check-*/config.json` | Private temporary configuration for the independent checker; removed after each check |
| `xray` or `xray.exe` | Platform-specific executable managed by the runner |

Serving inbound ports are assigned consecutively from `PROXY_BASE_PORT`, including when loading a cache. The checker requests separate available ports from the operating system and excludes the serving ports. Both processes bind to `127.0.0.1`, so external clients do not need access to those ports. Do not expose them publicly as part of installing the bot. No separate checker port setting is required.

Parsed source candidates have no serving port until they pass health checks. Their count can exceed the available TCP port range because the checker tests them in separate batches. At startup, a legacy cache larger than `65536 - PROXY_BASE_PORT` is skipped without overwriting it. For example, 70,813 cached entries cannot fit from port 18,001. A successful background check replaces that cache with the filtered working pool. Until a pool exists, profile requests use the existing direct-access fallback.

The cache and generated Xray configuration can contain UUIDs and other private connection material. They are runtime files, not suitable public example configuration.

### Pool Selection

The pool keeps a proxy associated with an asynchronous task while that assignment is useful. It uses recent successes and failures to rank available configurations, then randomly selects among a small group of high-scoring candidates.

This is adaptive selection rather than uniform round-robin distribution. Proxies with recent failures enter cooldown, and rate-limit responses use a separate cooldown from connection failures. Task bindings are cleaned up after account work completes.

When every proxy is in cooldown, the client can report pool exhaustion instead of repeatedly attempting unavailable ports. The collector waits or invokes its bounded recovery path as appropriate.

### Health Checks

Health checks start configurations in batches in a separate Xray process and request a test profile through its local ports. The test nickname and API URL are configurable. During parsing, subscription downloads, probes, and batch splitting, commands and scheduled collection continue using the serving Xray and current pool. Candidate port assignments do not modify the serving records.

Automatic and emergency refreshes stop scheduling new probes once `PROXY_WORKING_TARGET` working routes have been found. Already running requests finish, so the saved pool can exceed the target by up to the worker count minus one. Unchecked candidates are reported separately from failures. Batch splitting also stops once enough working routes have been found; an untested half is not recorded as failed.

For a bounded refresh, entries from the previous pool are checked first only if their IDs still occur in the freshly downloaded sources. Their new source parameters are used; an entry removed from its subscription is not restored from the cache. Remaining candidates are shuffled to avoid always selecting the first source entries. `MAX_PROXIES` still caps the parsed candidate list independently of the working target.

If the sources contain fewer working routes than the target, all candidates are checked and any working routes are saved. A refresh with no working routes leaves the previous pool in place. `PROXY_WORKING_TARGET=0` restores a full automatic scan. Manual `!proxycheck` always checks the full parsed candidate list before rewriting raw source lines.

If a batch fails Xray configuration validation, the checker splits it to isolate problematic configurations. This allows a single malformed entry to be rejected without automatically discarding every other proxy in that batch.

HTTP 429 demonstrates that the request reached the upstream API and is accepted as evidence of connectivity during filtering. It does not mean the proxy can provide unlimited successful profile requests during normal collection.

Before probing, the checker waits for all of its assigned local ports to listen, within `PROXY_CHECK_START_TIMEOUT`, then applies the configured warmup. Connection and read timeouts are bounded by the per-attempt total. Temporary connection failures and timeouts can retry up to `PROXY_CHECK_ATTEMPTS`; permanent HTTP failures do not retry. A route is counted once regardless of attempts. Increasing these limits increases the duration of a full scan.

Failed batches also log an aggregate reason summary at warning level: HTTP status counts, timeouts, connection failures, invalid JSON, or an unexpected JSON schema. This helps distinguish an unreachable route from an API response that the checker cannot accept. A successful Xray process start alone does not establish working API access.

Checks are serialized with a maintenance lock. After a successful scan, the checker stops and removes its temporary configuration. Only then does the bot acquire the pool-recovery lock, wait for ongoing profile requests or a collection round, restart the serving Xray, and publish the filtered pool. Requests can briefly wait during this final restart; they no longer wait for the entire source scan.

Manual `!proxycheck` updates the same Discord status message while waiting for an existing check, downloading each subscription, parsing candidates, probing routes, and switching the working pool. The numeric counter starts at zero after candidates are parsed. A command invoked during the automatic startup check waits in the queue before beginning its own full scan. Large subscription decoding and VLESS parsing run in worker threads so they do not block Discord's event loop. Failed status-message updates are recorded in the logs.

A failed or cancelled scan leaves the serving runtime and pool in place. If the final serving restart fails or is cancelled, the bot attempts to restore the previous runtime before releasing the replacement lock. Shutdown cancels an active check and stops both managed processes. Hard process termination can leave a temporary checker directory; treat it as private credential material.

An independent check does not make an exhausted or unreachable serving pool healthy. If collection requires emergency recovery, it can still wait for usable routes. Direct access remains the existing fallback when no pool exists; `XRAY_ENABLED=true` does not enforce proxy-only access.

### Automatic Checks and Emergency Recovery

The automatic check runs after Discord readiness and repeats every `PROXY_CHECK_INTERVAL_HOURS` hours, defaulting to six. It downloads the current subscription contents on each run and preserves the source list while updating the working cache and pool. The interval is measured by the task loop rather than a fixed wall-clock schedule. Change the environment setting and restart the bot to apply a different interval.

The default target of 50 routes is a starting value, not a guarantee of suitable capacity for every installation. Increase it when collection needs a larger reserve, or use zero for a complete scan. A short scan can still take time when sources are unavailable or few candidates work; it does not guarantee a specific completion time.

A normal full collection can recover an exhausted pool up to `DAILY_STATS_MAX_RECOVERIES` times. The default is two recoveries. Remaining failures are reported and retained as failures for that collection rather than causing unlimited recovery attempts.

Dry-run collection does not invoke emergency recovery. Manual `!proxycheck` differs from the automatic check because it rewrites raw source lines to retain entries that passed.

### Xray Process Lifecycle

The runner resolves a compatible binary, validates and launches the configuration, and owns that child process. An explicitly configured binary path takes precedence over automatic selection.

On Windows, automatic selection prefers `xray.exe`; on Linux it prefers `xray`. Platform checks can identify common mistakes such as a Linux ELF executable selected on Windows or a Windows executable selected on Linux.

Extension unloading cancels and awaits background loops before stopping Xray and closing the shared HTTP session. Collection workers are also cancelled and awaited when their parent operation is cancelled. These controls reduce races between active requests and shutdown.

## Scheduling and Report Delivery

### Background Tasks

| Task | Timing | Main responsibility |
|------|--------|---------------------|
| Daily collection | 02:00 UTC each day | Fetch profiles, save snapshots, queue reports, and attempt delivery |
| Pending-report retry | First pass after readiness, then every five minutes | Retry recipients whose saved reports remain unacknowledged |
| Automatic proxy check | First pass after readiness, then every six hours by default | Download fresh sources and verify routes until the configured target is reached |

The daily task uses a UTC time definition. On a Moscow host this corresponds to 05:00, regardless of whether the terminal displays local timestamps. Changing a server timezone or adding a `TZ` environment variable does not alter that source-defined schedule.

### Collection Sequence

1. Acquire the collection lock and load tracked account records.
2. Fetch profiles with the configured worker count and retry limits.
3. For each successful account, reload its current subscribers and baseline under the account lock.
4. Calculate the difference and create a pending report.
5. Save the new baseline and pending report together in the account JSON file.
6. Attempt eligible widget updates.
7. Attempt queued DM deliveries and persist acknowledgements.
8. Recover the proxy pool within the configured limit when the collection requires it.
9. Finish with processed and failed account counts.

The collection lock serializes scheduled and forced collection. A separate pool-recovery lock coordinates collection rounds and individual profile requests with the final serving-pool replacement. The full candidate scan runs outside that lock. Per-account locks protect report persistence and flushing within the running process.

### Durable Outbox

A report is stored before its first DM attempt. Its record includes a report ID, creation time, nickname, current snapshot, calculated differences, and pending subscriber IDs.

The baseline advances when this combined save succeeds, even if a recipient is temporarily unavailable. The already calculated difference remains in the outbox, so it does not disappear merely because the next collection uses a newer baseline.

After a successful DM, the bot removes that recipient from the pending list. Once every pending recipient has been acknowledged or removed, the report is removed from the queue.

### Recipient Ordering

The bot retries stored reports in their saved order. If an earlier report fails for a user during a pass, later reports for that same user wait. Other recipients can still receive their reports.

Users who have unsubscribed are removed from pending delivery when the queue is flushed. This prevents a stale pending report from continuing to target a former follower.

### Delivery Guarantee

The outbox provides at-least-once delivery attempts. A rare duplicate can occur if Discord accepts a message but the process stops, or acknowledgement persistence fails, before the success is saved locally.

There is no atomic transaction spanning Discord and the local filesystem. Do not describe this mechanism as exactly-once delivery. It prioritizes retaining an undelivered report over silently dropping it.

### Backlog Behavior

Closed DMs, blocks, and temporary Discord errors leave reports pending. Restarting the bot reloads those reports and the retry task resumes after readiness.

The current queue has no automatic expiration or fixed backlog cap. A permanently unreachable user can accumulate pending records over time. Monitor the account directory and diagnose persistent failures rather than assuming retries will eventually succeed without user action.

A collection summary counts an account as processed after successful persistence and queueing. It is not a count of recipients who definitely received a message.

## Data Storage and Account Scope

### Account Directory

The application stores private runtime state under `accounts/` in the project directory. The directory is created as needed and is excluded from public source publication by `.gitignore`.

| Record | Contents |
|--------|----------|
| One JSON file per tracked nickname | API URL, subscribers, aliases, baseline, update time, and pending reports |
| `blacklist.json` | Discord user IDs blocked from command access |
| `user_languages.json` | Manual language preferences or automatic-mode locale state |
| `user_tokens.json` | Widget OAuth tokens, expiry values, nickname bindings, and identity IDs |

Metadata files are excluded when the manager enumerates game-account records.

### Game-Account Record

The following is a simplified example for documentation. Real `last_stats` and report payloads contain additional mode and equipment data returned by the profile API.

```json
{
  "nickname": "ExamplePlayer",
  "api_url": "https://ratings.tankionline.com/api/eu/profile/?user=ExamplePlayer&lang=ru",
  "tracked_by": {
    "123456789012345678": {
      "account_name": "Main",
      "added_at": "2026-10-02T02:00:00"
    }
  },
  "last_stats": {
    "score": 100000,
    "kills": 125,
    "deaths": 80,
    "earnedCrystals": 50000,
    "caughtGolds": 2
  },
  "last_updated": "2026-10-02T02:00:00",
  "pending_reports": []
}
```

The example Discord ID and counters are fictional. Timestamps illustrate the structure; queued reports use timezone-aware UTC creation timestamps.

Older records can contain a `current_stats` field. Current comparison and collection use the saved `last_stats` baseline; the existence of an extra legacy field does not define a second reporting period.

### Filenames and Reserved Names

Account filenames are normalized and sanitized. Reserved metadata names and operating-system names, including `CON`, `NUL`, and `COM1`, are protected from filename collisions by a prefix in the storage filename.

This storage protection does not forbid a legitimate Tanki nickname merely because it resembles a reserved filename. Always use the account manager when deriving a path instead of constructing `<nickname>.json` in new code.

### Subscriber Scope

The `tracked_by` mapping stores subscriber IDs as strings. Each subscriber has a personal alias and added date. Several aliases belonging to different users can reference one nickname record.

An alias is unique within a user's subscriptions, not a global game-account identifier. The baseline and pending report list belong to the nickname record; language and OAuth state belong to the Discord user.

### Atomic Writes

[storage.py](utils/storage.py) serializes data, writes a temporary file in the destination directory, flushes and synchronizes it, and replaces the destination file. This reduces the chance of leaving a partially written JSON document.

Atomic replacement applies to individual files. It does not encrypt their contents, provide a multi-file database transaction, or make two independent bot processes safe writers to the same directory.

### Corruption and Recovery

JSON read and write failures are logged. A damaged token file is not silently replaced with a fresh empty token store during a save. Other read failures can make records unavailable to the calling operation.

The application does not provide a universal automatic repair command. Restore damaged files from a trusted backup, and validate their JSON before restarting. Stop the bot before manual edits so an in-memory operation does not overwrite your changes.

## Privacy and Credential Handling

### Data the Bot Needs

The tracking workflow stores public game nicknames and snapshots, Discord subscriber IDs, personal aliases, dates, language choices, and pending report state. Widget authorization additionally stores OAuth credentials and identity bindings.

The bot does not need Tanki login credentials. A request to supply a game password would not be part of the documented tracking flow.

### Private Runtime Files

| Material | Handling |
|----------|----------|
| `.env` | Keep local; contains bot and optional application credentials |
| `accounts/` | Back up privately; contains user relationships, reports, and possible OAuth tokens |
| Proxy source and generated files | Keep local; can contain subscription secrets and VLESS credentials |
| `bot.log` and rotated logs | Review before sharing; can contain identifiers and operational details |
| `.refactor-backup/` | Local recovery material; do not publish as source |

The local JSON stores are not encrypted. Filesystem permissions, private backups, and access to the host determine who can read them.

### Test and Production Isolation

A different `BOT_TOKEN` does not create a separate account database. Running another application against the same project directory still exposes the same tracked accounts, language settings, token records, and report queue to that process.

Use a separate project copy with its own `.env` and `accounts/` for testing. Start it with fresh test data and test subscriptions. A second process must not share the production account directory.

OAuth records also belong to the application that issued them. Replacing the bot token with another application's token does not make the old widget tokens valid for the new application.

### Sharing Diagnostics

Before posting logs or configuration, remove bot tokens, client secrets, OAuth codes and tokens, private subscription URLs, VLESS UUIDs and keys, and unnecessary Discord identifiers.

Share the relevant error, platform, Python version, Xray version, and sanitized configuration instead. These are usually sufficient to investigate a binary mismatch, dependency issue, or network failure.

### User-Facing Policy Links

The `/info` and help views contain configured policy and project links. This README documents storage behavior; it does not replace an operator's published terms or privacy policy. Review those links and their content when adopting the code for another application.

## Module Documentation

### Account Commands Module

**Purpose:** Manage user subscriptions and language-setting commands.

**Source:** [accounts.py](commands/stats_features/accounts.py)

The module implements `/add`, `/remove`, and `/language`. Registration handles validation, account limits, duplicate checks, first-time DM testing, and the initial API request for a new nickname.

The registration lock is shared across incoming add requests. Persistent data is delegated to `AccountsManager`; API access uses the same profile client and optional pool as collection.

When extending this module, preserve the distinction between a new subscriber and a new game-account record. Reinitializing an existing nickname's snapshot when another user joins would change every follower's next report.

### Views Module

**Purpose:** Build informational Discord layouts for account lists, help, and bot details.

**Source:** [views.py](commands/stats_features/views.py)

The module implements `/list`, `/help`, and `/info` with modern Discord UI views, containers, sections, buttons, and optional image attachments. It reads subscription and runtime information without starting a collection.

Keep asset paths anchored to the project directory. Review external links when changing application ownership. View text uses the localization helpers, while upstream nicknames and account aliases remain user data.

### Localization Module

**Purpose:** Resolve preferences and translate supported user-facing report and command text.

**Source:** [localization.py](commands/stats_features/localization.py), with reference mappings in [discord_translations.py](utils/discord_translations.py)

The helpers distinguish Russian from the two supported English variants and update automatic-mode locale state when interactions provide it. Saved preferences make scheduled messages independent of whether an interaction is currently active.

Add translations alongside their existing alternatives instead of embedding inconsistent language checks across unrelated modules. Preserve legacy language compatibility when changing preference storage.

### Reports Module

**Purpose:** Normalize cumulative statistics, calculate differences, determine ranks, and render report embeds.

**Source:** [reports.py](commands/stats_features/reports.py)

Report calculation and rendering are separate from fetching and sending. This makes it possible to compare a synthetic snapshot pair and inspect its embed without contacting Tanki or Discord.

Rank thresholds, equipment normalization, custom emoji references, and section formatting live here. Regression fixtures in `tests/fixtures/reports.json` capture representative output for supported languages.

Changes to merge keys, missing-item handling, sorting, or numeric presentation can affect every report even if collection remains healthy. Treat those changes as reporting behavior changes and review the fixture differences.

### Collection Module

**Purpose:** Coordinate scheduled and manual account collection, dry-run behavior, retries, and pool recovery.

**Source:** [collection.py](commands/stats_features/collection.py), using [stats_collector.py](utils/stats_collector.py)

The feature module owns collection orchestration and the daily task. The utility module owns the parallel worker queue, attempt accounting, failure accumulation, and cancellation cleanup.

Dry-run and normal collection share fetching logic while deliberately diverging before persistence and user delivery. Keep that boundary clear: a dry run should remain suitable for diagnosis without changing the report baseline.

### Delivery Module

**Purpose:** Persist report payloads and retry recipients who have not been acknowledged.

**Source:** [delivery.py](commands/stats_features/delivery.py)

The module combines baseline advancement with queue insertion, attempts widget updates, sends reports, and records per-recipient acknowledgements. It also implements the five-minute retry loop.

The account lock and reload before calculating the difference protect the current subscriber list and baseline within one process. Avoid adding a second direct-send path that bypasses the persisted outbox.

### Widget Module

**Purpose:** Authorize and publish a selected Tanki snapshot to a Discord application identity profile.

**Source:** [widget.py](commands/stats_features/widget.py)

The module implements the three widget slash commands, OAuth exchange and refresh, identity resolution, payload construction, and binding-aware automatic updates.

It uses per-user token locks for refresh and derives the application ID from the connected bot. OAuth credentials and profile bindings are delegated to the account manager.

Keep authorization, account selection, and remote publication distinct when extending the workflow. A valid token does not guarantee that an arbitrary identity path is authorized or that the latest profile has already been collected.

### Proxy Tasks Module

**Purpose:** Run periodic proxy checks, recover failed pools, and report relevant maintenance failures.

**Source:** [proxy_tasks.py](commands/stats_features/proxy_tasks.py)

The module coordinates the feature layer with `ProxyBootstrap`. Automatic and emergency scans use an independent checker. They pass the shared recovery lock to the final pool replacement so it cannot restart the serving runtime during a collection round or profile request.

Automatic filtering preserves original source lines. Manual destructive filtering remains an explicit administrator command rather than an incidental effect of every scheduled check.

### Administrator Module

**Purpose:** Expose controlled maintenance commands for authorized Discord users.

**Source:** [admin.py](commands/stats_features/admin.py), with authorization IDs in [constants.py](commands/stats_features/constants.py)

This module handles forced collection, dry runs, manual proxy checks, blacklist changes, and their responses. It delegates actual collection and delivery to the shared feature paths.

Keep access checks attached to every maintenance entry point. Adding a command alias must not create a route around authorization or duplicate the collection implementation.

## Architecture and Project Structure

### Source Layout

```text
Tanki Stats/
├── bot.py                         # Discord entry point, intents, sync, logging
├── commands/
│   ├── stats.py                   # Cog composition and resource lifecycle
│   └── stats_features/
│       ├── accounts.py            # Subscription and language commands
│       ├── admin.py               # Maintenance prefix commands
│       ├── collection.py          # Daily/manual orchestration
│       ├── constants.py           # Administrator allowlist
│       ├── delivery.py            # Persistent report outbox
│       ├── localization.py        # Locale and text helpers
│       ├── proxy_tasks.py         # Scheduled filtering and recovery
│       ├── reports.py             # Differences, ranks, report embeds
│       ├── views.py               # List, help, and information layouts
│       └── widget.py              # OAuth and application profile writes
├── utils/
│   ├── accounts_manager.py        # JSON records and subscription operations
│   ├── discord_translations.py    # Report/reference translation mappings
│   ├── stats_collector.py         # Parallel collection workers
│   ├── storage.py                 # Atomic text/JSON writes
│   └── tanki_client.py            # Profile API and proxy-aware retries
├── proxy/
│   ├── bootstrap.py               # Source loading and runtime orchestration
│   ├── config_store.py            # Normalized proxy cache
│   ├── health_check.py            # Batched proxy probes
│   ├── checker.py                 # Independent temporary Xray runtime and ports
│   ├── models.py                  # Proxy records
│   ├── pool.py                    # Selection, task bindings, cooldowns
│   ├── sources_loader.py          # Raw source-file parsing
│   ├── sources_rewrite.py         # Preserve/filter source entries
│   ├── subscription.py            # Subscription fetching and decoding
│   ├── subscription_import.py     # VLESS URI and Xray JSON subscription import
│   ├── vless_parser.py            # URI parsing
│   ├── xray_compat.py             # Compatibility rules
│   ├── xray_config.py             # Runtime configuration generation
│   └── xray_runner.py             # Binary selection and child process
├── tests/
│   ├── fixtures/reports.json      # Synthetic report expectations
│   ├── helpers.py                 # Test support
│   └── test_*.py                  # Regression and failure-path tests
├── .github/workflows/tests.yml    # Windows/Ubuntu verification matrix
├── .env.example                   # Public configuration template
├── .gitignore                     # Runtime and secret exclusions
├── pyproject.toml                 # Ruff configuration
├── requirements.txt               # Broad dependency ranges
├── requirements.lock              # Pinned production dependencies
├── requirements-dev.txt           # Verification dependencies
├── account_icon.png               # Account-view asset
├── rounded-in-photoretrica.png     # Help/information asset
└── README.md                      # This documentation
```

Package `__init__.py` files are omitted from this diagram for readability and should remain in the source tree. Private runtime files such as `.env`, `accounts/`, proxy caches, logs, and executables are also omitted from the public-source diagram.

### Entry Point and Cog Composition

[bot.py](bot.py) creates the bot, loads configuration, configures logging, loads the command extension, and synchronizes slash commands. It also applies command blacklist checks and defines the owner-only synchronization command.

[commands/stats.py](commands/stats.py) composes the feature mixins into the `Stats` cog. It owns shared locks, the HTTP session, the proxy bootstrap object, and task startup/shutdown.

The large command implementation has been split into feature files. Keep the cog entry point focused on composition and lifecycle rather than growing another single file containing every command and subsystem.

### Main Data Path

```text
Discord command or daily trigger
             |
             v
     Collection orchestration
             |
             v
    Tanki profile API client -------- Optional Xray proxy pool
             |
             v
  Difference against saved baseline
             |
             v
  Atomic account save: baseline + pending report
             |
             +----------------------> Bound widget update attempt
             |
             v
       Discord DM attempt
             |
       +-----+----------------------+
       |                            |
    Accepted                      Failed
       |                            |
Persist recipient ack        Keep pending recipient
                                    |
                                    v
                         Retry loop after readiness
```

### Concurrency Boundaries

| Lock or mechanism | Protects |
|-------------------|----------|
| Registration lock | Concurrent account-add validation and registration |
| Collection lock | Daily and forced collection runs |
| Pool recovery lock | Collection rounds and profile requests versus final serving-pool replacement |
| Proxy check lock | Concurrent automatic, manual, and emergency scans |
| Per-account lock | Baseline/outbox update and report flushing |
| Per-user token lock | OAuth refresh state for one Discord user |
| Atomic file replacement | Individual JSON/text persistence |

These mechanisms operate inside the bot process. They do not coordinate multiple independent installations writing the same account files.

### Removed Snapshot Collector

`proxy/snapshot_collector.py` is not part of the active runtime. The former file depended on unrelated modules that are absent from this application, and it was removed during the refactor.

The active worker implementation is [utils/stats_collector.py](utils/stats_collector.py). Deploy it with the `utils` package. Do not restore the obsolete proxy collector or create a separate service for it. A private historical copy in `.refactor-backup/` is recovery material only.

## Linux Server Deployment

### What to Transfer

Transfer the application source and assets, then prepare the host-specific runtime. The following distinction is especially important when copying a Windows development folder to a Linux server.

| Item | New Linux installation | Updating an existing server |
|------|------------------------|-----------------------------|
| `bot.py`, package directories, and PNG assets | Copy | Replace with the reviewed source |
| Dependency files and `pyproject.toml` | Copy | Update together with the source |
| `.env.example` and README | Copy | Update as reference files |
| `.env` | Create for the server | Preserve the server's existing credentials and settings |
| `accounts/` | Transfer privately only when migrating real state | Preserve the existing production directory |
| `proxies_sources.txt` | Configure privately when using proxies | Preserve unless intentionally changing sources |
| `proxies.json` | Optional compatible cache | Preserve; startup uses it when it fits, and successful background checks replace it |
| `xray_config.runtime.json` | Generated by the application | Allow the application to regenerate it |
| `.xray-check-*/` | Not needed | Temporary private checker state; never publish or copy into a deployment |
| Linux `xray` executable | Install a compatible build | Keep or deliberately update the compatible build |
| Windows `xray.exe` | Not used on Linux | Not needed |
| Windows `.venv/` | Do not transfer; recreate | Maintain a Linux virtual environment |
| `__pycache__/`, Ruff caches, temporary files | Not needed | Not needed |
| `.refactor-backup/` | Not needed for runtime | Keep separately if required for private recovery |
| `tests/` and `.github/` | Optional for runtime; useful for verification | Keep if server-side checks are part of maintenance |
| Existing logs | Optional private diagnostic history | Retain according to your log policy |

An existing Linux `xray` file can be reused only if it matches the host architecture and passes validation. Its name alone does not establish compatibility.

### Prepare the Runtime

This example assumes the source has been placed in `/opt/tanki-stats`, a dedicated `tanki-stats` service user and group exist, and that user owns the application directory. Adapt the path and account names to your server.

```bash
cd /opt/tanki-stats
sudo -u tanki-stats python3.12 -m venv .venv
sudo -u tanki-stats .venv/bin/python -m pip install -r requirements.lock
sudo -u tanki-stats .venv/bin/python -m pip check
```

Create the server `.env` from the template on a new installation. For proxy mode, set:

```dotenv
XRAY_ENABLED=true
XRAY_BINARY_PATH=xray
```

Give the Linux executable permission to run:

```bash
chmod +x /opt/tanki-stats/xray
/opt/tanki-stats/xray version
```

Check private file permissions. The service user needs to read `.env` and write `accounts/`, logs, and generated proxy files. Other ordinary host users generally do not need to read the credentials.

### First Server Check

Run the bot interactively as the service user before enabling a background service:

```bash
cd /opt/tanki-stats
sudo -u tanki-stats .venv/bin/python bot.py
```

Confirm login, slash-command synchronization, and the intended routing mode. Check `/list` and `/help` from Discord. If migrating an existing installation, verify that the existing subscription list appears without re-registering users.

Pending production reports can be retried as soon as the bot becomes ready. A migration test using real account files can therefore send real messages. Use isolated test data for checks intended to avoid production delivery.

### Example systemd Service

On a systemd-based host, create `/etc/systemd/system/tanki-stats.service` using the actual deployment path and service user. This is a deployment template, not a service already installed by the repository.

```ini
[Unit]
Description=Tanki Stats Discord Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=tanki-stats
Group=tanki-stats
WorkingDirectory=/opt/tanki-stats
ExecStart=/opt/tanki-stats/.venv/bin/python /opt/tanki-stats/bot.py
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONUTF8=1
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
KillMode=control-group
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
```

The bot reads its own `.env`, so this example does not add a second credential-loading mechanism. `SIGINT` requests the Python runner's normal interrupt handling, while the control-group setting keeps the managed Xray child within the service's process scope. Review the host's systemd behavior against the [official service documentation](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml).

Enable and inspect the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tanki-stats
sudo systemctl status tanki-stats
sudo journalctl -u tanki-stats -n 100 --no-pager
```

Follow live service output when diagnosing startup:

```bash
sudo journalctl -u tanki-stats -f
```

The application also writes `bot.log` in the project directory. File rotation uses a roughly 5 MB threshold and three backup files.

### Single-Instance Operation

Run one bot process per state directory. Stop an old interactive process before starting the service, and stop the Windows installation before activating a migrated Linux installation with the same production data.

Multiple processes can independently collect, send reports, refresh OAuth tokens, or overwrite JSON state. The process-local locks do not protect against that situation.

### Migration Timing

Stop the old instance before making the final state copy. Transfer the complete `accounts/` directory rather than only visible nickname files: the metadata and pending report records are part of the application state.

After the new instance is confirmed healthy, keep the old private backup until delivery and the next collection have been reviewed. Do not leave the old bot running merely as a backup.

## Updates, Backups, and Recovery

### Update Procedure

1. Review the source change and any configuration or dependency changes.
2. Stop the running bot or service.
3. Back up the current source, `.env`, `accounts/`, and private proxy sources.
4. Replace application source and assets with the reviewed revision.
5. Preserve production state and credentials.
6. Install the corresponding dependency lock in the server virtual environment.
7. Run available verification in an isolated environment when practical.
8. Start the bot and inspect its logs.
9. Check subscription visibility, pending delivery, and routing.

Do not overwrite a working server `.env` with a developer's file. Update individual settings deliberately. Likewise, do not replace the production account directory with an empty development directory.

### What to Back Up

| Backup item | Reason |
|-------------|--------|
| `accounts/` in full | Preserves subscriptions, baselines, pending reports, language choices, and widget tokens |
| `.env` | Preserves application credentials and deployment settings |
| `proxies_sources.txt` or its configured replacement | Preserves private proxy sources |
| Source revision and dependency lock | Makes restoration reproducible |
| Xray version and compatible binary, where appropriate | Preserves a known working runtime combination |
| Relevant logs | Helps reconstruct the failure and migration history |

Protect backups with access controls appropriate for credentials. A public archive containing `.env` or `user_tokens.json` is not a safe source release.

### Consistent State Copies

Stop the bot before taking a migration or recovery snapshot of the account directory. Atomic writes protect individual files, but copying a changing collection of files does not produce an application-wide point-in-time snapshot.

Keep backup date and source revision information together. Restoring only old baselines while retaining a newer outbox can create confusing report periods and delivery history.

### Restoring a Backup

Stop the process, restore the intended source and matching dependencies, restore the complete private state, verify file ownership, and start one instance. Inspect JSON validity and startup logs before assuming the restored installation is healthy.

Restoring an older backup can bring back reports that were delivered after the backup was taken. Those reports can be sent again because their acknowledgements are absent from the restored state. Account for that possibility when choosing a recovery point.

### Dependency Updates

Update dependencies in a development copy first. Run the regression suite and lint checks, then review the new lock file before deployment. UI-component support, Discord API behavior, and Xray compatibility are particularly relevant to this project.

Avoid installing unreviewed latest packages directly into production to resolve an unrelated problem. A binary-platform mismatch is fixed by the correct executable; it is not normally fixed by changing the Python dependency set.

## Testing and Verification

### Local Verification Commands

Create or use a development virtual environment and install the verification dependencies:

```console
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m unittest discover -v
```

Here `python` means the selected virtual environment's interpreter. On Windows it can be replaced with `.\.venv\Scripts\python.exe`; on Linux with `.venv/bin/python`.

### Test Coverage

| Test module | Main areas |
|-------------|------------|
| `test_reports.py` | Original report differences, language-specific embeds, views, widget payload, rank boundaries |
| `test_commands.py` | Command loading, registration behavior, locale handling, widget command behavior |
| `test_storage.py` | Subscription records, reserved filenames, atomic persistence, token state |
| `test_delivery.py` | Persistent outbox, partial delivery, retries, acknowledgement failures |
| `test_collector.py` | Parallel collection, retries, exhaustion, cancellation, failure accounting |
| `test_client.py` | Profile API responses, timeouts, proxy failures, rate-limit behavior |
| `test_proxy_lifecycle.py` | Parallel registration and daily delivery during scanning, independent ports/configs, serialized checks, cancellation, shutdown, and replacement rollback |
| `test_proxy_health.py` | Health-check failure summaries, accepted responses, unsupported VLESS flows, and invalid user IDs |
| `test_proxy_refresh.py` | Early stopping, honest checked/failed/unchecked counts, fresh source parameters, complete manual checks, worker cancellation, and configurable intervals |
| `test_proxy_sources.py` | Masked source entries, aggregate diagnostics, credential-safe parser logs, valid IPv6 addresses, and plain/Base64 subscription decoding |
| `test_proxy_startup.py` | Cached startup without downloads, missing and oversized caches, background pool creation, and cache preservation after a failed refresh |
| `test_proxy_progress.py` | Visible queue and subscription stages, initial probe counter, responsive parsing, and updates to the same Discord message |
| `test_proxy_import.py` | Connection-aware deduplication, transport settings, Xray JSON import, cache round trips, bounded retries/timeouts, and listener readiness |

The most recent local verification passed 118 unit tests on Python 3.12. Ruff checks and dependency consistency checks also passed during the implementation verification. A separate integration check validated seven generated configurations with Xray 26.3.27 and reached a local profile API through real VLESS WebSocket, gRPC, and HTTPUpgrade routes, including a JSON-imported route.

Synthetic fixtures compare the refactored reports, views, and widget payload with the original behavior. They are test data rather than exported production snapshots.

### Network Isolation

The unit tests use mocked API and Discord operations and temporary storage. They do not log in the production bot, contact real subscribers, or launch a daily reporting run against live account files.

Proxy lifecycle tests exercise controlled failure and cancellation behavior. A separate local Windows check ran two real Xray processes: the serving process handled 132 successful requests to a synthetic local API during two checker starts, keeping its PID and configuration. Both processes stopped and the temporary checker configuration was removed. Those checks do not establish Linux production behavior or remote proxy availability.

### Continuous Integration

[tests.yml](.github/workflows/tests.yml) defines checks for Python 3.12 and 3.13 on Ubuntu and Windows. It installs development dependencies, runs Ruff lint and format checks, and executes the unit suite. The workflow sets UTF-8 mode and disables Xray for those unit-test jobs.

The workflow is prepared for repository publication. Until it runs on the published repository, the matrix should be described as configured rather than remotely verified. This README does not display an invented passing CI badge.

### Practical Acceptance Checks

After deployment, verify login, command availability, preserved account subscriptions, and DM access with an appropriate test user. Confirm direct or proxy routing from logs and check that the service runs only once.

Use `!statscheck` for collection diagnostics that should preserve the baseline. Use forced collection only when sending follower reports and advancing the baseline are intended.

Widget acceptance requires the correct application, OAuth setup, a valid identity binding, and saved game statistics. A passing report test alone cannot confirm live profile authorization.

## Compatibility and Known Limitations

### Platform Scope

The source and CI configuration target Windows and Linux environments with Python 3.12 or 3.13. Local runtime verification was performed on Windows with Python 3.12. Linux deployment instructions are provided, but this documentation does not claim that a particular remote server has already been validated.

The Xray executable must independently match the platform and architecture. A working Windows Python environment does not make a Linux executable usable on Windows, and the reverse is also true.

### External Services

The bot depends on the current Tanki profile API and Discord interfaces. Upstream field changes, profile availability, rate limits, service outages, or changes to widget eligibility can affect features without a local source change.

Retries and proxy recovery improve resilience within configured limits. They cannot guarantee access when the API is unavailable, every proxy fails, or Discord refuses a message or profile write.

### Reporting Scope

Reports summarize differences in saved cumulative statistics. There is no per-battle archive, strict calendar-day history, missed-day reconstruction, or independent baseline for each subscriber of a nickname.

The current renderer does not paginate oversized equipment reports. Discord message and embed limits still apply; persistent sending failures for a large report require inspection rather than unlimited blind retries.

### Storage Scope

Storage is local, single-process JSON. There is no database replication, distributed lock, built-in encryption, automatic backup scheduler, or universal damaged-file repair routine.

The pending-report queue has no expiration or size cap. It preserves delivery state but can grow for users who remain unreachable.

### Widget Scope

The widget requires application-specific authorization and a valid Discord identity profile context. The code attempts identity resolution but cannot invent an authorized identity when Discord does not provide one.

The widget uses saved snapshots, and failed profile writes are not part of the persistent DM queue. Manual refresh and a later applicable collection are its current retry paths.

### Presentation and Localization

Custom emoji IDs, asset filenames, project links, and the widget's configured game reference reflect the current application. Operators deploying a different application should review them.

Supported user-facing translations do not mean every source comment, log, command description, or administrator response is English. Unknown upstream item names can appear without a translated equivalent.

## Troubleshooting

### The Bot Exits Because the Token Is Missing

Set `BOT_TOKEN` in the `.env` next to `bot.py`, or provide it through the process environment. Check that the file is actually named `.env`, not `.env.txt`.

If both locations contain a value, the existing process environment wins. A service with an old environment value can therefore continue using the old token after a file edit. Inspect configuration privately without printing the token into shared logs.

### Discord Login Fails

Confirm that the credential is the bot token for the intended application, rather than the client secret or an OAuth access token. Check for accidental whitespace or an incomplete copy.

If replacing the application, configure its permissions and widget secret separately. A successful login with a new token does not isolate the existing account directory.

### Privileged Intent Errors or Prefix Commands Do Not Respond

Enable Message Content Intent in the application's Bot settings. The source requests `message_content=True`, and prefix commands require the corresponding message content.

Also verify the administrator allowlist for maintenance commands, the owner's status for `!sync`, command spelling, and blacklist state. Slash-command access and prefix-command authorization are separate checks.

### Slash Commands Are Missing

Inspect startup logs for extension-loading and synchronization errors. Confirm that the application was installed with command access and that you are interacting with the intended bot.

Global command updates can require propagation. The owner can use `!sync` after fixing the underlying issue. Repeated synchronization will not repair an import failure caused by missing feature files or an old dependency version.

### `LayoutView` or UI Classes Are Unavailable

Install the locked dependencies in the interpreter that actually launches the bot. An older system-wide `discord.py` can still be used accidentally if the service's `ExecStart` points outside the virtual environment.

Check the executable path and package version. Reinstalling packages in a different environment does not change the running service's imports.

### Windows Reports `WinError 193`

The selected executable is not a valid Windows binary. A common cause is explicitly pointing `XRAY_BINARY_PATH` to a Linux file named `xray`.

Install the official Windows build, use `xray.exe`, and set `XRAY_BINARY_PATH=xray.exe` or leave automatic selection enabled. Verify it independently:

```powershell
.\xray.exe version
```

Both platform binaries may coexist in a private development folder. An explicit path must still select the correct one.

### Linux Reports Permission Denied or an Executable Format Error

Check execute permission, the configured path, and CPU architecture:

```bash
chmod +x ./xray
file ./xray
./xray version
```

Permission denied can also reflect directory permissions or mount settings. An executable-format error can indicate a Windows build on Linux or an incompatible architecture. Use the correct official Linux build rather than renaming another platform's file.

### Xray Rejects the Configuration

Inspect the validation error for the unsupported transport or missing parameter. Compatibility filtering removes known unsupported cases, but a parsed URI can still contain settings that the generator or installed Xray build cannot use.

When the generated configuration exists, test it with the selected binary:

```bash
./xray run -test -c xray_config.runtime.json
```

On Windows, use `.\xray.exe` in place of `./xray`. This validates configuration; it does not prove every remote connection works.

### No Proxies Are Loaded

Check `PROXIES_SOURCES`, source-file contents, subscription availability, and the logs for compatibility rejections. Empty, expired, or malformed subscription responses can leave the pool empty.

Check whether the existing cache is the one you intended to use. Startup skips missing, empty, or oversized caches and lets the background check build a working pool. An oversized-cache warning does not require deleting the cache: a successful check replaces it. The legacy `REFRESH_PROXIES_ON_START` setting does not force a foreground source download. With proxies disabled, no active pool is expected.

### Every Local Proxy Port Is Refused

Confirm that the managed Xray process started successfully and that the generated local ports match the active configuration. A parsed cache is not proof that Xray is listening.

Inspect startup and child-process errors before changing API retry counts. Increasing retry limits cannot open ports belonging to a process that never launched.

### The API Repeatedly Returns HTTP 429

Reduce collection concurrency, review worker delays, and inspect proxy health and cooldowns. The response is a rate limit, not necessarily a broken tunnel.

A health check can mark that route reachable while normal collection still receives 429. Avoid immediately classifying every rate-limited proxy as permanently invalid.

### Adding an Account Fails

Check the nickname, current subscription count, duplicate nickname, duplicate alias, and DM availability. A missing player and a temporary network error require different remedies.

The account limit is three subscriptions per user. Changing a display alias does not permit a duplicate subscription to the same nickname.

### Daily Reports Do Not Arrive

Confirm the bot was running at 02:00 UTC, that collection succeeded, and that the user still follows the account. Check direct-message permissions and pending report entries.

A report can be saved but undelivered. The retry loop cannot override a user's DM restrictions. If the bot was offline at the trigger, it does not reconstruct a separate snapshot for that missed day.

### A Report Covers More or Less Than One Day

Inspect the last successful snapshot time and recent forced collections. Failed collection lengthens the next interval; a successful forced run shortens it.

The bot compares saved snapshots rather than a separate daily history endpoint. This is expected behavior unless the baseline was altered incorrectly.

### Duplicate Reports Appear After a Crash or Restore

Check whether Discord accepted the message before its acknowledgement was saved, or whether an older backup restored the report's pending state.

The delivery mechanism is at-least-once. Preserve logs and queue state when diagnosing repeated duplicates; do not delete all account files as a general fix.

### A Removed or Blacklisted User Still Receives Messages

Removing a subscription prevents later outbox delivery for that account once membership is checked. Blacklisting only blocks command invocation and does not remove subscriptions.

If the intended action is to stop tracking, use the subscription workflow rather than assuming the command blacklist revokes delivery. A message already accepted by Discord cannot be recalled by a later subscription change.

### Widget Authorization Fails

Check the application ID, client secret, registered redirect URI, and copied code. The code must belong to the intended authorization flow and should be used promptly.

If the bot token now belongs to another application, repeat authorization with that application's secret. Stored credentials from the former application are not transferable.

### Widget Refresh Reports an Identity Error

Use the identity ID returned for the authorized Discord application context. It is distinct from the Tanki nickname. If automatic lookup fails or multiple identities are available, pass the appropriate `provider_user_id` explicitly.

A 403 can reflect missing authorization; a 400 can reflect identity or payload constraints. Inspect the sanitized remote error instead of repeatedly guessing new IDs.

### Widget Values Are Old

`/widget_refresh` publishes saved data. Check the last successful collection and the selected account binding. The command itself does not request a new Tanki snapshot.

If a different account was collected, automatic publication may correctly skip it because the widget is bound to another nickname.

### Token Refresh Cannot Save Its Result

Check filesystem permissions, disk space, and JSON validity in the private token file. A damaged token store is intentionally not silently overwritten with an empty one.

Stop the bot and restore a trusted backup when necessary. Preserve bindings and other users' records rather than replacing the entire store to fix one authorization.

### Language Changes Are Not Reflected in Reports

Check whether the user chose a manual language. In automatic mode, interact with a slash command after changing the Discord client locale so the saved detected locale can update.

Daily delivery uses persisted language state and cannot independently observe a changed Discord client setting.

### PyNaCl or Voice-Related Warnings Appear

The application does not implement voice functionality. A warning about an optional voice dependency such as PyNaCl does not by itself prevent tracking, slash commands, or DM reports.

Investigate the actual login, import, API, or proxy error if those functions fail. Installing voice dependencies is not the remedy for an unrelated Xray binary error.

### The Service Works Differently From an Interactive Terminal

Compare the service's interpreter, working directory, user, environment, and file permissions. Verify that the service user can read configuration and write runtime data.

Inspect both the journal and `bot.log`. Also check that the terminal process has been stopped so two instances are not using the same files.

### Should `snapshot_collector.py` Be Deleted?

The obsolete file under `proxy/` is not required and is already absent from the active source. Its archived copy can remain privately in `.refactor-backup/`, which is not deployed.

Keep `utils/stats_collector.py`. That file is the live collection implementation used by the bot.

## Release and GitHub Publication

### Public Source Contents

A public source repository should contain the application packages, assets, dependency files, configuration template, verification workflow, tests, and documentation. Private runtime data should remain outside the publication.

The project has a [.gitignore](.gitignore) for local configuration, account records, proxy sources and caches, generated runtime configuration, executables, logs, virtual environments, and private refactor backups.

Ignore rules only affect untracked files. They do not remove a secret that was already committed or protect files accidentally included in a separate archive. Inspect the actual staged contents before publishing.

### Publication Review

Before the first push, verify the following:

1. `.env.example` contains placeholders and defaults rather than live credentials.
2. `.env`, `accounts/`, private proxy files, logs, binaries, and backups are excluded.
3. Report fixtures are synthetic and do not contain production user data.
4. Administrator IDs, policy links, emoji references, and application-specific presentation are intentional.
5. Local tests and lint checks pass for the source being published.
6. The README describes implemented behavior and its current limitations.
7. License and ownership terms have been decided before presenting the project as licensed open-source software.

After Git initialization and staging, inspect the file list and changes:

```console
git status --short
git diff --cached --name-only
git diff --cached
```

These commands are a review step, not an instruction to publish the entire working folder blindly. Review the output privately if credentials may already have been staged.

### Repository Metadata

Add the actual repository URL, release tags, and CI badge only after the repository exists and those references are valid. The project currently has no declared application version in a package manifest, so this README does not borrow a version number from another project.

When creating releases, describe the concrete behavior changed, supported migration path, dependency or Xray requirements, and relevant verification. Avoid promising perfect availability or exactly-once messaging.

### Release Archives

Build source archives from reviewed public files rather than zipping the complete development directory. Keep credentials, subscribers, token stores, logs, caches, and `.refactor-backup/` out of the archive.

Do not bundle an executable merely because it happens to be present locally. If a release includes third-party binaries, review their platform labeling and distribution terms separately. A source-only release can direct operators to official Xray downloads.

## Maintenance Guidelines

### Routine Operation

Check startup and collection summaries, persistent delivery failures, account-directory growth, proxy availability, and service restart frequency. A process that remains online can still have a failing collection or delivery path.

Keep the system clock accurate and record UTC collection times when investigating report periods. Separate the time a report was created from the time it was finally delivered.

### Changes to Command Behavior

Preserve existing command names and option meanings unless a deliberate user-facing migration is planned. Keep long-running slash commands deferred and use follow-up responses after the initial acknowledgement.

For subscription changes, test account limits, duplicate aliases, shared nicknames, reserved filenames, and concurrent registration. For administrative additions, preserve authorization and document side effects.

### Changes to Statistics

Review normalization, missing-item comparisons, negative counters, rank boundaries, and output ordering against the report fixtures. Changing a baseline rule can affect all followers of an account.

If the upstream API changes, capture sanitized representative payloads in test fixtures. Avoid adding real subscriber IDs or credentials to regression data.

### Changes to Delivery

Persist a report before sending it and acknowledge recipients after successful delivery. Keep retry ordering and unsubscribe checks intact.

Test partial success and persistence failures, not only a successful send. Preserve the documented at-least-once semantics unless a new design explicitly addresses the remote/local acknowledgement gap.

### Changes to Proxies and Lifecycle

Keep pool replacement coordinated with collection and preserve bounded recovery. Validate the final runtime configuration and test cancellation paths when modifying the runner or health checker.

Do not broaden the accepted VLESS syntax without implementing and testing the corresponding Xray settings. A parser accepting a parameter is not sufficient evidence that routing uses it correctly.

### Documentation Maintenance

Update this README when changing command options, source-defined intervals, environment defaults, data shape, dependency policy, or deployment requirements. Keep `.env.example` and the configuration tables consistent.

Separate verified results from prepared checks. A local Windows run, a mocked test, and a remote Ubuntu CI run provide different evidence and should be described accordingly.

## License and Project Status

The repository currently does not include a license file or declare a release version. This documentation does not assign MIT, Apache, proprietary extension terms, or any other license to the bot.

Before public distribution, the owner should select the intended licensing terms and add the corresponding file. Third-party dependencies and optional Xray binaries retain their respective licenses independently of that decision.

Tanki Stats is an independent project using public game-profile data and Discord interfaces. This README does not claim official affiliation with Tanki Online, Discord, or Xray.

The source includes a modular command implementation, persistent report delivery, regression tests, and a prepared verification workflow. GitHub publication, actual remote CI results, and production Linux acceptance should be recorded when those steps are completed.

## References and Acknowledgements

The project relies on Python, `discord.py`, `aiohttp`, the Tanki Ratings profile service, and optional Xray-based VLESS routing. Their availability and interfaces make the current collection and delivery workflow possible.

For external configuration and API details, consult the primary sources:

- [Discord Developer Portal](https://discord.com/developers/applications) for application configuration.
- [Discord Gateway documentation](https://docs.discord.com/developers/events/gateway#privileged-intents) for intents and gateway requirements.
- [Discord OAuth2 documentation](https://docs.discord.com/developers/topics/oauth2) for authorization and token flows.
- [Discord Application Identity Profile documentation](https://docs.discord.com/developers/resources/application-identity-profile) for profile payload and authorization rules.
- [Official Xray-core releases](https://github.com/XTLS/Xray-core/releases) for platform-specific runtime downloads.
- [systemd service documentation source](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml) for Linux service behavior.

For application-specific behavior, the source modules and regression tests linked throughout this README are the implementation reference. When external documentation and current code differ, investigate the affected integration rather than assuming the discrepancy cannot affect runtime behavior.
