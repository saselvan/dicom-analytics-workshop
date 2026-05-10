#!/usr/bin/env bash
# Refresh PS3.6 attribute dictionary from innolitics/dicom-standard (GitHub)
# DICOM standard updates ~once/year. Run when NEMA publishes a supplement.
#
# Usage: ./scripts/refresh_ps36.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
OUT="$REPO_ROOT/skills/dicom-analytics/reference/ps36_attributes.json"
URL="https://raw.githubusercontent.com/innolitics/dicom-standard/master/standard/attributes.json"

echo "Fetching PS3.6 from innolitics/dicom-standard..."
curl -sL "$URL" \
  | python3 -c "
import json, sys
raw = json.load(sys.stdin)
out = []
for a in raw:
    tag = a.get('tag', '')
    if '(' not in tag:
        continue
    tag_id = tag.replace('(','').replace(')','').replace(',','').upper()
    out.append({
        'tag_id': tag_id,
        'tag_id_pretty': tag,
        'keyword': a.get('keyword', ''),
        'name': a.get('name', ''),
        'vr': a.get('valueRepresentation', ''),
        'vm': a.get('valueMultiplicity', ''),
        'is_retired': a.get('retired', '') == 'Y'
    })
json.dump(out, sys.stdout, indent=2)
" > "$OUT"

COUNT=$(python3 -c "import json; print(len(json.load(open('$OUT'))))")
echo "Written $COUNT entries to $OUT"
