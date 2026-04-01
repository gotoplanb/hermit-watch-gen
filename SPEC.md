# Hermit Watch — State Generator Repo Spec

## Purpose

A public GitHub repository that generates state JSON files for Hermit Watch. It runs on a schedule via GitHub Actions, fetches status from well-known public status pages, normalizes each signal to the Hermit Watch state enum, and commits one JSON file per source signal into a `sources/` directory.

This repo serves as:
- The default data source baked into the Hermit Watch app
- A reference implementation for anyone writing their own generator
- A live test harness during iOS and watchOS development (edit JSON files manually to simulate any state)

Anyone can fork this repo, add their own sources, and point the Hermit Watch app at their fork's raw GitHub URLs.

---

## The State Enum

Every generator, regardless of complexity, produces exactly one of these five states:

| State | Color | Meaning |
|-------|-------|---------|
| `serene` | Green | Better than baseline / all clear |
| `calm` | Blue | Nominal / operational |
| `unsettled` | Yellow | Worth watching / degraded |
| `squall` | Orange | Actively degrading / partial outage |
| `storm` | Red | Incident / major outage |

A sixth implicit state exists only in the app: if the JSON cannot be fetched or parsed, the app renders grey (`unknown`). This is handled client-side — generators never emit `unknown`.

Numeric aliases are equivalent: `1` = `storm`, `2` = `squall`, `3` = `unsettled`, `4` = `calm`, `5` = `serene`. Generators may emit either form.

Common mappings for generator authors:

| Statuspage indicator | DEFCON | PagerDuty Priority | → State |
|----------------------|--------|--------------------|---------|
| `none` (all operational) | 5 | P5 | `serene` |
| `none` (minor component) | 4 | P4 | `calm` |
| `minor` | 3 | P3 | `unsettled` |
| `major` | 2 | P2 | `squall` |
| `critical` | 1 | P1 | `storm` |

---

## Source JSON Schema

Each source is a single JSON file. This is the complete schema:

```json
{
  "updated_at": "2026-03-31T17:07:00Z",
  "state": "calm",
  "display_name": "GitHub Actions",
  "message": "All systems operational",
  "url": "https://www.githubstatus.com"
}
```

### Field reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `updated_at` | ISO 8601 string | Yes | UTC timestamp of last generator run |
| `state` | string or int | Yes | One of five named states or 1–5 |
| `display_name` | string | Yes | Human label for this signal, e.g. "GitHub Actions" |
| `message` | string or object | No | Detail shown in iPhone app on tap |
| `url` | string | No | Deep link into source system for investigation |

### The `display_name` field

The generator knows what it is monitoring and should say so. `display_name` is the suggested label the Hermit Watch app uses when a user adds this source. The user can override it locally in the app without affecting the JSON.

### The `message` field

Either a plain string or an object with arbitrary keys. The app renders `message.summary` if the value is an object, otherwise renders the string directly. Unknown keys are ignored. This allows the same JSON payload to be consumed by other tooling (Slack bots, status boards, webhooks) beyond the Hermit Watch app.

```json
// simple
"message": "Elevated error rate on push events"

// extended
"message": {
  "summary": "Elevated error rate on push events",
  "incident_id": "INC-4821",
  "severity": "P2",
  "started_at": "2026-03-31T16:45:00Z"
}
```

### The `url` field

An escape hatch to wherever the real details live — a PagerDuty incident, Sumo Logic search, Linear ticket, or internal runbook. The Hermit Watch app surfaces this as a tappable link in the source detail view. Never required.

---

## Repo Structure

