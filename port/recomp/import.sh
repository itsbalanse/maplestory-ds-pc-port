#!/bin/sh
# One-time Ghidra analysis of the ARM9 binary, ITCM/DTCM and all overlays (takes ~5 minutes).
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GH=/c/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat
W="$ROOT/work"; mkdir -p "$W/ghidra_full"
S="$ROOT/tools/ghidra_scripts"
MSDS_EXTRACTED="$ROOT/extracted" "$GH" "$W/ghidra_full" msfull -import "$ROOT/extracted/arm9_dec.bin" -loader BinaryLoader \
    -loader-baseAddr 0x02000000 -processor "ARM:LE:32:v5t" -preScript AddOverlays.java -scriptPath "$S" > "$W/ghidra_import.log" 2>&1
"$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" -postScript SeedOverlays.java > "$W/seed_overlays.log" 2>&1
MSDS_EXTRA_ENTRIES="$W/extra_entries.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" \
    -postScript SeedStatic.java > "$W/seed_static.log" 2>&1
grep -h -E "seeded|orphan|functions now" "$W/seed_overlays.log" "$W/seed_static.log"
