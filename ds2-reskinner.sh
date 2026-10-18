#!/bin/sh
# Start DS2 Reskinner on Linux:  ./ds2-reskinner.sh
cd "$(dirname "$0")"
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python's tkinter is missing. Install it with your package manager, e.g."
  echo "  Debian/Ubuntu: sudo apt install python3-tk"
  echo "  Fedora:        sudo dnf install python3-tkinter"
  echo "  Arch:          sudo pacman -S tk"
  exit 1
fi
exec python3 ds2_reskinner.py "$@"
