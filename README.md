# Instagram Following Cleaner

A Python CLI tool to safely audit and clean your Instagram following list while respecting custom exemptions and rate limits.

## Security & Authentication
The script **never asks for or stores your password**. It authenticates exclusively via an existing session cookie (`sessionid`) from your regular web browser:
1. Open Instagram in your web browser.
2. Open Developer Tools (`F12` -> `Storage` / `Application` -> `Cookies` -> `https://www.instagram.com`).
3. Copy the value of the cookie named `sessionid`.

You can provide it in three ways:
- **Interactively:** The script will prompt for it with masked input (characters will not appear on screen).
- **Secure local file:** Save it inside `.sessionid` in the project root (ignored by Git).
- **Environment variable:** `export IG_SESSIONID="<sessionid>"`

Once validated, the session settings are cached locally in `ig_session.json` (also ignored by Git) so you won't need to re-enter it on subsequent runs as long as the session remains valid.

## Filtering Rules
1. Identifies accounts that **do not follow you back**.
2. **Exemptions preserved (will NOT be unfollowed):**
   - Accounts exceeding the configured follower threshold (defaults to 2,000 followers, saved to `exempt_over_<threshold>.txt`).
   - Private accounts (saved to `exempt_private.txt`).
3. The remaining accounts are flagged as candidates for unfollowing (`candidates_to_unfollow.txt`).

## Usage with `uv`

### 1. Audit / Simulation (Dry-Run by default)
Scans and populates report files without taking any destructive actions:
```bash
cd /home/carlosg/Projects/instagram-cleaner
uv run main.py
```
*When prompted, press `Enter` to keep the default threshold of 2,000 followers, or enter any custom number.*

You can also pass the parameter directly:
```bash
uv run main.py --min-followers 5000
```

### 2. Execute Real Unfollows
Add the `--execute` flag and optionally specify a `--limit` per session (50–70 per day is recommended to prevent Instagram action blocks):
```bash
uv run main.py --execute --limit 50
```

## CLI Options
- `--min-followers <N>`: Follower threshold to exempt accounts from unfollowing.
- `--execute`: Execute actual unfollows (runs in simulation mode by default).
- `--limit <N>`: Maximum unfollows per run (default: 50).
- `--reset-session`: Delete cached session to switch accounts.
- `--clear-cache`: Remove previous `.txt` reports to restart analysis from scratch.

## Generated Output Files
- `exempt_over_<threshold>.txt`: Accounts you follow with follower count above the threshold.
- `exempt_private.txt`: Private accounts you follow that don't follow back.
- `candidates_to_unfollow.txt`: Accounts eligible to be unfollowed.
- `unfollowed.txt`: Cumulative log of accounts unfollowed across runs.
