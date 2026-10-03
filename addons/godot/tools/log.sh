#!/bin/sh
# Print a Godot log as UTF-8 (Windows PowerShell's *> redirect writes UTF-16 in some hosts). Usage: tools/log.sh FILE
if head -c 2 "$1" | od -An -tx1 | grep -q "ff fe"; then iconv -f UTF-16 -t UTF-8 "$1"; else cat "$1"; fi
