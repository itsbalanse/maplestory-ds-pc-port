#!/bin/sh
# Build the headless melonDS harness (needs MSYS2 ucrt64 toolchain and a built melonDS core).
set -e
export PATH=/c/msys64/ucrt64/bin:$PATH
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HERE/../../thirdparty/melonDS-src/src"
B="$HERE/../../thirdparty/melonDS-build/src"
g++ -std=c++17 -O2 -fwrapv -DNDEBUG -DWIN32_LEAN_AND_MEAN -DNOMINMAX -DARCHITECTURE_x86_64=1 -DJIT_ENABLED \
    -D_WIN32_WINNT=_WIN32_WINNT_WIN8 -I"$S" -I"$B" "$HERE/harness.cpp" -o "$HERE/harness.exe" \
    "$B/libcore.a" "$B/teakra/src/libteakra.a" -lole32 -lcomctl32 -lwsock32 -lws2_32 -lonecore -static -Wl,--stack,67108864
