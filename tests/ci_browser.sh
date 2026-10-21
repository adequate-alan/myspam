#!/usr/bin/env bash
# Installs the pinned Playwright and its headless Chromium for a CI job (Oct 21). The GitHub runner image already has
# Chrome's system libraries, so the ~20 s apt step (`--with-deps`) runs only when the browser can't start without it.
set -euo pipefail
pip install -r tests/requirements-ci.txt
python -m playwright install --only-shell chromium
probe='from playwright.sync_api import sync_playwright as s
p = s().start(); p.chromium.launch().close(); p.stop()'
if ! python -c "$probe" 2>/dev/null; then
  echo "Browser needs system libraries: installing them"
  python -m playwright install-deps chromium
  python -c "$probe"
fi
