#!/bin/sh
# One-time setup for building the PC port on Windows with MSYS2 (ucrt64).
#  - installs the toolchain packages (SDL2, CMake, Ninja, GCC)
#  - clones the DS hardware model (melonDS 1.1, GPL-3.0) into thirdparty/
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
/c/msys64/usr/bin/bash.exe -lc "pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-SDL2 mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja"
if [ ! -d "$ROOT/thirdparty/melonDS-src" ]; then
    git clone --depth 1 --branch 1.1 https://github.com/melonDS-emu/melonDS.git "$ROOT/thirdparty/melonDS-src"
fi
for p in "$ROOT"/port/patches/*.patch; do
    [ -e "$p" ] || continue
    git -C "$ROOT/thirdparty/melonDS-src" apply --check "$p" 2>/dev/null && git -C "$ROOT/thirdparty/melonDS-src" apply "$p" && echo "applied $(basename "$p")"
done
echo "setup done"
