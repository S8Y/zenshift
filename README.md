# ZenShift

**OpenCode Zen API key rotation manager for Hermes Agent.**

![version](https://img.shields.io/badge/version-0.1.0-blue)
![hermes](https://img.shields.io/badge/hermes-v2026.4.16+-purple)

Automatically rotate OpenCode Zen API keys to avoid rate limits and dead key
downtime. Dashboard UI + agent integration in one plugin.

---

## Features

- **Manage multiple Zen API keys** — add, remove, view masked keys
- **Three rotation strategies:**
  - `session` — rotate on each new agent session
  - `timed` — rotate every N seconds (default: 600s / 10 min)
  - `api_call` — rotate after N tool calls
- **Auto-blacklist dead keys** — 404/401/403 responses blacklist for 24h
- **Rate-limit auto-rotation** — 429 / quota errors trigger rotate immediately
- **Env integration** — writes active key to `~/.hermes/.env` as
  `OPENCODE_ZEN_API_KEY`
- **Agent integration** — patches Hermes error classifier + client for
  fully automatic operation

## Installation

```bash
# Clone into Hermes plugins directory
git clone https://github.com/zo/zenshift ~/.hermes/plugins/zenshift

# Enable in config.yaml
hermes config set plugins.enabled += zenshift
```

**Requires:** `hermes >= v2026.4.16` (dashboard plugin system).

## Usage

### Dashboard UI

1. Start the dashboard: `hermes dashboard`
2. Open the **ZenShift** tab (appears after Config)
3. Paste your Zen API keys (one per line) → **Save Keys**
4. Configure rotation strategy + parameters → **Apply**

### API Routes

All routes mounted at `/api/plugins/zenshift/`:

| Method | Path              | Description                  |
|--------|-------------------|------------------------------|
| GET    | `/status`         | Plugin status + active key   |
| GET    | `/keys`           | List all keys (masked)       |
| POST   | `/keys`           | Replace key list             |
| POST   | `/rotate`         | Force rotate to next key     |
| POST   | `/config`         | Update rotation strategy     |
| POST   | `/report-error`   | Report API error for action  |
| POST   | `/report-tool-call` | Count tool call (api_call) |
| POST   | `/reset-session`  | Reset session counter        |
| GET    | `/check-timed`    | Check timed rotation due     |

### CLI Commands

```bash
# Force rotate the active key
zenshift rotate-now

# Check current status
curl http://127.0.0.1:9119/api/plugins/zenshift/status
```

## Architecture

```
~/.hermes/plugins/zenshift/
├── __init__.py                  # Agent plugin registration
├── plugin.yaml                  # Plugin manifest
├── zenshift_integration.py      # Agent integration (error feed, key injection)
├── dashboard/
│   ├── manifest.json            # Dashboard plugin manifest
│   ├── plugin_api.py            # FastAPI backend (9 routes)
│   └── dist/
│       ├── index.js             # React frontend (Preact SDK)
│       └── style.css            # Dashboard styles
```

## State

- **Key list + config** persisted to `~/.hermes/zenshift-state.json`
- **Active key** synced to `~/.hermes/.env` as `OPENCODE_ZEN_API_KEY`
- **Blacklist** persists across restarts (24h expiry, wall-clock)

## Development

```bash
# Frontend
cd dashboard
npm install
npm run build
```

The frontend uses the Hermes Plugin SDK (`window.__HERMES_PLUGIN_SDK__`).
API calls use `API_BASE = "/api/plugins/zenshift"`.

## License

MIT
