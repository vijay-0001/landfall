#!/usr/bin/env bash
# Stops the local demo stack started by scripts/restart_local.sh (ports 3000 web, 3300 renderer, 3400 Kiln, 8000 API).
# The database container (landfall-pg) is left running unless you pass --db.  Windows (Git Bash).
for port in 3000 3300 3400 8000; do
  for pid in $(netstat -ano | grep -E "[:.]$port .*LISTENING" | awk '{print $5}' | sort -u); do taskkill //PID "$pid" //F //T >/dev/null 2>&1; done
done
echo "app processes stopped (3000, 3300, 3400, 8000)"
if [ "$1" = "--db" ]; then docker stop landfall-pg >/dev/null 2>&1 && echo "database container landfall-pg stopped"; fi
