#!/bin/sh
# Build the PC port into build/port/bin
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH=/c/msys64/ucrt64/bin:$PATH
cmake -S "$ROOT/port" -B "$ROOT/build/port" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -Wno-dev
# all cores at once can overwhelm some PCs (one crashed here); override with JOBS=n
ninja -j "${JOBS:-8}" -C "$ROOT/build/port" MapleStoryDS
echo "built: $ROOT/build/port/bin/MapleStoryDS.exe"
