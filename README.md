# Hermit Watch — State Generator

Generates JSON status files for the [Hermit Watch](https://github.com/gotoplanb/hermit-watch) app by polling public status pages. Runs every 5 minutes via GitHub Actions, commits updated state files to `sources/`, and serves them as raw GitHub URLs — no server, no API, no auth.

## State Enum

Every source file contains exactly one of five states:

| State | Color | Meaning |
|-------|-------|---------|
| `serene` | Green | Better than baseline / all clear |
| `calm` | Blue | Nominal / operational |
| `unsettled` | Yellow | Worth watching / degraded |
| `squall` | Orange | Actively degrading / partial outage |
| `storm` | Red | Incident / major outage |

Numeric aliases are equivalent: `1` = storm, `2` = squall, `3` = unsettled, `4` = calm, `5` = serene.

## Source JSON Schema

Each file in `sources/` follows this schema:

```json
{
  "updated_at": "2026-03-31T17:07:00Z",
  "state": "calm",
  "display_name": "GitHub Actions",
  "message": "All systems operational",
  "url": "https://www.githubstatus.com"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `updated_at` | ISO 8601 string | Yes | UTC timestamp of last generator run |
| `state` | string or int | Yes | One of five named states or 1–5 |
| `display_name` | string | Yes | Human label for this signal |
| `message` | string or object | No | Detail shown in app on tap |
| `url` | string | No | Deep link into source system |

The `message` field can be a plain string or an object. If an object, the app renders `message.summary`.

```json
"message": {
  "summary": "Elevated error rate on push events",
  "incident_id": "INC-4821",
  "severity": "P2"
}
```

## Adding a Statuspage.io Source

Add a block to `config.yml` — no Python changes needed:

```yaml
sources:
  my-service:
    generator: statuspage
    api_url: https://status.example.com/api/v2/summary.json
    component: "Web App"          # optional: specific component name
    display_name: My Service
    url: https://status.example.com
```

If `component` is omitted, the top-level status indicator is used.

## Writing a Custom Generator

For non-Statuspage sources, create a new module in `generators/` that exports a function with this signature:

```python
def get_state(api_response: dict, component: str | None = None) -> tuple[str, str]:
    """Return (state, message) from the API response."""
```

Then register it in `run.py`'s `GENERATOR_MAP`:

```python
GENERATOR_MAP = {
    "statuspage": statuspage.get_state,
    "my_custom": my_custom.get_state,
}
```

Use `generators.base` utilities:
- `normalize_state(raw)` — maps named states, numeric aliases, and Statuspage indicators
- `write_source(filename, state, display_name, message, url)` — writes the JSON file
- `stale_source(filename, last_state, reason, display_name, url)` — preserves last state on failure

## Source File URLs

Once the repo is public, source files are at:

```
https://raw.githubusercontent.com/{owner}/hermit-watch-gen/main/sources/{filename}.json
```

These are the URLs the Hermit Watch app polls directly.

## Running Locally

```bash
pip install -r requirements.txt
python run.py
```

## Running Tests

```bash
pytest
```
