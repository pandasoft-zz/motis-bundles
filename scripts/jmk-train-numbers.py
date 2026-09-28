#!/usr/bin/env python3
"""Add train numbers to the IDS JMK (KORDIS) feed and write train-brands.json.

    jmk-train-numbers.py <jmk.gtfs.zip> <train-brands.json>

The KORDIS feed has no trip_short_name. Its rail routes carry the IDS line
brand ("S3") as route_short_name, and the train number ("4968") is only in
the non-standard api.txt, which MOTIS does not read:

    Linka/CVlaku = trip_id: <line>/<train number> = <trip_id>

This script does two things with api.txt:

1. It adds the column trip_short_name to trips.txt and fills it with the
   train number for every rail trip. It only adds: a value that is already
   there stays. Bus and tram trips stay empty. The zip is written back in
   place, and every other file in it stays byte for byte the same.
2. It writes {"<train number>": "<line brand>", ...} for rail trips. A train
   number with more than one brand (a train that runs as S2 and then as S3)
   is left out, because we cannot say which brand is right.

The result is standard GTFS. See https://gtfs.org/documentation/schedule/reference/#tripstxt
Only the Python standard library is used.
"""

import csv
import io
import json
import os
import re
import sys
import tempfile
import zipfile

API_LINE = re.compile(r"^Linka/CVlaku = trip_id: (?P<line>[^/]+)/(?P<number>\S+) = (?P<trip>\S+)\s*$")


def is_rail(route_type):
    """Basic GTFS rail (2) or an extended rail type (100-117)."""
    try:
        t = int(route_type)
    except ValueError:
        return False
    return t == 2 or 100 <= t <= 117


def read_csv(zf, name):
    with zf.open(name) as f:
        text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        return reader.fieldnames or [], list(reader)


def read_api(zf):
    numbers = {}
    with zf.open("api.txt") as f:
        for raw in io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace"):
            m = API_LINE.match(raw.strip())
            if m:
                numbers[m.group("trip")] = m.group("number")
    return numbers


def main(zip_path, json_path):
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for need in ("api.txt", "routes.txt", "trips.txt"):
            if need not in names:
                sys.exit(f"{zip_path}: {need} is missing")
        numbers = read_api(zf)
        _, routes = read_csv(zf, "routes.txt")
        fields, trips = read_csv(zf, "trips.txt")

    if not numbers:
        sys.exit(f"{zip_path}: api.txt has no train numbers; did its format change?")

    brand_of = {r["route_id"]: (r.get("route_short_name") or "").strip()
                for r in routes if is_rail(r.get("route_type", ""))}

    if "trip_short_name" not in fields:
        fields = fields + ["trip_short_name"]
    added = kept = 0
    brands = {}
    conflicts = set()
    for t in trips:
        if t["route_id"] not in brand_of:
            continue  # DictWriter writes a missing value as ""
        number = numbers.get(t["trip_id"], "")
        if (t.get("trip_short_name") or "").strip():
            kept += 1
        else:
            t["trip_short_name"] = number
            added += 1 if number else 0
        brand = brand_of[t["route_id"]]
        if not number or not brand:
            continue
        if brands.get(number, brand) != brand:
            conflicts.add(number)
        brands.setdefault(number, brand)
    for number in conflicts:
        del brands[number]

    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(trips)
    new_trips = out.getvalue().encode("utf-8")

    # A new zip beside the old one, moved over it on success: a failure
    # half way cannot leave a broken feed for the import.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(zip_path)), suffix=".part")
    os.close(fd)
    try:
        with zipfile.ZipFile(zip_path) as src, \
                zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = new_trips if info.filename == "trips.txt" else src.read(info)
                dst.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(tmp, zip_path)
    except BaseException:
        os.unlink(tmp)
        raise

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(brands.items(), key=lambda kv: (len(kv[0]), kv[0]))), f,
                  ensure_ascii=False, indent=0, separators=(",", ":"))
        f.write("\n")

    print(f"trip_short_name: {added} rail trips filled, {kept} kept as they were")
    print(f"train-brands.json: {len(brands)} train numbers, {len(conflicts)} left out (more than one brand)")
    if added + kept == 0:
        sys.exit(f"{zip_path}: no rail trip got a train number; did the feed change?")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    main(sys.argv[1], sys.argv[2])
