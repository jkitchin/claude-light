"""SQLite storage for measurements.

One writer thread owns the write connection and commits in small batches.
Readers (stats, export) open their own connections; WAL mode lets them run
while the writer is busy.

Besides the raw `measurements` table, the writer maintains small rollup tables
so the statistics page never has to scan every measurement:

- daily: experiments per (date, country, origin), with latency sums
- daily_users: one row per (date, user), for unique-user counts
- places: experiments per (date, origin, location), for the map dots;
  locations are rounded to 0.1 degree (about 10 km)
"""

import datetime
import logging
import queue
import sqlite3
import threading
import time

from .geo import hash_ip
from .instrument import CHANNELS

log = logging.getLogger(__name__)

# Column names for the channels; '415nm' is not a valid bare SQL identifier.
CH_COLS = ['ch' + c.replace('nm', '') if c[0].isdigit() else c
           for c in CHANNELS]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    t0 REAL NOT NULL,
    elapsed REAL,
    queue_wait REAL,
    origin TEXT,
    R REAL, G REAL, B REAL,
    {', '.join(f'{c} INTEGER' for c in CH_COLS)},
    ip_hash TEXT,
    country TEXT,
    country_name TEXT,
    region TEXT,
    city TEXT,
    lat REAL,
    lon REAL
);
CREATE INDEX IF NOT EXISTS measurements_t0 ON measurements(t0);
CREATE INDEX IF NOT EXISTS measurements_ip ON measurements(ip_hash);

CREATE TABLE IF NOT EXISTS daily (
    date TEXT NOT NULL,
    country_name TEXT NOT NULL,
    origin TEXT NOT NULL,
    country TEXT,
    n INTEGER NOT NULL,
    elapsed_sum REAL NOT NULL,
    elapsed_max REAL NOT NULL,
    PRIMARY KEY (date, country_name, origin)
);

CREATE TABLE IF NOT EXISTS daily_users (
    date TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    country_name TEXT NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (date, ip_hash)
);

CREATE TABLE IF NOT EXISTS places (
    date TEXT NOT NULL,
    origin TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    country_name TEXT,
    city TEXT,
    n INTEGER NOT NULL,
    PRIMARY KEY (date, origin, lat, lon)
);
"""

INSERT = f"""INSERT INTO measurements
(t0, elapsed, queue_wait, origin, R, G, B, {', '.join(CH_COLS)},
 ip_hash, country, country_name, region, city, lat, lon)
VALUES ({', '.join(['?'] * (7 + len(CH_COLS) + 7))})"""

UPSERT_DAILY = """INSERT INTO daily VALUES (?, ?, ?, ?, 1, ?, ?)
ON CONFLICT DO UPDATE SET n = n + 1,
    elapsed_sum = elapsed_sum + excluded.elapsed_sum,
    elapsed_max = max(elapsed_max, excluded.elapsed_max)"""

UPSERT_USER = """INSERT INTO daily_users VALUES (?, ?, ?, 1)
ON CONFLICT DO UPDATE SET n = n + 1"""

UPSERT_PLACE = """INSERT INTO places VALUES (?, ?, ?, ?, ?, ?, 1)
ON CONFLICT DO UPDATE SET n = n + 1"""


def connect(path, readonly=False):
    if readonly:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True,
                              check_same_thread=False)
    else:
        con = sqlite3.connect(path, check_same_thread=False)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
        con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def to_row(record, geo, salt):
    """Convert a measurement record (the old results.jsonl format) into a
    measurements row. The raw IP is used only for lookup and hashing."""
    loc = geo.lookup(record.get('ip'))
    R, G, B = record['in']
    out = record['out']
    return (record['t0'], record.get('elapsed_time'), record.get('queue_wait'),
            record.get('origin') or 'unknown', R, G, B,
            *[out.get(c) for c in CHANNELS],
            hash_ip(record.get('ip'), salt),
            loc['country'], loc['country_name'], loc['region'], loc['city'],
            loc['lat'], loc['lon'])


def write_rows(con, rows):
    """Insert rows and update the rollups. The caller commits."""
    con.executemany(INSERT, rows)
    for row in rows:
        (t0, elapsed, _, origin, *_rest) = row
        ip_hash, country, country_name, _region, city, lat, lon = row[-7:]
        date = datetime.datetime.fromtimestamp(t0).date().isoformat()
        elapsed = elapsed or 0.0
        con.execute(UPSERT_DAILY, (date, country_name, origin, country,
                                   elapsed, elapsed))
        if ip_hash:
            con.execute(UPSERT_USER, (date, ip_hash, country_name))
        if lat is not None and lon is not None:
            con.execute(UPSERT_PLACE, (date, origin, round(lat, 1),
                                       round(lon, 1), country_name, city))


class Store:
    """Background writer. Call add(record) from any thread."""

    def __init__(self, path, geo, salt, batch_seconds=1.0):
        self.path = path
        self.geo = geo
        self.salt = salt
        self.batch_seconds = batch_seconds
        self._q = queue.Queue()
        self._thread = None

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connect(self.path).close()  # create the schema before readers come
        self._thread = threading.Thread(target=self._run, name='store',
                                        daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread:
            self._q.put(None)
            self._thread.join(timeout=10)

    def add(self, record):
        self._q.put(record)

    def flush(self):
        """Block until everything queued so far is written (for tests)."""
        done = threading.Event()
        self._q.put(done)
        done.wait(timeout=10)

    def _run(self):
        con = connect(self.path)
        stop = False
        while not stop:
            item = self._q.get()
            deadline = time.monotonic() + self.batch_seconds
            batch, events = [], []
            while True:
                if item is None:
                    stop = True
                elif isinstance(item, threading.Event):
                    events.append(item)
                else:
                    batch.append(item)
                if stop or events or len(batch) >= 200:
                    break
                try:
                    item = self._q.get(
                        timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break
            if batch:
                try:
                    rows = [to_row(r, self.geo, self.salt) for r in batch]
                    with con:
                        write_rows(con, rows)
                except Exception:
                    log.exception('failed to write %d measurements', len(batch))
            for e in events:
                e.set()
        con.close()
