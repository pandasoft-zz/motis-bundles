# Runs before the import, in work/czech/ (see build.sh, "Prepare").
#
# IDS JMK: add trip_short_name (the train number, from KORDIS's api.txt) to
# the rail trips, and write train-brands.json (train number -> IDS line
# brand) for the release. Trasio uses the brand for czptt legs, which carry
# only the national name ("Os 4968"). Remove this when KORDIS fills
# trip_short_name in its own feed.
set -euo pipefail
python3 "$REPO/scripts/jmk-train-numbers.py" input/jmk.gtfs.zip train-brands.json