```
hermit-watch-state/
├── README.md
├── .github/
│   └── workflows/
│       └── update-status.yml
├── generators/
│   ├── __init__.py
│   ├── base.py                  # shared fetch, normalize, write logic
│   ├── statuspage.py            # generic Statuspage.io fetcher
│   ├── github_actions.py        # GitHub Actions specifically
│   ├── github_prs.py            # GitHub Pull Requests
│   ├── github_packages.py       # GitHub Packages
│   ├── github_pages.py          # GitHub Pages
│   ├── github_codespaces.py     # GitHub Codespaces
│   ├── anthropic_api.py         # Anthropic API
│   └── aws_status.py            # AWS (stretch goal, non-Statuspage format)
├── sources/                     # output directory, one JSON file per signal
│   ├── github-actions.json
│   ├── github-prs.json
│   ├── github-packages.json
│   ├── github-pages.json
│   ├── github-codespaces.json
│   ├── anthropic-api.json
│   └── aws-us-east-1.json
├── config.yml                   # maps source filenames to generator config
├── run.py                       # entrypoint
└── tests/
    ├── test_normalize.py
    ├── test_statuspage.py
    └── fixtures/
        └── statuspage_response.json
```

---

## config.yml

Declarative mapping of output filenames to generator configuration. Adding a new Statuspage.io-compatible source requires only a new block here — no Python changes.

```yaml
sources:
  github-actions:
    generator: statuspage
    api_url: https://kctbh9vrtdwd.statuspage.io/api/v2/summary.json
    component: "Actions"
    display_name: GitHub Actions
    url: https://www.githubstatus.com

  github-prs:
    generator: statuspage
    api_url: https://kctbh9vrtdwd.statuspage.io/api/v2/summary.json
    component: "Pull Requests"
    display_name: GitHub Pull Requests
    url: https://www.githubstatus.com

  github-packages:
    generator: statuspage
    api_url: https://kctbh9vrtdwd.statuspage.io/api/v2/summary.json
    component: "Packages"
    display_name: GitHub Packages
    url: https://www.githubstatus.com

  github-pages:
    generator: statuspage
    api_url: https://kctbh9vrtdwd.statuspage.io/api/v2/summary.json
    component: "Pages"
    display_name: GitHub Pages
    url: https://www.githubstatus.com

  github-codespaces:
    generator: statuspage
    api_url: https://kctbh9vrtdwd.statuspage.io/api/v2/summary.json
    component: "Codespaces"
    display_name: GitHub Codespaces
    url: https://www.githubstatus.com

  anthropic-api:
    generator: statuspage
    api_url: https://status.anthropic.com/api/v2/summary.json
    component: "API"
    display_name: Anthropic API
    url: https://status.anthropic.com
```

