"""Bisect which recompiled function is wrong: interpret the first k functions of a list and check
whether frame N matches a reference screenshot. usage: bisect_interp.py ref.bmp frames fnlist.txt"""
import subprocess, sys, os
from PIL import Image, ImageChops
ref, frames, lst = sys.argv[1], sys.argv[2], sys.argv[3]
fns = [int(x, 16) for x in open(lst).read().split()]
rom = '../../MapleStory DS (English).nds'
refim = Image.open(ref).convert('RGB')

def ok(k):
    ranges = ','.join('%08x-%08x' % (a, a) for a in fns[:k]) or '0-0'
    env = dict(os.environ, MSDS_HEADLESS='1', MSDS_INTERP_FN=ranges)
    subprocess.run(['./MapleStoryDS.exe', rom, '--test-frames', frames, '--test-shot', 'bis.bmp'], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    im = Image.open('bis.bmp').convert('RGB')
    diff = ImageChops.difference(im, refim).getbbox()
    print('k=%d -> %s' % (k, 'match' if diff is None else 'differs'), flush=True)
    return diff is None

lo, hi = 0, len(fns)
assert ok(hi), 'interpreting all listed functions does not fix it'
while lo < hi:
    mid = (lo + hi) // 2
    if ok(mid): hi = mid
    else: lo = mid + 1
print('culprit: function #%d at %08x' % (lo - 1, fns[lo - 1]))
