# Routing comparison: MOTIS 2.11.3 vs Mapy.cz

Run on 2026-10-25 with `build.sh compare czech` (bundle with SRTM1
elevation, OSM of 2026-10-24). Mapy.cz profiles are the ones Trasio uses:
walking → `foot_hiking`, cycling → `bike_road`, mtb → `bike_mountain`.

## Results

- **Elevation data is good.** Where both routers take the same path, the
  climb counted from our SRTM tiles is the same for both lines (Sněžka 847 /
  842 m, Radhošť 166 / 164 m, Špilberk 89 / 94 m).
- **Walk times: MOTIS is flat.** MOTIS times are 0.31–0.70 of the Mapy.cz
  times, and the gap grows with the climb: Ještěd 36 vs 117 min, Lysá hora
  84 vs 227 min. In 2.11 elevation changes BIKE only. Mapy.cz
  `foot_hiking` is slow even in town (0.92 km in 21 min).
  A Tobler time computed from the MOTIS line and the DEM closes about half
  of the gap.
- **Walk paths: mostly the same.** 95–100 % overlap on Pražský hrad, Špilberk,
  Sněžka, Radhošť and Praděd. They differ where Mapy.cz keeps to marked
  trails: Ještěd 23 %, Lysá hora 68 / 48 %, Kleť 71 / 46 %.
- **Road bike: times similar, paths not.** On flat routes MOTIS needs
  1.1× the Mapy.cz time, but only 0–42 % of the lines overlap. Beroun →
  Karlštejn: Mapy.cz rides 20 km where MOTIS rides 11 km.
  `elevationCosts=HIGH` cuts the climb where a flat way exists
  (Praha → Černošice 316 → 135 m, Mapy.cz 151 m).
- **MTB uphill: MOTIS far too fast.** The bike speed is flat 15 km/h:
  Lysá hora 32 min vs 107 min (HIGH: 67 min), Kleť 15 vs 48 min.
- **MOTIS climb (own)** is higher than the DEM climb on flat routes
  (Olomouc → Litovel 384 vs 119 m). osr stores up/down per way segment in
  4 bits each (0, 1, 2, 4, 6, 8, 11 … 48 m) and rounds up, so small bumps
  add up.

Tables below; lines in `work/czech/compare/routes.geojson` after a run.

## walking (MOTIS WALK vs Mapy.cz `foot_hiking`)

| case | crow km | MOTIS min | Tobler min | Mapy min | MOTIS/Mapy time | MOTIS km | Mapy km | climb MOTIS | climb Mapy | MOTIS climb (own) | overlap |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Praha: Malostranské nám. -> Pražský hrad | 0.41 | 12 | 14 | 21 | 0.55 | 0.85 | 0.92 | 67 | 64 | 0 | 100 % / 98 % |
| Praha: Malostranské nám. -> Petřín | 0.83 | 18 | 23 | 35 | 0.52 | 1.29 | 1.29 | 125 | 127 | 0 | 67 % / 57 % |
| Brno: hl. n. -> Špilberk | 1.10 | 21 | 23 | 35 | 0.59 | 1.48 | 1.46 | 89 | 94 | 0 | 98 % / 98 % |
| Horní Hanychov -> Ještěd | 2.40 | 36 | 72 | 117 | 0.31 | 2.59 | 3.77 | 506 | 497 | 0 | 23 % / 16 % |
| Ovčárna -> Praděd | 1.54 | 54 | 48 | 77 | 0.70 | 3.22 | 3.70 | 186 | 195 | 0 | 98 % / 84 % |
| Pec pod Sněžkou -> Sněžka | 4.67 | 89 | 131 | 198 | 0.45 | 6.36 | 6.47 | 847 | 842 | 0 | 95 % / 94 % |
| Ostravice -> Lysá hora | 4.00 | 84 | 134 | 227 | 0.37 | 5.80 | 7.86 | 911 | 913 | 0 | 68 % / 48 % |
| Pustevny -> Radhošť | 3.05 | 53 | 54 | 76 | 0.70 | 3.77 | 3.78 | 166 | 164 | 0 | 100 % / 100 % |
| Pavlov -> Děvín | 1.60 | 37 | 49 | 80 | 0.46 | 2.63 | 2.78 | 312 | 315 | 0 | 84 % / 82 % |
| Krasetín -> Kleť | 3.00 | 51 | 73 | 142 | 0.36 | 3.39 | 5.19 | 531 | 552 | 0 | 71 % / 46 % |

## cycling (MOTIS BIKE vs Mapy.cz `bike_road`)

| case | crow km | MOTIS min | MOTIS HIGH min | Mapy min | MOTIS/Mapy time | MOTIS km | Mapy km | climb MOTIS | climb MOTIS HIGH | climb Mapy | MOTIS climb (own) | overlap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Brno hl. n. -> Tišnov | 22.29 | 110 | 139 | 99 | 1.10 | 25.00 | 25.43 | 457 | 519 | 330 | 767 | 42 % / 42 % |
| Praha Palackého nám. -> Černošice | 14.59 | 73 | 86 | 67 | 1.09 | 17.25 | 18.58 | 316 | 135 | 151 | 590 | 30 % / 26 % |
| Olomouc hl. n. -> Litovel | 18.94 | 94 | 100 | 79 | 1.18 | 21.88 | 23.20 | 119 | 88 | 97 | 384 | 1 % / 0 % |
| Beroun -> Karlštejn | 8.34 | 45 | 53 | 78 | 0.57 | 10.77 | 19.98 | 211 | 211 | 309 | 405 | 16 % / 8 % |
| Boží Dar -> Klínovec | 3.43 | 16 | 23 | 27 | 0.58 | 3.94 | 4.22 | 233 | 243 | 228 | 304 | 19 % / 16 % |
| Brno Bystrc přístaviště -> Kraví hora | 5.27 | 32 | 43 | 28 | 1.12 | 6.75 | 6.44 | 99 | 101 | 109 | 196 | 28 % / 30 % |

## mtb (MOTIS BIKE vs Mapy.cz `bike_mountain`)

| case | crow km | MOTIS min | MOTIS HIGH min | Mapy min | MOTIS/Mapy time | MOTIS km | Mapy km | climb MOTIS | climb MOTIS HIGH | climb Mapy | MOTIS climb (own) | overlap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ovčárna -> Praděd | 1.54 | 15 | 19 | 23 | 0.67 | 3.22 | 3.70 | 186 | 186 | 195 | 241 | 98 % / 84 % |
| Ostravice -> Lysá hora | 4.00 | 32 | 67 | 107 | 0.30 | 7.97 | 15.16 | 954 | 1011 | 1036 | 851 | 10 % / 5 % |
| Pustevny -> Radhošť | 3.05 | 16 | 21 | 23 | 0.69 | 3.91 | 3.91 | 166 | 163 | 167 | 219 | 100 % / 100 % |
| Krasetín -> Kleť | 3.00 | 15 | 32 | 48 | 0.31 | 3.39 | 4.82 | 531 | 572 | 537 | 431 | 58 % / 38 % |
