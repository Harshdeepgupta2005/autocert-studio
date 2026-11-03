#!/bin/bash
# AutoCert Studio launcher — double-click me.
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Setting up (first run, ~30 seconds)…"
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet -r requirements.txt
fi

echo "Starting AutoCert Studio…"
./venv/bin/python app.py
