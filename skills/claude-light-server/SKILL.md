---
name: claude-light-server
description: Operates and maintains the Claude-Light server on its Raspberry Pi (claude-light.cheme.cmu.edu) - deploying updates, restarting the service, checking logs and health, the SQLite data and backups, the GeoIP database, nginx rate limits, and troubleshooting GPIO, camera or queue problems. Use when the user asks to deploy, update, restart, debug or check the Claude-Light server, or works on the jkitchin/claude-light code under claude/, deploy/ or scripts/.
license: MIT
metadata:
  version: "2.0"
---

# Claude-Light server operations

The instrument is a Raspberry Pi 4 (Debian 12, Python 3.11) at
`claude-light.cheme.cmu.edu`, reached with `ssh claude-light.cheme.cmu.edu`
as user `jkitchin`. It is a **public, shared service**: stopping it breaks
experiments for students and anyone else using it. Confirm with the user
before any restart or stop, say how long the outage will be, and verify the
public API afterwards.

## Layout

| What | Where |
|---|---|
| Code (git checkout of jkitchin/claude-light) | `~/claude-light` |
| Python venv (`--system-site-packages`, for picamera2 from apt) | `~/.venv` |
| Secrets (`CLAUDE_LIGHT_SECRET`, `CLAUDE_LIGHT_IP_SALT`) | `~/claude-light/.env`, mode 600, not in git |
| Database (SQLite, WAL) | `~/claude-light-data/claude.db` |
| GeoIP database (DB-IP Lite City) | `~/claude-light-data/dbip-city-lite.mmdb` |
| Old log, before 2026-10-29 (raw IPs) | `~/results.jsonl` |
| App service (uvicorn on 127.0.0.1:8000) | `claude.service`, from `claude.service` in the repo |
| Monthly GeoIP refresh | `claude-geodb.timer`, from `deploy/` |
| nginx site (TLS, rate limits, cache) | `/etc/nginx/sites-available/claude-light.cheme.cmu.edu.conf`, from `deploy/nginx-claude-light.conf` |

How the app works:
- `claude/instrument.py`: one worker thread owns the LED, sensor and camera.
  Requests wait in a bounded asyncio queue: 503 when it's full, 429 per IP.
- `claude/store.py`: a writer thread batches rows into SQLite and updates the
  rollup tables (`daily`, `daily_users`, `places`).
- `claude/stats.py`: reads only the rollups, cached for 60 s.
- `claude/config.py`: settings, all from the environment or `.env`.

## Health checks (safe, read-only)

```bash
curl -s https://claude-light.cheme.cmu.edu/health             # app up
curl -s https://claude-light.cheme.cmu.edu/health/instrument  # last measurement ok
curl -s https://claude-light.cheme.cmu.edu/status             # queue depth
ssh claude-light.cheme.cmu.edu 'systemctl status claude.service --no-pager; journalctl -u claude -n 50 --no-pager'
```

A real measurement (`/api?G=0.5`) should return 515nm ≈ 32000 in ~0.65 s.

## Deploying a change

Develop and test locally first, with the simulated instrument:

```bash
pip install -e '.[test]' && pytest
CLAUDE_LIGHT_FAKE=1 uvicorn --factory claude.app:create_app --reload
```

Then push to `main` and, with the user's go-ahead, on the Pi:

```bash
cd ~/claude-light
git pull --ff-only https://github.com/jkitchin/claude-light.git main
~/.venv/bin/pip install -q -e '.[pi]'      # only if dependencies changed
sudo systemctl restart claude.service      # ~5 s outage
curl -sf http://127.0.0.1:8000/health
```

- The Pi has no SSH key for GitHub, so pull over https as shown.
- Restarting turns the LED off, releases the GPIO pins and camera, and waits
  up to 15 s for the queue.
- If `deploy/nginx-claude-light.conf` changed, install it and reload nginx.
  Reloading has no downtime:

  ```bash
  sudo cp deploy/nginx-claude-light.conf /etc/nginx/sites-available/claude-light.cheme.cmu.edu.conf
  sudo nginx -t && sudo systemctl reload nginx
  ```

  The live file is the repo file. Keep them identical: certbot's lines are
  already in the repo copy.
- If `claude.service` changed: `sudo cp claude.service /etc/systemd/system/ && sudo systemctl daemon-reload`, then restart.

## Testing on the Pi without touching the live service

Copy the code to another folder, give it its own venv and `.env` (with
`CLAUDE_LIGHT_DATA` pointing at a test folder), and run it with
`CLAUDE_LIGHT_FAKE=1` on another loopback port, reached through an SSH tunnel
(`ssh -L 8001:127.0.0.1:8001 ...`). The real hardware can only be used by one
process at a time: the live app holds the camera and GPIO, so a hardware test
means stopping `claude.service` first. That is an outage; ask first.

## Gotchas (all have happened)

- **`.env` may lack a trailing newline.** `echo X=... >> .env` then glues the
  new variable onto the previous line. Use `sed -i -e '$a\' .env` first, and
  check with `awk -F= '{print NR, $1}' .env`. Never print the values.
- **`pkill -f pattern` over ssh can kill its own shell**, because the pattern
  is in the remote command line. Anchor it, for example
  `pkill -f '^/home/jkitchin/.venv/bin/python'`, or use `systemctl`.
- **Never change `CLAUDE_LIGHT_IP_SALT`.** Unique-user counts depend on it.
  Keep a copy of `.env` in a password manager.
- **`scripts/update_geodb.sh` restarts the app only with `--restart`.** The
  timer passes it; manual runs don't.
- **`load_dotenv` finds the `.env` next to the code**, not in the working
  directory. Scripts run from another checkout use that checkout's `.env`.
  Pass `--db` explicitly to `scripts/migrate_jsonl.py`.
- **GPIO busy / camera in use** errors at startup mean another process holds
  the hardware. Look for one with `pgrep -af 'claude|uvicorn|python'`.
- `/home/jkitchin` is mode 700, so nginx can't serve files from it directly.
  Static files are proxied and cached instead.

## Data and backups

- The database is the only copy of the measurement history. Back it up with a
  consistent snapshot while the server runs (the Pi has no `sqlite3` CLI):

  ```bash
  ~/.venv/bin/python -c "import sqlite3, sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))" \
      ~/claude-light-data/claude.db /path/claude-$(date +%F).db
  ```
- To load an old-format JSONL log, use `scripts/migrate_jsonl.py FILE --db PATH`.
  It can be re-run; it only adds rows newer than what is already in the database.
- Raw IP addresses are never stored in the database. `~/results.jsonl`
  (pre-2026-10-29) still has them; don't copy or publish it.
