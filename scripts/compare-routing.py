#!/usr/bin/env python3
"""Compare walk and bike routes of a running bundle with Mapy.cz.

    compare-routing.py <cases.json> <out-dir> [--motis URL] [--srtm DIR]

Mapy.cz is what Trasio uses today for walk and bike stages
(internal/routing/mapycz.go: walking -> foot_hiking, cycling -> bike_road,
mtb -> bike_mountain). For every case and profile the script asks both
routers, then measures the two lines in the same way:

- distance and duration, as each router reports them;
- climb and descent, from the same SRTM tiles for both lines, so the
  numbers do not depend on the elevation model of the router;
- for walking, a hiking time from the MOTIS line by Tobler's hiking
  function. MOTIS 2.11 times walks on flat ground; this column shows what
  a client could compute from the MOTIS geometry and the DEM;
- overlap: how much of one line runs within 50 m of the other.

The Mapy.cz key comes from MAPY_CZ_API_KEY and goes in a header, never in
the URL. Without a key only MOTIS is asked, so the script still works as a
check of the bundle. Output: report.md, report.json and routes.geojson
(both lines of each case, for geojson.io or QGIS).

Only the standard library is used, so it runs wherever build.sh runs.
"""

import argparse
import json
import math
import mmap
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Trasio profile -> (MOTIS mode, Mapy.cz routeType).
PROFILES = {
    "walking": ("WALK", "foot_hiking"),
    "cycling": ("BIKE", "bike_road"),
    "mtb": ("BIKE", "bike_mountain"),
}
MAPY_URL = "https://api.mapy.com/v1/routing/route"
EARTH_R = 6_371_000.0
SAMPLE_M = 20.0      # step for elevation samples along a line
HYSTERESIS_M = 3.0   # ignore height changes smaller than this (DEM noise)
OVERLAP_M = 50.0     # a point is "on the other line" within this distance


# ── geometry ─────────────────────────────────────────────────────────────────

def haversine(a, b):
    """Distance in metres between two (lat, lon) points."""
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dla, dlo = la2 - la1, math.radians(b[1] - a[1])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def line_length(line):
    return sum(haversine(line[i], line[i + 1]) for i in range(len(line) - 1))


