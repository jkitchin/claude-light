"""Load ~/results.jsonl into the SQLite database.

IP addresses are geolocated and hashed on the way in; they are not stored.
Safe to re-run: only lines newer than the latest measurement already in the
database are added, so it can also catch up after a cutover.

    python scripts/migrate_jsonl.py ~/results.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude import config  # noqa: E402
from claude.geo import Geo  # noqa: E402
from claude.store import connect, to_row, write_rows  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('jsonl', type=Path)
    p.add_argument('--db', type=Path, default=config.DB_PATH)
    p.add_argument('--geodb', type=Path, default=config.GEO_DB)
    p.add_argument('--chunk', type=int, default=10_000)
    args = p.parse_args()

    if not config.IP_SALT:
        sys.exit('Set CLAUDE_LIGHT_IP_SALT (or CLAUDE_LIGHT_SECRET) first, '
                 'and use the same value as the server.')

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = connect(args.db)
    latest = con.execute('SELECT max(t0) FROM measurements').fetchone()[0] or 0
    geo = Geo(args.geodb)

    n_read = n_added = n_bad = 0
    chunk = []
    start = time.time()

    def flush():
        nonlocal chunk, n_added
        with con:
            write_rows(con, chunk)
        n_added += len(chunk)
        chunk = []
        print(f'\r{n_read:,} read, {n_added:,} added, {n_bad} bad '
              f'({time.time() - start:.0f} s)', end='', flush=True)

    with open(args.jsonl) as f:
        for line in f:
            n_read += 1
            try:
                record = json.loads(line)
                if record['t0'] <= latest:
                    continue
                chunk.append(to_row(record, geo, config.IP_SALT))
            except (ValueError, KeyError, TypeError):
                n_bad += 1
                continue
            if len(chunk) >= args.chunk:
                flush()
    if chunk:
        flush()
    print()

    total = con.execute('SELECT count(*) FROM measurements').fetchone()[0]
    print(f'Done: {n_added:,} added, {n_bad} unreadable lines, '
          f'{total:,} measurements in {args.db}')


if __name__ == '__main__':
    main()
