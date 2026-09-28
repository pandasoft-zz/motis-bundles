#!/usr/bin/env python3
"""Prepare the czech inputs after download, before `motis import`.

IDS JMK (jmk.gtfs.zip) leaves the standard GTFS field trips.trip_short_name
empty. The train number of each trip is only in the feed's own api.txt,
which MOTIS ignores:

    Linka/CVlaku = trip_id: <line>/<train number> = <trip_id>

This script does two things with it. It changes no value that is already in
the feed; it only adds what is missing.

1. It writes the train number into trips.txt as trip_short_name, for rail
   trips only. MOTIS then returns a jmk rail leg with both names:
   routeShortName "S3" (the IDS line brand) and tripShortName "4968" (the
   train number).

2. It writes out/train-brands.json, a map train number -> IDS line brand
   ({"4968": "S3", ...}). The build attaches it to the release. A client uses
   it for rail legs from the national feed (czptt), which carry only the
   national name ("Os 4968") and no brand.

A train number that runs under more than one brand (a train that changes
line on the way, e.g. S2 and S3) is left out of the map: there is no single
right answer for it. A "brand" with a space in it is a national name, not a
brand, and is left out too.

Usage: prepare.py <work dir>   (the directory with input/ in it)
Standard library only.
"""

import csv
import io
import json
import os
import re
import sys
import zipfile

FEED = "jmk.gtfs.zip"
# GTFS route_type values that mean a train: 2 (rail) and the extended rail
# types 100-117.
RAIL_TYPES = {"2"} | {str(t) for t in range(100, 118)}
API_LINE = re.compile(r"^Linka/CVlaku = trip_id: (\S+)/(\S+) = (\S+)$")


def read_csv(z, name):
    """Returns (header, rows) of a CSV member. utf-8-sig drops a BOM."""
    text = z.read(name).decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    return header, list(reader)


def train_numbers(z):
    """trip_id -> train number, from api.txt."""
    out = {}
    for line in z.read("api.txt").decode("utf-8-sig").splitlines():
        m = API_LINE.match(line.strip())
        if m:
            out[m.group(3)] = m.group(2)
    return out


def is_brand(name):
    return bool(name) and " " not in name


def prepare(work):
    path = os.path.join(work, "input", FEED)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "api.txt" not in names:
            print(f"prepare: {FEED} has no api.txt, nothing to do")
            return None
        numbers = train_numbers(z)

        r_header, r_rows = read_csv(z, "routes.txt")
        ri = {c: i for i, c in enumerate(r_header)}
        short = ri.get("route_short_name")
        routes = {
            row[ri["route_id"]]: (row[ri["route_type"]], row[short] if short is not None else "")
            for row in r_rows
        }

        t_header, t_rows = read_csv(z, "trips.txt")
        if "trip_short_name" not in t_header:
            t_header.append("trip_short_name")
            for row in t_rows:
                row.append("")
        ti = {c: i for i, c in enumerate(t_header)}

        filled = 0
        brands = {}  # train number -> set of brands
        for row in t_rows:
            route_type, short_name = routes.get(row[ti["route_id"]], ("", ""))
            if route_type not in RAIL_TYPES:
                continue
            number = numbers.get(row[ti["trip_id"]])
            if not number:
                continue
            if not row[ti["trip_short_name"]]:
                row[ti["trip_short_name"]] = number
                filled += 1
            if is_brand(short_name):
                brands.setdefault(number, set()).add(short_name)

        # Written without the BOM the original may have; GTFS readers accept
        # both.
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\r\n").writerows([t_header] + t_rows)
        new_trips = buf.getvalue().encode("utf-8")

        # Every other member is copied byte for byte.
        tmp = path + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                data = new_trips if info.filename == "trips.txt" else z.read(info.filename)
                out.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, path)

    unique = {n: next(iter(b)) for n, b in brands.items() if len(b) == 1}
    conflicts = len(brands) - len(unique)
    out_dir = os.path.join(work, "out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "train-brands.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(unique.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0])), f,
                  ensure_ascii=False, indent=0, separators=(",", ":"))
        f.write("\n")

    return filled, len(unique), conflicts


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-2], file=sys.stderr)
        sys.exit(2)
    result = prepare(sys.argv[1])
    if result is None:
        return
    filled, mapped, conflicts = result
    if mapped == 0:
        # api.txt was there but gave nothing: its format changed. Fail the
        # build rather than ship a bundle without train numbers.
        print("prepare: api.txt gave no train numbers — did its format change?", file=sys.stderr)
        sys.exit(1)
    print(f"- jmk: trip_short_name set on {filled} rail trips; "
          f"train-brands.json has {mapped} trains ({conflicts} with more than one brand left out)")


if __name__ == "__main__":
    main()
