#!/bin/sh
# Essay front-end check: node tests, then headless Chrome renders at
# 1280px and 375px and asserts every chart placeholder produced output,
# the page does not scroll sideways, and the error slot stayed empty.
set -e
cd "$(git rev-parse --show-toplevel)"

node --test 'essay/test/*.test.mjs'

PORT=$((20000 + RANDOM % 20000))
python3 -m http.server "$PORT" --directory essay >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
if [ ! -x "$CHROME" ]; then CHROME="$(command -v chrome || command -v chromium || command -v google-chrome || true)"; fi
if [ -z "$CHROME" ] || [ ! -x "$CHROME" ]; then echo "essay-check: headless Chrome not found"; exit 1; fi

for W in 1280 375; do
  OUT="$(mktemp -t essay-dom)"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --window-size="$W,900" --virtual-time-budget=30000 \
    --dump-dom "http://127.0.0.1:$PORT/index.html?check=$W" >"$OUT" 2>/dev/null || true
  node - "$OUT" "$W" <<'EOF'
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const w = process.argv[3];
const placeholders = (html.match(/class="chart" data-chart=/g) || []).length;
const rendered = (html.match(/data-rendered="1"/g) || []).length;
const m = html.match(/id="check-result"[^>]*data-overflow="([^"]*)"[^>]*data-unrendered="([^"]*)"[^>]*data-errors="([^"]*)"/);
const overflow = m ? m[1] : "missing";
const unrendered = m ? m[2] : "?";
const errors = m ? m[3] : "?";
const svgs = (html.match(/<svg/g) || []).length + (html.match(/<canvas/g) || []).length;
const ok = placeholders > 0 && rendered === placeholders && overflow === "0" && errors === "0" && svgs >= placeholders;
console.log(`[${w}px] placeholders=${placeholders} rendered=${rendered} svg/canvas=${svgs} overflow=${overflow} errors=${errors}`);
if (!ok) { console.log(`essay-check: FAILED at ${w}px`); process.exit(1); }
EOF
  rm -f "$OUT"
done
echo "essay-check: ok"
