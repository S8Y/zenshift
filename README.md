# ZenShift

**Automatic OpenCode Zen API key rotation for Hermes Agent.**

ZenShift is a Hermes dashboard plugin that manages a pool of OpenCode Zen API keys
and rotates them automatically through configurable strategies. It detects API
errors at runtime and swaps keys instantly — no manual intervention needed.

## Features

- **Timed rotation** — swap keys every N seconds (default: 600s, min: 30s)
- **Per-API-call rotation** — rotate after N API calls
- **Per-session rotation** — rotate on each Hermes agent start
- **Auto rate-limit recovery** — detects 429 errors and insta-swaps keys
- **Dead-key blacklisting** — 401/403 errors blacklist the offending key for 24h,
  skips it during rotation; falls back to key[0] if all keys are blacklisted
- **WebUI dashboard** — manage keys and config from Hermes Dashboard
  (`hermes dashboard` → ZenShift tab)
- **Zero-config** — install, paste keys, set interval, forget

## Installation

```bash
# Copy plugin to Hermes plugins directory
cp -r zenshift ~/.hermes/plugins/

# Enable the plugin
hermes config set plugins.enabled '["zenshift"]'

# Restart Hermes
```

## Usage

1. Run `hermes dashboard` and open the browser
2. Click the **ZenShift** tab
3. Paste your OpenCode Zen API keys (one per line) in the text box
4. Choose a rotation strategy and interval
5. Click **Save** — ZenShift handles the rest

## Files

```
zenshift/
├── plugin.yaml                    # Plugin manifest
├── __init__.py                    # Plugin entry point (register())
├── zenshift_integration.py        # Hermes agent runtime monkey-patches
├── dashboard/
│   ├── manifest.json              # Dashboard manifest
│   ├── plugin_api.py              # Backend API (FastAPI APIRouter)
│   └── dist/
│       ├── index.js               # Frontend React component
│       └── style.css              # Dashboard styling
├── .gitignore
└── README.md
```

## Strategies

| Strategy | Description |
|----------|-------------|
| `timed` | Rotate every N seconds. Best for "set and forget" |
| `api_call` | Rotate after every N successful API calls |
| `session` | Rotate once when Hermes starts (calls `register()`) |

## Error handling

| API Response | ZenShift Action |
|-------------|----------------|
| 429 / rate-limit | Rotate to next valid key immediately |
| 401 / 403 / invalid key | Blacklist key for 24h, rotate to next valid |
| All keys blacklisted | Fall back to key[0] |
| Unrecognized error | Pass through, no rotation |

## Requirements

- Hermes Agent 0.16.0+
- OpenCode Zen API keys

## License

MIT
