"""Runtime configuration, read from the environment (and ~/claude-light/.env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None):
    return os.environ.get(name, default)


# Set CLAUDE_LIGHT_FAKE=1 to run without the Pi hardware (development, tests).
FAKE = _env('CLAUDE_LIGHT_FAKE', '0') == '1'

# Used to sign the session cookie. There is deliberately no default in
# production; a random one is generated in fake mode so tests just work.
SECRET = _env('CLAUDE_LIGHT_SECRET') or (os.urandom(32).hex() if FAKE else None)

# Salt for hashing IP addresses. Changing it breaks the continuity of unique
# user counts, so set it once and leave it alone.
IP_SALT = _env('CLAUDE_LIGHT_IP_SALT', SECRET or '')

DATA_DIR = Path(_env('CLAUDE_LIGHT_DATA', '~/claude-light-data')).expanduser()
DB_PATH = Path(_env('CLAUDE_LIGHT_DB', DATA_DIR / 'claude.db'))
GEO_DB = Path(_env('CLAUDE_LIGHT_GEODB', DATA_DIR / 'dbip-city-lite.mmdb'))

# Backpressure. The instrument does ~1.5 measurements/s, so a queue of 30 is
# roughly a 20 s wait at worst.
QUEUE_MAX = int(_env('CLAUDE_LIGHT_QUEUE_MAX', 30))
PER_IP_MAX = int(_env('CLAUDE_LIGHT_PER_IP_MAX', 3))
TIMEOUT = float(_env('CLAUDE_LIGHT_TIMEOUT', 60))
GM_MAX_POINTS = int(_env('CLAUDE_LIGHT_GM_MAX', 50))

STATS_TTL = float(_env('CLAUDE_LIGHT_STATS_TTL', 60))
