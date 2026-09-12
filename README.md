# motis-bundles

Ready-to-run [MOTIS](https://github.com/motis-project/motis) images with a
region's public-transport data already imported, rebuilt weekly.

```sh
docker run --rm -p 8080:8080 ghcr.io/pandasoft-zz/motis-bundles/czech:latest
# http://localhost:8080
```

That is a routing server for the whole of Czechia — trains, regional and
national buses, Prague and Brno public transport, walking on OpenStreetMap,
geocoding — with no import to run and no data to download.

## Why a bundle

`motis import` turns feeds and an OSM extract into a data directory, and
`motis server` serves that directory. The import takes tens of minutes and
several gigabytes of memory; the server needs neither, only the result. Doing
the import where the server runs means every server carries an import's worth
of memory, disk and failure modes for a job that happens once a week.

A bundle moves the import here, where compute is free and roomy, and ships
the result as an image: the upstream MOTIS binary, unchanged, plus its data.
Two things follow from the "plus its data":

- **The version can't drift.** MOTIS writes the version of each binary format
  into the data and refuses at startup to serve data written by another. A
  bundle carries the binary that wrote its data, so that check can only pass.
- **Nothing is configured at run time.** `motis server` has one option, the
  data directory, and reads its config from a copy the import left there.
  What a bundle does is decided in this repository; changing it means a
  commit and a build, and the change is visible in git.

The upstream image declares `VOLUME /data`; the bundle keeps its data at
`/bundle` instead, so `docker run` does not copy gigabytes into an anonymous
volume on every start.

## Images and tags

| image | dataset |
|---|---|
| `ghcr.io/pandasoft-zz/motis-bundles/czech` | Czechia: IDS JMK, PID, national rail (CZPTT), national buses (JDF), OSM Czech Republic |

Every build pushes three tags:

| tag | example | meant for |
|---|---|---|
| `<motis>-<date>-<time>` | `2.11.2-20260915-0100` | deployments. Immutable: one per build, never overwritten. |
| `<motis>` | `2.11.2` | "the newest data for this MOTIS" |
| `latest` | | `docker run` |

The first part of every tag is the MOTIS version the bundle was built with
and serves with. Bumping MOTIS (Renovate does it, in the `Dockerfile`)
produces a bundle with the new version in its tag; the graph is rebuilt, not
carried over.

## How a build goes

[`build.sh`](build.sh) does the whole thing and runs identically on a laptop
and in [the workflow](.github/workflows/build.yml):

1. **download** the variant's [`sources.txt`](variants/czech/sources.txt) into
   `work/<variant>/input/` and test every zip — a feed host in maintenance
   answers 200 with an HTML page.
2. **build** with `work/<variant>/` as the context. The
   [`Dockerfile`](Dockerfile) is two stages from the same upstream image: the
   first runs `motis import`, the second copies only its output to `/bundle`.
   The inputs never enter the image, and the import happens inside the build
   because a Docker Desktop bind mount cannot resize the mmap'd files the
   import writes (`unable to import: resize error`) — a build stage works
   the same on a laptop and on the Linux runner.
3. **smoke-test** it: start the image, wait for `/api/v1/health`, geocode a
   place, plan a journey for tomorrow morning and check it contains transit.

Only then does the workflow push. A bundle that fails any step is not
published and the previous one stays current. The workflow also runs on pull
requests without pushing, so a MOTIS bump or a config change is proven to
build and serve before it merges.

Builds run Mondays 01:00 UTC, on every push to `main`, and by hand from the
Actions tab.

## Adding a variant

```
variants/<name>/
  config.yml     MOTIS import config; input paths are input/<file>
  sources.txt    <file>  <url>, one per line
```

Then add `<name>` to the matrix in `.github/workflows/build.yml`. The image
is `ghcr.io/pandasoft-zz/motis-bundles/<name>`. On first push GHCR creates
the package **private**; switch it to public in the package settings or
nobody can pull it.

The smoke test plans Brno → Praha by default. A variant elsewhere sets
`SMOKE_FROM`, `SMOKE_TO` (`lat,lon`) and `SMOKE_GEOCODE` for `build.sh`.

## Running a build locally

```sh
./build.sh czech                  # -> motis-bundles/czech:dev
docker run --rm -p 8080:8080 motis-bundles/czech:dev
```

Needs docker, curl, jq. Budget about a gigabyte of download and, on a
laptop, tens of minutes for the import; `work/` is git-ignored. BuildKit
caches the import stage, so a re-run with unchanged inputs and config skips
it.

## Keeping the schedule alive

GitHub disables scheduled workflows in a repository with no activity for 60
days. Renovate's merged bumps are commits, and the scheduled run re-enables
itself through the API when it finishes. If a Monday build is missing, look
for a "disabled" banner on the workflow before looking anywhere else.

## License

MIT. The data comes from its publishers under their own terms: KORDIS JMK,
ROPID, the Czech national timetable (CIS JŘ via ggu.cz and
[gtfs-processor](https://github.com/0xaa55h/gtfs-processor)) and
OpenStreetMap contributors (ODbL).
