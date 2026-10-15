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
# the Mobiclip decoder image (ov200, created by AddOverlays from overlay_dec/ov200_*.bin) is reached
# only through runtime pointers and computed jumps: seed its entry and sweep it linearly
echo "1ff8500 ov200 0" > "$W/seeds_manual.txt"
MSDS_SEEDS="$W/seeds_manual.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" -postScript SeedOverlays.java > "$W/seed_manual.log" 2>&1
"$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" -postScript SeedLinear.java ov200 > "$W/seed_linear.log" 2>&1
"$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" -postScript SeedOverlayPointers.java > "$W/seed_ovptr.log" 2>&1
MSDS_EXTRA_ENTRIES="$W/extra_entries.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" \
    -postScript SeedStatic.java > "$W/seed_static.log" 2>&1
# Thumb switch tables Ghidra did not recover (their case blocks would be missing from the C):
# needs a P-code export to know what is decoded, then seed the targets and export again (regen.sh)
PCODE_OUT="$W/pcode_full.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -readOnly \
    -scriptPath "$S" -postScript ExportPcode.java > "$W/export.log" 2>&1
python "$ROOT/tools/find_switch_tables.py" --out "$W/switch_seeds.txt"
MSDS_SWITCH="$W/switch_seeds.txt" "$GH" "$W/ghidra_full" msfull -process arm9_dec.bin -noanalysis -scriptPath "$S" \
    -postScript SeedSwitchTargets.java > "$W/seed_switch.log" 2>&1
grep -h -E "seeded|orphan|functions now|switch targets" "$W/seed_overlays.log" "$W/seed_static.log" "$W/seed_switch.log"
