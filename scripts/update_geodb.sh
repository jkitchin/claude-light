#!/bin/bash
# Download the current DB-IP Lite City database (CC BY 4.0, https://db-ip.com).
# DB-IP publishes a new one each month. Run monthly by claude-geodb.timer.
set -euo pipefail

DEST=${CLAUDE_LIGHT_GEODB:-$HOME/claude-light-data/dbip-city-lite.mmdb}
mkdir -p "$(dirname "$DEST")"

# Try this month's file, then last month's (early in the month it may not be
# published yet).
for month in "$(date +%Y-%m)" "$(date -d '-1 month' +%Y-%m 2>/dev/null || date -v-1m +%Y-%m)"; do
    url="https://download.db-ip.com/free/dbip-city-lite-${month}.mmdb.gz"
    if curl -fsSL "$url" -o "$DEST.gz.tmp"; then
        gunzip -c "$DEST.gz.tmp" > "$DEST.tmp"
        rm "$DEST.gz.tmp"
        mv "$DEST.tmp" "$DEST"
        echo "Installed $url -> $DEST"
        # The server reads the database at startup. Restart only when asked
        # (the monthly timer passes --restart).
        if [ "${1:-}" = "--restart" ]; then
            sudo systemctl restart claude.service
        fi
        exit 0
    fi
done
echo "Could not download a DB-IP database" >&2
exit 1
