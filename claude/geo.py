"""Offline IP geolocation and IP hashing.

Uses a MaxMind-format city database (DB-IP Lite City, CC-BY 4.0, or GeoLite2
City). See scripts/update_geodb.sh for downloading it. If no database is
present, lookups return 'unknown' and everything else keeps working.
"""

import hashlib
import hmac
import ipaddress
import logging
from functools import lru_cache

from .countries import ISO2_TO_ISO3

log = logging.getLogger(__name__)

UNKNOWN = {'country': None, 'country_name': 'unknown', 'region': None,
           'city': None, 'lat': None, 'lon': None}
LOCAL = {**UNKNOWN, 'country_name': 'local network'}


def hash_ip(ip, salt):
    """A stable, non-reversible id for an IP address (for unique-user counts)."""
    if not ip:
        return None
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


class Geo:
    def __init__(self, path):
        self.reader = None
        try:
            import maxminddb
            self.reader = maxminddb.open_database(str(path))
        except FileNotFoundError:
            log.warning('GeoIP database %s not found; locations will be '
                        'unknown', path)
        self.lookup = lru_cache(maxsize=50_000)(self._lookup)

    def _lookup(self, ip):
        if not ip:
            return UNKNOWN
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return UNKNOWN
        if addr.is_private or addr.is_loopback:
            return LOCAL
        if self.reader is None:
            return UNKNOWN
        rec = self.reader.get(ip)
        if not rec:
            return UNKNOWN

        def name(key):
            return (rec.get(key) or {}).get('names', {}).get('en')

        iso2 = (rec.get('country') or {}).get('iso_code')
        loc = rec.get('location') or {}
        subdivisions = rec.get('subdivisions') or [{}]
        return {'country': ISO2_TO_ISO3.get(iso2),
                'country_name': name('country') or 'unknown',
                'region': subdivisions[0].get('names', {}).get('en'),
                'city': name('city'),
                'lat': loc.get('latitude'),
                'lon': loc.get('longitude')}
