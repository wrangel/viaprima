#!/bin/bash
set -e

# To be run on the Synology (Task Scheduler, user-defined script):
#
#   bash /volume1/homes/Matthias/Drive/Programming/viaprima/scripts/syno-deploy.sh
#
# Building and publishing happen on GitHub: every merge to main builds, tests
# and pushes the image (.github/workflows/image.yml; "make prod" on the Mac is
# the fallback). This script only pulls and restarts - it never builds. The
# Synology lacks everything needed for that anyway. Scheduled weekly, Tuesdays
# 04:15, after Renovate's Monday merges.
#
# The file reaches the NAS through Synology Drive, not through git. It can
# therefore be older than the version on the Mac; the line below says which one
# actually ran.
SCRIPT_VERSION="2026-10-08-pinned2"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_DIR="${PROJECT_DIR:-/volume1/homes/Matthias/Drive/Programming/viaprima}"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
IMAGE="wrangel/viaprima"
# The container name comes from the project name pinned in
# docker-compose.yml, so it no longer depends on the folder name.
SERVICE="viaprima-app-1"

echo -e "${GREEN}syno-deploy.sh ${SCRIPT_VERSION}${NC}"
[[ -f "$COMPOSE_FILE" ]] || { echo -e "${RED}No compose file at $COMPOSE_FILE${NC}"; exit 1; }

# Compose v2 is a subcommand of docker, v1 was a program of its own. Try v2
# first, so this survives updates to the Container Manager.
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi
echo "   using: $COMPOSE"
COMPOSE_CMD=($COMPOSE -f "$COMPOSE_FILE")

# ==============================================================================
# Pull
#
# "compose pull" reads the compose file and fetches exactly the tag written
# there. No guessing against Docker Hub's tag list - with abstractaltitudes that
# had led to some arbitrary sha tag being pulled while the one actually in use
# was never refreshed.
# ==============================================================================
echo -e "${GREEN}Pulling the image named in the compose file...${NC}"
"${COMPOSE_CMD[@]}" pull

# down + up rather than restart: that rebuilds the network. On this NAS the
# bridge has repeatedly come back without its iptables FORWARD rules, leaving
# the containers with no route out. For this app that is especially awkward - it
# fetches its premium data from the BAG.
echo -e "${GREEN}Bringing the stack back up...${NC}"
"${COMPOSE_CMD[@]}" down
docker network prune -f >/dev/null 2>&1 || true
# --no-build: nothing is built on the NAS. If the image is missing, the script
# should fail rather than start compiling pandas.
"${COMPOSE_CMD[@]}" up -d --no-build

# NOTE: abstractaltitudes once had "docker volume prune -f" here. That deletes
# every unused volume on the NAS, other people's data included. Here it would
# also be self-defeating: the premium-cache volume holds the BAG's 12 MB file.
# Without it, every start pays for the full download.

# ==============================================================================
# Check
#
# "container is running" does not mean "app responds": Streamlit listens before
# it has loaded the premium data. The health endpoint tells the two apart.
# ==============================================================================
echo -e "${GREEN}Waiting for the app to respond...${NC}"
ready=false
for _ in $(seq 1 45); do
  sleep 2
  if docker exec "$SERVICE" python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" \
      >/dev/null 2>&1; then
    ready=true
    break
  fi
done

if [[ "$ready" != "true" ]]; then
  echo -e "${RED}The app did not become ready within 90 seconds.${NC}"
  echo -e "${YELLOW}   Look at the log with: docker logs $SERVICE${NC}"
  exit 1
fi
echo -e "${GREEN}App responds.${NC}"

# This app is worthless without internet - it fetches the premium data from the
# BAG. After the network has been rebuilt, an explicit probe is worth it.
#
# The probe reports which layer failed rather than just "cannot reach", because
# the three causes need three different fixes and they are indistinguishable
# from the outside. Container Manager's terminal cannot be pasted into, so this
# has to run itself.
# The container cannot resolve names, so docker-compose.yml pins the BAG's
# address in /etc/hosts. The NAS itself resolves perfectly well, so it can
# check that the pin is still right - otherwise a change at the BAG would turn
# into a silent outage weeks later.
# Synology's shell has no getent, so try a few things and - importantly - say
# so when none of them worked. The first version treated "no answer" as "they
# match", which is the one outcome this check exists to rule out.
PINNED="$(grep -oE 'opendata\.bagnet\.ch:[0-9.]+' "$COMPOSE_FILE" | cut -d: -f2)"
ACTUAL=""
if command -v nslookup >/dev/null 2>&1; then
  ACTUAL="$(nslookup opendata.bagnet.ch 2>/dev/null \
            | awk '/^Address: /{print $2; exit}')"
fi
if [[ -z "$ACTUAL" ]] && command -v python3 >/dev/null 2>&1; then
  ACTUAL="$(python3 -c "import socket;print(socket.gethostbyname('opendata.bagnet.ch'))" 2>/dev/null)"