Note: Multiple sources can share the same `api_url` when a single Statuspage endpoint covers multiple components (as GitHub's does). The generator fetches once per unique URL and extracts the relevant component.

---

## Generator Logic

### base.py

Shared utilities used by all generators:

- `fetch_json(url)` — GET with 10-second timeout, returns parsed JSON or raises
- `normalize_state(raw)` — maps any known severity vocabulary to the five-state enum. Accepts named states, numeric aliases, and Statuspage indicator values
- `write_source(filename, state, display_name, message, url)` — writes `sources/{filename}.json` with correct `updated_at` in UTC ISO 8601
- `stale_source(filename, last_state, reason)` — preserves last known state but updates message to indicate fetch failure. The app sees a real color, not grey, but the message explains the uncertainty

### statuspage.py

Generic fetcher for any Statuspage.io v2 API. Accepts an `api_url` and optional `component` name.

If `component` is specified: find that component in the response, map its `status` field to a state, use the component name as context in the message.

If no `component` is specified: use the top-level `indicator` field.

Component status mapping:

| Statuspage component status | → State |
|-----------------------------|---------|
| `operational` | `serene` if indicator also `none`, else `calm` |
| `degraded_performance` | `unsettled` |
| `partial_outage` | `squall` |
| `major_outage` | `storm` |

Message is built from any active incidents affecting the component. If no incidents, message is `"All systems operational"`.

### run.py

- Reads `config.yml`
- Deduplicates API URLs (fetch each unique URL once)
- Iterates sources, calls appropriate generator with cached API response
- Writes source JSON files to `sources/`
- Exits code 0 on full success, code 1 if any source failed

---

## GitHub Actions Workflow

`.github/workflows/update-status.yml`:

```yaml
name: Update Status

on:
  schedule:
    - cron: '*/5 * * * *'   # every 5 minutes
  workflow_dispatch:          # manual trigger for testing

jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install -r requirements.txt

      - run: python run.py

      - name: Commit updated sources
        run: |
          git config user.name "hermit-watch-bot"
          git config user.email "bot@hermitwatch"
          git add sources/
          git diff --staged --quiet || git commit -m "chore: update source states $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          git push
```

The `git diff --staged --quiet ||` guard prevents a commit when no states changed — keeps history clean.

---

## Source File URLs

Once the repo is public, source files are accessible at:

```
https://raw.githubusercontent.com/{owner}/hermit-watch-state/main/sources/{filename}.json
```

Example:
```
https://raw.githubusercontent.com/gotoplanb/hermit-watch-state/main/sources/github-actions.json
```

These are the URLs the Hermit Watch app polls directly. No server, no API, no auth.

---

## Tests

All generators must have tests. Use `pytest`.

### test_normalize.py
- All Statuspage indicator values map to correct states
- Numeric aliases 1–5 map correctly
- Named state strings map correctly
- `serene` emitted when indicator is `none` and all components operational
- `calm` emitted when indicator is `none` but not all components operational
- Unknown values raise a descriptive error

### test_statuspage.py
- Uses fixture JSON (real captured Statuspage API response)
- Correct state and message for all-operational response
- Correct state and message for degraded component
- Correct state and message for partial outage
- Component filtering works correctly when `component` is specified
- Falls back to top-level indicator when no `component` specified

### fixtures/statuspage_response.json
Real captured response from `kctbh9vrtdwd.statuspage.io/api/v2/summary.json`. Used in tests to avoid network calls.

---

## requirements.txt

```
requests>=2.31.0
pyyaml>=6.0
pytest>=8.0
responses>=0.25.0
```

---

## README.md Requirements

The README is also the generator authoring guide. Must cover:

1. What this repo does — one paragraph
2. The state enum — five states, colors, meaning
3. Source JSON schema — full field reference with examples
4. How to add a new Statuspage.io source — add a block to `config.yml`, no code needed
5. How to write a custom generator — subclass `BaseGenerator`, implement `fetch_state()`, return a `SourceResult`
6. The raw GitHub URL format for source files
7. Running locally — `pip install -r requirements.txt && python run.py`
8. Running tests — `pytest`

---

## Definition of Done

- [ ] `run.py` executes without error locally
- [ ] All configured sources write valid JSON to `sources/`
- [ ] `updated_at` is always a valid UTC ISO 8601 timestamp
- [ ] `state` is always one of the five valid string values
- [ ] `display_name` is always present and non-empty
- [ ] GitHub Actions workflow runs on schedule and commits changes
- [ ] No commit is made when all source states are unchanged
- [ ] Deduplication: shared Statuspage API URLs fetched only once per run
- [ ] All tests pass (`pytest` exits 0)
- [ ] README covers schema and custom generator authoring
- [ ] All source files publicly accessible via raw.githubusercontent.com

---

## Out of Scope

- iOS or watchOS app
- Authentication — all Phase 1 sources are public APIs
- AWS generator (their format differs significantly from Statuspage.io, stretch goal)
- Collectibles
- Any manifest file format (that lives in the iOS spec)

---

## Notes for the Claude Code Session

- Keep generators as simple as possible — this is a reference implementation others learn from
- The `config.yml` pattern is intentional — adding a new Statuspage.io source must never require editing Python
- Deduplicate API fetches: GitHub's endpoint covers all GitHub components, fetch it once per run
- Prefer explicit error handling over silent failures — a source that fails to update should write a stale file with an explanatory message rather than leave the previous file untouched or crash the run
- Commit messages from the bot should be minimal and consistent
- The repo should be immediately forkable and useful by someone who has never seen the iOS app
