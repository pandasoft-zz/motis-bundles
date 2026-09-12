#!/usr/bin/env bash
# Builds one variant end to end: download the inputs, build the bundle image
# (the Dockerfile runs `motis import` inside the build), and prove the bundle
# serves before anyone is allowed to push it.
#
#   build.sh <variant> [image[:tag]]
#
#   build.sh czech                                   -> motis-bundles/czech:dev
#   build.sh czech ghcr.io/pandasoft-zz/motis-bundles/czech:2.11.2-20260915-0100
#
# The same script runs in CI and on a laptop; CI adds only disk cleanup
# before and a push after. Needs docker, curl and jq. Everything lands under
# work/<variant>/ — the inputs, and summary.md with sizes and timings, which
# CI lifts into the job summary.
set -euo pipefail

VARIANT=${1:?usage: build.sh <variant> [image[:tag]]}
IMAGE=${2:-motis-bundles/$VARIANT:dev}

cd "$(dirname "$0")"

# Git Bash on Windows rewrites arguments that look like POSIX paths before
# docker sees them. Off, always; it is a no-op anywhere else.
export MSYS_NO_PATHCONV=1

[ -d "variants/$VARIANT" ] || { echo "no such variant: variants/$VARIANT" >&2; exit 2; }

# The one place the version is stated — see the Dockerfile.
MOTIS_VERSION=$(sed -n 's/^ARG MOTIS_VERSION=//p' Dockerfile)
[ -n "$MOTIS_VERSION" ] || { echo "MOTIS_VERSION not found in Dockerfile" >&2; exit 2; }

WORK="work/$VARIANT"
SUMMARY="$WORK/summary.md"
mkdir -p "$WORK/input"
: > "$SUMMARY"

note()  { printf '%s\n' "$*" | tee -a "$SUMMARY"; }
step()  { printf '\n\033[1m== %s\033[0m\n' "$*"; STEP_START=$SECONDS; }
took()  { note "- $1: $(( (SECONDS - STEP_START) / 60 ))m $(( (SECONDS - STEP_START) % 60 ))s"; }

note "## $VARIANT — MOTIS $MOTIS_VERSION"
note ""

# ── 1. Inputs ────────────────────────────────────────────────────────────────
step "download inputs for $VARIANT"
while read -r name url; do
  case "$name" in ''|'#'*) continue ;; esac
  echo "-> $name"
  # Into a .part and moved on success, so an interrupted download cannot
  # leave a truncated file that the import then accepts.
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 15 \
       -o "$WORK/input/$name.part" "$url"
  mv "$WORK/input/$name.part" "$WORK/input/$name"
done < "variants/$VARIANT/sources.txt"

# A feed host in maintenance answers 200 with an HTML page, and curl saves it
# as the zip it asked for. Test every archive before spending the import on it.
if command -v unzip >/dev/null; then
  for z in "$WORK"/input/*.zip; do
    unzip -tq "$z" >/dev/null || { echo "$z is not a valid zip archive" >&2; exit 1; }
  done
else
  echo "unzip not installed; skipping archive validation" >&2
fi
du -sh "$WORK"/input/* | sed 's/^/- /' | tee -a "$SUMMARY"
took "download"

# ── 2. Import and image ──────────────────────────────────────────────────────
# The build context is the variant's work directory — config.yml beside the
# downloads — and the Dockerfile does the rest: the import in a first stage,
# in the same image that will serve, and the bundle from its output alone.
# The inputs never reach the final image.
step "docker build $IMAGE  (this is the import; tens of minutes)"
cp "variants/$VARIANT/config.yml" "$WORK/config.yml"
printf 'summary.md\n*.part\n' > "$WORK/.dockerignore"
docker build \
  --progress=plain \
  --file Dockerfile \
  --tag "$IMAGE" \
  --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --label "org.opencontainers.image.revision=$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
  --label "org.opencontainers.image.version=${IMAGE##*:}" \
  --label "org.opencontainers.image.description=MOTIS $MOTIS_VERSION with the $VARIANT dataset, ready to run" \
  --label "io.github.motis-project.version=$MOTIS_VERSION" \
  --label "dev.motis-bundles.variant=$VARIANT" \
  "$WORK"
note ""
note "- image: $(docker image inspect --format '{{.Size}}' "$IMAGE" | awk '{printf "%.2f GB", $1/1e9}')"
took "import + build"

# ── 3. Smoke test ────────────────────────────────────────────────────────────
# The image is started exactly as a user would start it, and asked for what
# a user would ask: is it healthy, does it find a place, does it plan a
# journey with actual transit in it. A bundle that fails any of these is not
# pushed; the previous one stays current.
step "smoke test"
PORT=${SMOKE_PORT:-18080}
CID=$(docker run -d --rm -p "127.0.0.1:$PORT:8080" "$IMAGE")
cleanup() { docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# MOTIS loads the whole graph into memory before it opens its port, so this
# is minutes, not seconds. Fifteen of them, then the log says why not.
for i in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then break; fi
  if ! docker ps -q --no-trunc | grep -q "$CID"; then
    echo "server exited during startup:" >&2; docker logs "$CID" 2>&1 | tail -50 >&2; exit 1
  fi
  [ "$i" -eq 180 ] && { echo "server not healthy after 15 minutes:" >&2; docker logs "$CID" 2>&1 | tail -50 >&2; exit 1; }
  sleep 5
done
took "startup to healthy"

# A place lookup: geocoding is enabled in the config, so it must answer.
curl -fsS "http://127.0.0.1:$PORT/api/v1/geocode?text=$(printf %s "${SMOKE_GEOCODE:-Brno}" | jq -sRr @uri)" \
  | jq -e 'length > 0' >/dev/null \
  || { echo "geocode returned nothing" >&2; exit 1; }

# A journey. Tomorrow at 08:00 UTC rather than now: the build runs at night,
# and "no itinerary at 01:00" would say nothing about the graph. The two
# points default to Brno hl.n. -> Praha hl.n.; a variant can override them.
WHEN=$(date -u -d 'tomorrow 08:00' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -v+1d +%Y-%m-%dT08:00:00Z)
FROM=${SMOKE_FROM:-49.1907,16.6128}
TO=${SMOKE_TO:-50.0830,14.4355}
PLAN=$(curl -fsS "http://127.0.0.1:$PORT/api/v1/plan?fromPlace=$FROM&toPlace=$TO&time=$WHEN")
echo "$PLAN" | jq -e '.itineraries | length > 0' >/dev/null \
  || { echo "plan returned no itineraries: $(echo "$PLAN" | head -c 500)" >&2; exit 1; }
# At least one leg that is not walking, or the street graph alone answered
# and the timetable is missing.
echo "$PLAN" | jq -e '[.itineraries[].legs[].mode] | any(. != "WALK")' >/dev/null \
  || { echo "plan found only walking legs; no transit in the graph?" >&2; exit 1; }
note "- smoke: healthy, geocode ok, $(echo "$PLAN" | jq '.itineraries | length') itineraries $FROM -> $TO at $WHEN"

cleanup; trap - EXIT
step "done: $IMAGE"
cat "$SUMMARY"