fi
if [[ -z "$ACTUAL" ]] && command -v getent >/dev/null 2>&1; then
  ACTUAL="$(getent hosts opendata.bagnet.ch | awk '{print $1}' | head -1)"
fi

if [[ -n "$PINNED" && -z "$ACTUAL" ]]; then
  echo -e "${YELLOW}   could not check the pinned BAG address $PINNED -" \
          "no working resolver on the NAS${NC}"
elif [[ -n "$PINNED" && "$PINNED" != "$ACTUAL" ]]; then
  echo -e "${RED}The pinned BAG address is out of date.${NC}"
  echo -e "${RED}   docker-compose.yml says $PINNED, DNS says $ACTUAL.${NC}"
  echo -e "${RED}   Update extra_hosts in docker-compose.yml, or the app will${NC}"
  echo -e "${RED}   keep talking to an address the BAG no longer uses.${NC}"
elif [[ -n "$PINNED" ]]; then
  echo "   pinned BAG address $PINNED matches DNS ($ACTUAL)"
fi

echo -e "${GREEN}Checking what the container can reach...${NC}"
docker exec -i "$SERVICE" python - <<'PROBE'
import socket, struct, random

def udp_dns(server):
    """A real DNS query over UDP - which is what resolution actually uses."""
    q = struct.pack('>HHHHHH', random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    for part in b'opendata.bagnet.ch'.split(b'.'):
        q += bytes([len(part)]) + part
    q += b'\x00' + struct.pack('>HH', 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.sendto(q, (server, 53))
        s.recvfrom(512)
        return True
    except Exception:
        return False

def tcp(host, port):
    try:
        socket.create_connection((host, port), 5).close()
        return True
    except Exception:
        return False

def fetch(url):
    """What the app actually does, including the user agent admin.ch demands."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method='HEAD', headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 '
                          'Safari/537.36'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return f'HTTP {r.status}'
    except Exception as e:
        return f'{type(e).__name__}'

routing = tcp('1.1.1.1', 443)
bag_tcp = tcp('opendata.bagnet.ch', 443)
bag_http = fetch('https://opendata.bagnet.ch/')
pinned = udp_dns('8.8.8.8')
embedded = udp_dns('127.0.0.11')
try:
    socket.gethostbyname('opendata.bagnet.ch')
    resolves = True
except Exception:
    resolves = False

print(f"     route out (1.1.1.1:443) : {'yes' if routing else 'NO'}")
print(f"     DNS to 8.8.8.8 over UDP : {'yes' if pinned else 'NO'}")
print(f"     Docker resolver .0.11   : {'yes' if embedded else 'NO'}")
print(f"     name resolution works   : {'yes' if resolves else 'NO'}")
print(f"     TCP to the BAG :443     : {'yes' if bag_tcp else 'NO'}")
print(f"     HTTPS GET from the BAG  : {bag_http}")
if resolves and bag_http.startswith("HTTP 2"):
    print("     -> fine")
elif resolves and not bag_tcp:
    print("     -> DNS is fine but the BAG refuses the connection.")
    print("        Outbound 443 to 80.74.156.75 is blocked, or the BAG is down.")
elif resolves:
    print(f"     -> DNS and TCP fine, the request itself failed: {bag_http}")
elif not routing:
    print("     -> no route out at all: the iptables FORWARD problem.")
    print("        Recreate the network, or check the Synology firewall.")
elif pinned:
    print("     -> upstream DNS is reachable but resolution still fails.")
    print("        The container predates the dns: block in docker-compose.yml.")
    print("        Run this task again; it recreates the container.")
else:
    print("     -> UDP port 53 is blocked for this bridge, so pinning public")
    print("        resolvers cannot work. Synology firewall, scoped to the")
    print("        bridge subnet. Allow UDP 53 outbound for it.")
PROBE

# ==============================================================================
# Clean up - last, so that a failure above leaves every fallback standing.
#
# This project's images only. "docker system prune -af" would remove every
# unused image on the NAS, including other containers'. "docker rmi" without -f
# refuses to delete an image in use - the running version is therefore safe by
# itself.
# ==============================================================================
echo -e "${GREEN}Clearing out old images...${NC}"
echo "   before:"
docker images --format '     {{.Repository}}:{{.Tag}}  {{.Size}}  ({{.CreatedSince}})' \
  | grep viaprima || echo "     (none)"

# The superseded version loses its tag when the new one is pulled and becomes
# dangling. That is where most of the space sits.
reclaimed=$(docker image prune -f 2>/dev/null | tail -1)
echo "     ${reclaimed:-nothing to reclaim}"

echo "   after:"
docker images --format '     {{.Repository}}:{{.Tag}}  {{.Size}}  ({{.CreatedSince}})' \
  | grep viaprima || echo "     (none)"

echo -e "${GREEN}Done. The app is running on port ${PORT:-8501} of the NAS.${NC}"
