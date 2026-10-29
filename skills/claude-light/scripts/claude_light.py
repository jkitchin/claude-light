# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///
"""Measure with Claude-Light, waiting politely when the instrument is busy.

Use as a module:

    from claude_light import measure, measure_many
    out = measure(G=0.5)            # {'415nm': ..., '515nm': ..., ...}
    rows = measure_many([(0, g, 0) for g in (0, 0.5, 1)])

or from the command line (prints CSV):

    uv run claude_light.py 0 0.5 0              # one measurement
    uv run claude_light.py 0 0.5 0 --repeat 10  # the same point 10 times
    uv run claude_light.py --status             # is it busy?
"""

import argparse
import csv
import sys
import time

import requests

API = 'https://claude-light.cheme.cmu.edu'
CHANNELS = ['415nm', '445nm', '480nm', '515nm', '555nm',
            '590nm', '630nm', '680nm', 'clear', 'nir']

_session = requests.Session()


def measure(R=0.0, G=0.0, B=0.0, max_wait=300, verbose=False):
    """One measurement. Returns the dict of 10 channel readings.

    The instrument is shared and does ~1.5 measurements/s for everyone. When
    it answers 429 (you already have measurements queued) or 503 (queue full),
    wait the Retry-After seconds and try again, up to max_wait in total.
    """
    deadline = time.time() + max_wait
    while True:
        resp = _session.get(f'{API}/api', params={'R': R, 'G': G, 'B': B},
                            timeout=90)
        if resp.status_code in (429, 503):
            wait = int(resp.headers.get('Retry-After', 3))
            if time.time() + wait > deadline:
                raise TimeoutError('Claude-Light stayed busy; try again later.')
            if verbose:
                print(f'busy ({resp.status_code}), waiting {wait} s',
                      file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()['out']


def measure_many(points, verbose=False):
    """Measure each (R, G, B) in turn. Returns rows of
    {'R', 'G', 'B', 't', <channels>}. Sequential on purpose: parallel
    requests only wait in the instrument's queue and get 429s."""
    rows = []
    for i, (R, G, B) in enumerate(points):
        out = measure(R, G, B, verbose=verbose)
        rows.append({'R': R, 'G': G, 'B': B, 't': time.time(), **out})
        if verbose:
            print(f'{i + 1}/{len(points)}', file=sys.stderr)
    return rows


def status():
    """{'busy': bool, 'queue': int, 'last_t0': float, 'max_queue': int}"""
    return _session.get(f'{API}/status', timeout=10).json()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('rgb', nargs='*', type=float, help='R G B, each 0 to 1')
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--status', action='store_true')
    args = p.parse_args()

    if args.status:
        print(status())
        return
    if len(args.rgb) != 3:
        p.error('give three numbers: R G B')
    rows = measure_many([tuple(args.rgb)] * args.repeat, verbose=True)
    w = csv.DictWriter(sys.stdout, ['R', 'G', 'B', 't'] + CHANNELS)
    w.writeheader()
    w.writerows(rows)


if __name__ == '__main__':
    main()
