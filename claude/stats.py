"""Aggregates for the statistics page, computed from the rollup tables."""

import threading
import time

from .store import connect

EXCLUDE = ('unknown', 'local network')


def _columns(rows, keys):
    """Rows -> {key: [values]}; more compact JSON than a list of dicts."""
    return {k: [r[k] for r in rows] for k in keys}


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[i]


def _histogram(vals, lo, hi, nbins):
    width = (hi - lo) / nbins
    counts = [0] * nbins
    for v in vals:
        counts[min(nbins - 1, max(0, int((v - lo) / width)))] += 1
    return {'edges': [lo + i * width for i in range(nbins + 1)],
            'counts': counts}


def compute(db_path, recent_days=7):
    con = connect(db_path, readonly=True)
    try:
        q = con.execute
        daily = q('SELECT date, country_name, country, origin, n, '
                  'elapsed_sum, elapsed_max FROM daily ORDER BY date').fetchall()
        n = sum(r['n'] for r in daily)
        users = q('SELECT count(DISTINCT ip_hash) FROM daily_users').fetchone()[0]
        users_by_day = q('SELECT date, count(*) AS users FROM daily_users '
                         'GROUP BY date ORDER BY date').fetchall()
        users_by_country = q('SELECT country_name, '
                             'count(DISTINCT ip_hash) AS users '
                             'FROM daily_users GROUP BY country_name').fetchall()
        places = q('SELECT date, origin, lat, lon, country_name, city, n '
                   'FROM places ORDER BY date').fetchall()

        since = time.time() - recent_days * 86400
        recent = q('SELECT elapsed, queue_wait FROM measurements '
                   'WHERE t0 > ? ORDER BY t0 DESC LIMIT 100000',
                   (since,)).fetchall()
        last = q('SELECT max(t0) FROM measurements').fetchone()[0]
    finally:
        con.close()

    elapsed = sorted(r['elapsed'] for r in recent if r['elapsed'] is not None)
    waits = sorted(r['queue_wait'] for r in recent
                   if r['queue_wait'] is not None)
    countries = {r['country_name'] for r in daily} - set(EXCLUDE)

    return {
        'generated': time.time(),
        'totals': {'experiments': n, 'users': users,
                   'countries': len(countries),
                   'first_date': daily[0]['date'] if daily else None,
                   'last_t0': last},
        'daily': _columns(daily, ['date', 'country_name', 'country', 'origin',
                                  'n', 'elapsed_sum', 'elapsed_max']),
        'users_by_day': _columns(users_by_day, ['date', 'users']),
        'users_by_country': {r['country_name']: r['users']
                             for r in users_by_country},
        'places': _columns(places, ['date', 'origin', 'lat', 'lon',
                                    'country_name', 'city', 'n']),
        'recent': {
            'days': recent_days,
            'n': len(recent),
            'elapsed_p50': _percentile(elapsed, 0.5),
            'elapsed_p95': _percentile(elapsed, 0.95),
            'wait_p50': _percentile(waits, 0.5),
            'wait_p95': _percentile(waits, 0.95),
            'elapsed_hist': _histogram(elapsed, 0, 2, 40),
        },
    }


class StatsCache:
    """Recompute at most once per `ttl` seconds; concurrent callers share one
    computation instead of each scanning the database."""

    def __init__(self, db_path, ttl=60):
        self.db_path = db_path
        self.ttl = ttl
        self._value = None
        self._time = 0.0
        self._lock = threading.Lock()

    def get(self):
        if self._value is not None and time.time() - self._time < self.ttl:
            return self._value
        with self._lock:
            if self._value is None or time.time() - self._time >= self.ttl:
                self._value = compute(self.db_path)
                self._time = time.time()
        return self._value