def densify(line, step):
    """Points along the line, not more than `step` metres apart."""
    if not line:
        return []
    out = [line[0]]
    for a, b in zip(line, line[1:]):
        d = haversine(a, b)
        n = max(1, int(math.ceil(d / step)))
        for k in range(1, n + 1):
            t = k / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def decode_polyline(points, precision):
    """Google encoded polyline -> list of (lat, lon)."""
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10 ** precision
    while index < len(points):
        for is_lon in (False, True):
            shift, result = 0, 0
            while True:
                b = ord(points[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        coords.append((lat / factor, lon / factor))
    return coords


def overlap(a, b, radius=OVERLAP_M):
    """Share (0..1) of line `a` that runs within `radius` metres of line `b`."""
    if len(a) < 2 or len(b) < 2:
        return None
    lat0 = math.radians(a[0][0])
    # Local flat projection in metres; good enough for a few tens of km.
    def xy(p):
        return (math.radians(p[1]) * EARTH_R * math.cos(lat0), math.radians(p[0]) * EARTH_R)
    grid = {}
    for p in densify(b, radius / 5):
        x, y = xy(p)
        grid.setdefault((int(x // radius), int(y // radius)), []).append((x, y))
    pts = densify(a, radius / 5)
    hit = 0
    for p in pts:
        x, y = xy(p)
        cx, cy = int(x // radius), int(y // radius)
        if any((x - qx) ** 2 + (y - qy) ** 2 <= radius ** 2
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for qx, qy in grid.get((cx + dx, cy + dy), ())):
            hit += 1
    return hit / len(pts)


# ── elevation ────────────────────────────────────────────────────────────────

class Srtm:
    """Heights from SRTM .hgt tiles (1 or 3 arc-second), as MOTIS reads them."""

    def __init__(self, directory):
        self.dir = Path(directory) if directory else None
        self.tiles = {}

    def _tile(self, lat0, lon0):
        key = (lat0, lon0)
        if key not in self.tiles:
            name = f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}.hgt"
            path = self.dir / name if self.dir else None
            if path and path.exists():
                # The map stays valid after the file is closed.
                with open(path, "rb") as f:
                    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                size = int(round(math.sqrt(len(m) // 2)))
                self.tiles[key] = (m, size)
            else:
                self.tiles[key] = None
        return self.tiles[key]

    def _cell(self, tile, row, col):
        m, size = tile
        i = 2 * (row * size + col)
        v = int.from_bytes(m[i:i + 2], "big", signed=True)
        return None if v == -32768 else v

    def height(self, lat, lon):
        """Bilinear height in metres, or None outside the tiles."""
        lat0, lon0 = math.floor(lat), math.floor(lon)
        tile = self._tile(lat0, lon0)
        if tile is None:
            return None
        n = tile[1] - 1
        r = (lat0 + 1 - lat) * n
        c = (lon - lon0) * n
        r0, c0 = min(int(r), n - 1), min(int(c), n - 1)
        fr, fc = r - r0, c - c0
        vals = [self._cell(tile, r0 + dr, c0 + dc) for dr in (0, 1) for dc in (0, 1)]
        if any(v is None for v in vals):
            return next((v for v in vals if v is not None), None)
        top = vals[0] * (1 - fc) + vals[1] * fc
        bottom = vals[2] * (1 - fc) + vals[3] * fc
        return top * (1 - fr) + bottom * fr

    def profile(self, line):
        """[(distance from start, height)] every SAMPLE_M metres."""
        pts = densify(line, SAMPLE_M)
        out, dist = [], 0.0
        for i, p in enumerate(pts):
            if i:
                dist += haversine(pts[i - 1], p)
            h = self.height(*p)
            if h is not None:
                out.append((dist, h))
        return out


def climb(profile, hysteresis=HYSTERESIS_M):
    """(up, down) in metres; changes smaller than `hysteresis` are noise."""
    if not profile:
        return None, None
    up = down = 0.0
    ref = profile[0][1]
    for _, h in profile[1:]:
        if h - ref >= hysteresis:
            up += h - ref
            ref = h
        elif ref - h >= hysteresis:
            down += ref - h
            ref = h
    return round(up), round(down)


def tobler_seconds(profile):
    """Hiking time by Tobler: v = 6 * exp(-3.5 * |slope + 0.05|) km/h."""
    if len(profile) < 2:
        return None
    total = 0.0
    for (d0, h0), (d1, h1) in zip(profile, profile[1:]):
        dx = d1 - d0
        if dx <= 0:
            continue
        v = 6.0 * math.exp(-3.5 * abs((h1 - h0) / dx + 0.05)) / 3.6
        total += dx / v
    return round(total)


# ── routers ──────────────────────────────────────────────────────────────────

def get_json(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def motis_route(base, frm, to, mode, elevation_costs="NONE"):
    params = {
        "fromPlace": f"{frm[0]},{frm[1]}",
        "toPlace": f"{to[0]},{to[1]}",
        "transitModes": "",          # empty: direct street routes only
        "directModes": mode,
        "maxDirectTime": 6 * 3600,   # long hikes must not be cut off
        "elevationCosts": elevation_costs,
        "detailedLegs": "true",
    }
    data = get_json(f"{base}/api/v6/plan?{urllib.parse.urlencode(params)}")
    direct = data.get("direct") or []
    if not direct:
        return None
    it = direct[0]
    line, up, down = [], 0, 0
    for leg in it["legs"]:
        g = leg.get("legGeometry") or {}
        seg = decode_polyline(g.get("points", ""), g.get("precision", 6))
        line += seg[1:] if line else seg
        for s in leg.get("steps") or []:
            up += s.get("elevationUp") or 0
            down += s.get("elevationDown") or 0
    return {"duration": it["duration"], "distance": round(line_length(line)),
            "line": line, "router_up": up, "router_down": down}


def mapy_route(key, frm, to, route_type, retries=3):
    params = {
        "start": f"{frm[1]},{frm[0]}",
        "end": f"{to[1]},{to[0]}",
        "routeType": route_type,
        "lang": "cs",
    }
    url = f"{MAPY_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            data = get_json(url, headers={"X-Mapy-Api-Key": key})
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            if e.code in (400, 404):
                return None
            raise
    coords = data["geometry"]["geometry"]["coordinates"]
    line = [(c[1], c[0]) for c in coords]
    return {"duration": data["duration"], "distance": data["length"], "line": line,
            "router_up": data.get("ascent"), "router_down": data.get("descent")}


# ── report ───────────────────────────────────────────────────────────────────

def minutes(s):
    return "–" if s is None else f"{s / 60:.0f}"


def km(m):
    return "–" if m is None else f"{m / 1000:.2f}"


def ratio(a, b):
    return "–" if a is None or not b else f"{a / b:.2f}"


def pct(x):
    return "–" if x is None else f"{x * 100:.0f} %"


def run(args):
    cases = json.loads(Path(args.cases).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("MAPY_CZ_API_KEY", "")
    srtm = Srtm(args.srtm)
    results, features = [], []

    for case in cases:
        frm, to = tuple(case["from"]), tuple(case["to"])
        for profile in case["profiles"]:
            mode, route_type = PROFILES[profile]
            row = {"name": case["name"], "profile": profile,
                   "crow": round(haversine(frm, to))}
            variants = {"motis": ("NONE",)}
            if mode == "BIKE":
                # HIGH shows what the elevation data change for BIKE.
                variants["motis_high"] = ("HIGH",)
            for label, (costs,) in variants.items():
                try:
                    r = motis_route(args.motis, frm, to, mode, costs)
                except (urllib.error.URLError, OSError) as e:
                    print(f"{case['name']} {profile} {label}: {e}", file=sys.stderr)
                    r = None
                row[label] = r
            if key:
                try:
                    row["mapy"] = mapy_route(key, frm, to, route_type)
                except (urllib.error.URLError, OSError, KeyError) as e:
                    print(f"{case['name']} {profile} mapy: {e}", file=sys.stderr)
                    row["mapy"] = None
                time.sleep(0.2)  # be gentle with the paid API

            for label in ("motis", "motis_high", "mapy"):
                r = row.get(label)
                if not r:
                    continue
                prof = srtm.profile(r["line"])
                r["dem_up"], r["dem_down"] = climb(prof)
                if profile == "walking" and label == "motis":
                    r["tobler"] = tobler_seconds(prof)
                features.append({
                    "type": "Feature",
                    "properties": {"case": case["name"], "profile": profile, "router": label,
                                   "duration_min": round(r["duration"] / 60),
                                   "distance_m": r["distance"], "dem_up_m": r["dem_up"]},
                    "geometry": {"type": "LineString",
                                 "coordinates": [[round(p[1], 6), round(p[0], 6)] for p in r["line"]]},
                })
            if row.get("motis") and row.get("mapy"):
                row["overlap_motis_on_mapy"] = overlap(row["motis"]["line"], row["mapy"]["line"])
                row["overlap_mapy_on_motis"] = overlap(row["mapy"]["line"], row["motis"]["line"])
            results.append(row)
            m = row.get("motis") or {}
            print(f"{case['name']:<38} {profile:<8} motis {minutes(m.get('duration')):>4} min "
                  f"{km(m.get('distance')):>6} km  mapy {minutes((row.get('mapy') or {}).get('duration')):>4} min",
                  file=sys.stderr)

    # Lines are in routes.geojson; keep report.json small.
    slim = [{k: ({kk: vv for kk, vv in v.items() if kk != "line"} if isinstance(v, dict) else v)
             for k, v in r.items()} for r in results]
    (out / "report.json").write_text(json.dumps(slim, indent=2, ensure_ascii=False) + "\n")
    (out / "routes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}) + "\n")
    (out / "report.md").write_text(markdown(results, bool(key), bool(args.srtm)))
    print(f"wrote {out}/report.md, report.json, routes.geojson", file=sys.stderr)


def markdown(results, with_mapy, with_dem):
    lines = ["# Routing: MOTIS vs Mapy.cz", ""]
    if not with_mapy:
        lines += ["MAPY_CZ_API_KEY not set: MOTIS only.", ""]
    if not with_dem:
        lines += ["No --srtm directory: climb columns are empty.", ""]
    lines += [
        "Times in minutes, distances in km. *Climb* is counted from the same SRTM",
        "tiles for every line. *MOTIS climb (own)* is what MOTIS itself reports",
        "(`elevationUp` of the steps); 0 there means the bundle has no elevation data.",
        "*Overlap* is the share of the MOTIS line within 50 m of the Mapy.cz line,",
        "and the other way round.", "",
    ]
    for profile in PROFILES:
        rows = [r for r in results if r["profile"] == profile]
        if not rows:
            continue
        lines += [f"## {profile} (MOTIS {PROFILES[profile][0]} vs Mapy.cz `{PROFILES[profile][1]}`)", ""]
        if profile == "walking":
            head = ("| case | crow km | MOTIS min | Tobler min | Mapy min | MOTIS/Mapy time "
                    "| MOTIS km | Mapy km | climb MOTIS | climb Mapy | MOTIS climb (own) | overlap |")
        else:
            head = ("| case | crow km | MOTIS min | MOTIS HIGH min | Mapy min | MOTIS/Mapy time "
                    "| MOTIS km | Mapy km | climb MOTIS | climb MOTIS HIGH | climb Mapy | MOTIS climb (own) | overlap |")
        lines += [head, "|" + "---|" * (head.count("|") - 1)]
        for r in rows:
            m, h, y = r.get("motis") or {}, r.get("motis_high") or {}, r.get("mapy") or {}
            ov = (f"{pct(r.get('overlap_motis_on_mapy'))} / {pct(r.get('overlap_mapy_on_motis'))}"
                  if "overlap_motis_on_mapy" in r else "–")
            cells = [r["name"], km(r["crow"]), minutes(m.get("duration"))]
            if profile == "walking":
                cells.append(minutes(m.get("tobler")))
            else:
                cells.append(minutes(h.get("duration")))
            cells += [minutes(y.get("duration")), ratio(m.get("duration"), y.get("duration")),
                      km(m.get("distance")), km(y.get("distance")), str(m.get("dem_up", "–"))]
            if profile != "walking":
                cells.append(str(h.get("dem_up", "–")))
            cells += [str(y.get("dem_up", "–")), str(m.get("router_up", "–")), ov]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cases", help="JSON list of {name, from: [lat, lon], to: [lat, lon], profiles}")
    ap.add_argument("out", help="directory for report.md, report.json, routes.geojson")
    ap.add_argument("--motis", default="http://127.0.0.1:18080", help="base URL of the bundle")
    ap.add_argument("--srtm", help="directory with .hgt tiles (work/<variant>/input/srtm)")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
