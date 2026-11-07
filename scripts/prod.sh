#!/bin/bash
# Build the image for the Synology and push it to Docker Hub.
#
# The normal path is .github/workflows/image.yml: every merge to main builds,
# tests and pushes the image. This stays as the manual escape hatch, e.g. when
# GitHub Actions is down.
#
# What gets built is linux/amd64 - the Synology's architecture. On an Apple
# machine that image will not run; that is fine, it is not meant for here. For a
# local trial use scripts/test.sh.
set -e

cd "$(dirname "$0")/.."
IMAGE="$(grep -E '^\s*image:' docker-compose.yml | head -1 | awk '{print $2}')"

echo "Starting Docker if needed..."
open --background -a Docker 2>/dev/null || true
while ! docker info >/dev/null 2>&1; do
  echo "waiting for Docker..."
  sleep 2
done

echo "Checking the arithmetic before anything is published..."
VENV="${VENV:-$HOME/.venvs/viaprima}"
"$VENV/bin/python" test_calculation.py

echo "Building $IMAGE for linux/amd64..."
docker build --platform linux/amd64 -t "$IMAGE" .

echo "Signing in to Docker Hub (if needed)..."
docker login

echo "Pushing $IMAGE..."
docker push "$IMAGE"

echo
echo "Done. Pull it on the Synology with:"
echo "    docker pull $IMAGE"
