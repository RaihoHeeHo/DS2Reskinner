#!/bin/bash
# Double-click this in Finder to start DS2 Reskinner.
cd "$(dirname "$0")"
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python's window toolkit (tkinter) isn't installed."
  V=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  echo "If you use Homebrew Python, run:   brew install python-tk@$V"
  echo "Or install Python from https://www.python.org (it includes tkinter)."
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
python3 ds2_reskinner.py
