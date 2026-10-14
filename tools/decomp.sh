#!/bin/sh
# usage: decomp.sh OUTFILE args...
out="$1"; shift
DECOMP_OUT="$out" /c/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat "F:/Claude Projects/Maplestory-DS/work/ghidra" msds -process arm9_dec.bin -noanalysis -readOnly -scriptPath "F:/Claude Projects/Maplestory-DS/tools/ghidra_scripts" -postScript Decomp.java "$@" > /dev/null 2>&1
