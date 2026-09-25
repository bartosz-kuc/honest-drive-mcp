# honest-drive-mcp

Local Google Drive MCP server with **full permission management** — the piece missing from the official connector.

Companion project to [honest-gmail-mcp](https://github.com/bartosz-kuc/honest-gmail-mcp) and [honest-calendar-mcp](https://github.com/bartosz-kuc/honest-calendar-mcp).

## Why

The official Anthropic Drive connector is competent for read + create, but has one big gap: **it cannot set or modify sharing permissions.** If you build a workflow like "create a folder for my accountant and share it with her", you hit a dead end — you have to jump into the Drive UI to do the sharing part manually.

This MCP fixes that. Same trust model as the rest of the honest-* family: data flows only between your machine and Google.

## Features

Eight tools exposed over MCP:

- `list_files` — search with Drive query syntax
- `get_file` — full metadata
- `read_file` — download content (text/JSON returned as UTF-8; binaries as base64; Google-native docs auto-exported to plain text / CSV)
- `create_file` — upload from text or base64
- `create_folder` — new folder, optionally inside a parent
- **`share_file`** — grant access to an email (reader/commenter/writer/owner), notification optional, custom message supported ← the piece missing elsewhere
- **`list_permissions`** — see who has access and with what role
- **`remove_permission`** — revoke a specific permission by id

## Requirements

- Python 3.10+
- A Google account
- One-time Google Cloud OAuth setup (~10 min; can reuse the client from honest-gmail-mcp — just enable the Drive API on the same project)

## Setup

```bash
git clone https://github.com/bartosz-kuc/honest-drive-mcp.git
cd honest-drive-mcp
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

On Windows use `venv\Scripts\pip` and `venv\Scripts\python` instead of the `venv/bin/...` paths shown throughout this README.

Google Cloud steps (same as honest-gmail-mcp):
1. https://console.cloud.google.com/ → create or select project
2. **APIs & Services → Library** → enable **Google Drive API**
3. **APIs & Services → Credentials → OAuth client ID → Desktop app** → download JSON → save as `credentials.json` here

First run:

```bash
./venv/bin/python server.py
```

Browser opens → Allow → token saved to `token.json`. Ctrl+C.

Register with Claude Code:

```bash
claude mcp add drive-personal /absolute/path/to/venv/bin/python /absolute/path/to/server.py
```

Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "drive-personal": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

### Configuration (optional)

By default `credentials.json` and `token.json` are read from (and the token written to) the directory containing `server.py`. Two env vars override this, e.g. for one instance per Google account, or when installed from PyPI (pip/uvx), where that directory is the package's install location:

| Env var | Default | Purpose |
|---|---|---|
| `DRIVE_CREDENTIALS_PATH` | `credentials.json` next to `server.py` | OAuth client file |
| `DRIVE_TOKEN_PATH` | `token.json` next to `server.py` | OAuth token file (written after browser consent on the first tool call; its directory must exist) |

Use absolute paths, e.g. in `claude_desktop_config.json`:

```json
"env": {
  "DRIVE_CREDENTIALS_PATH": "/absolute/path/to/credentials.json",
  "DRIVE_TOKEN_PATH": "/absolute/path/to/token.json"
}
```

## Example usage

> "Create a folder called 'Faktury dla księgowej' in My Drive and share it with elwira@example.pl as writer."

AI calls `create_folder` → gets folder_id → calls `share_file(file_id, "elwira@example.pl", role="writer")`. Done in one shot. No context-switch to the Drive UI.

> "Who has access to file X?"

AI calls `list_permissions(file_id)` → returns all permissions with ids you can pass to `remove_permission` later.

## Data flow

```
Your AI client
     ↕  MCP stdio
This server (Python, on your machine)
     ↕  HTTPS
Google Drive API
```

No cloud middle. Tokens stay on disk, `.gitignore`d.

## Security notes

- **OAuth scope requested:** `drive` (full read/write on all Drive files this account can access). Google does not offer a scope that includes permission management without also including read/write to files, which is why the scope is broad.
- **`send_notification` defaults to `false`** — AI will not spam recipients unless explicitly asked.
- **`role: "owner"` transfers ownership** — an irreversible action. The tool passes `transferOwnership: true` automatically when this role is requested; consider using `writer` unless you really mean to hand over the file.
- Revoke access anytime at https://myaccount.google.com/permissions.
- `credentials.json` and `token.json` are `.gitignore`d.

## Author

**Bartosz Kuć** — Warsaw-based developer, JDG owner running skanfirmy.pl.

- Site: https://skanfirmy.pl
- GitHub: https://github.com/bartosz-kuc

- Email: firma@bartosza.pl

## Consulting

Available for consulting on Polish tax and business integrations (KSeF, GUS/NFZ/GIOŚ APIs, mBank data), MCP server design, and AI-assisted tooling for JDGs and small teams. See **[skanfirmy.pl/uslugi](https://skanfirmy.pl/uslugi)** for productized packages (audit 3k PLN, setup 8-15k PLN, retainer 2-4k PLN/mo), or reach out via email.

## License

MIT — see [LICENSE](LICENSE).

## Related

- [honest-gmail-mcp](https://github.com/bartosz-kuc/honest-gmail-mcp) — local Gmail MCP
- [honest-calendar-mcp](https://github.com/bartosz-kuc/honest-calendar-mcp) — local Google Calendar MCP
- [honest-nip-krs-mcp](https://github.com/bartosz-kuc/honest-nip-krs-mcp) — Polish company registry MCP (biała lista + KRS)
