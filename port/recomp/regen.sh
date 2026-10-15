#!/bin/sh
# Re-export P-code from the Ghidra project and regenerate build/gen.
# Usage: port/recomp/regen.sh            (expects work/ghidra_full created by import.sh)
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GH=/c/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat
W="$ROOT/work"
PCODE_OUT="$W/pcode_full.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -readOnly \
    -scriptPath "$ROOT/tools/ghidra_scripts" -postScript ExportPcode.java > "$W/export.log" 2>&1
mkdir -p "$ROOT/build/gen" && rm -f "$ROOT/build/gen"/*
python "$ROOT/port/recomp/pcode2c.py" "$W/pcode_full.txt" "$ROOT/build/gen" --extra-entries "$W/extra_entries.txt" --overlay-dir "$ROOT/extracted/overlay_dec" | head -2
