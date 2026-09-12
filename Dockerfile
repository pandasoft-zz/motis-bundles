# A bundle is upstream MOTIS, unchanged, plus the data directory that
# `motis import` produced from one variant's config. Both happen in this one
# file: the first stage runs the import, the second keeps only its output.
#
# The binary that built the graph is the binary that serves it, by
# construction: both stages start FROM the same image. MOTIS records the
# version of every binary format it wrote into data/meta/ and refuses at
# startup to serve data whose versions differ from its own, so this is not a
# nicety — a bundle assembled any other way could fail that check.
#
# MOTIS_VERSION is stated HERE and nowhere else. Renovate bumps it on this
# line; build.sh reads it from this line for the tag. A second copy anywhere
# would be the one that drifts.
ARG MOTIS_VERSION=2.11.2

# ── 1. Import ────────────────────────────────────────────────────────────────
# Inside the build rather than in a `docker run` with a bind mount, because
# the import grows its output files with mmap, and a Docker Desktop bind mount
# (Windows, macOS) cannot resize a mapped file: `unable to import: resize
# error` within seconds. A build stage writes to an ordinary container
# filesystem everywhere, so the same file works on a laptop and on the Linux
# runner — and BuildKit caches the stage, so a local re-run with unchanged
# inputs skips the forty minutes.
FROM ghcr.io/motis-project/motis:${MOTIS_VERSION} AS import
# Upstream sets USER motis; the import writes into the stage's filesystem, so
# it runs as root here. The serving stage below inherits upstream's user.
USER root
WORKDIR /work
# The build context is the variant's work directory: config.yml and input/.
COPY . .
# The progress bars redraw one line per task per tick and would fill a CI log
# with megabytes of carriage returns. `tr` turns them into lines and `grep`
# drops those that start with the erase-line escape — everything else, task
# lists and errors included, stays. pipefail so the import's own exit code is
# the step's, not grep's.
RUN set -o pipefail && \
    /motis import -c config.yml -d data 2>&1 | tr '\r' '\n' | grep -vF "$(printf '\033[K')"

# ── 2. Bundle ────────────────────────────────────────────────────────────────
FROM ghcr.io/motis-project/motis:${MOTIS_VERSION}

# /bundle, not /data. The upstream image declares `VOLUME /data`, and Docker
# initialises an anonymous volume from the image's content at that path on
# EVERY `docker run`: a multi-gigabyte copy per container start, and a stray
# volume left behind per run. Kubernetes ignores VOLUME, so only local runs
# would pay — but the smoke test in CI is a local run. /bundle is declared
# nowhere, so it is served straight from the image layers.
#
# --chown to the image's own user (upstream's USER motis), so the server can
# write beside its data if it ever needs to, without running as root.
COPY --from=import --chown=motis:motis /work/data /bundle

LABEL org.opencontainers.image.source="https://github.com/pandasoft-zz/motis-bundles" \
      org.opencontainers.image.licenses="MIT"

CMD ["/motis", "server", "-d", "/bundle"]
