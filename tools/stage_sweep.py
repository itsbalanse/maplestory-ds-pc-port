"""Whole-game sweep for the native port: warp to every stage (for every class that has scripts in
it) through the game's own Lua (`ChangePlayerJob`, `ChangeStage`), play a little, and flag stages
where the game crashes, hangs (stops running its frame loop), shows black screens, or runs code
the recompiler missed.

usage: python tools/stage_sweep.py SAVE OUTDIR [--workers N] [--only MP001201,...] [--classes 0123]
                                    [--exe PATH] [--interp] [--from-results OLDDIR/results.json]
  --interp: run in the reference interpreter (to tell port bugs from the game's own behaviour)
  --from-results: only rerun the stage/class runs flagged in an earlier sweep
  SAVE: a save that continues into gameplay (the sweep starts from there; it is copied, never written)
Results: OUTDIR/results.json and OUTDIR/report.txt; screenshots in OUTDIR/w*/.
"""
import argparse, concurrent.futures as cf, glob, json, os, re, shutil, subprocess, sys, threading, time
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, 'build', 'port', 'bin', 'MapleStoryDS.exe')
ROM = os.path.join(ROOT, 'build', 'MapleStory DS (English).nds')
STAGES = os.path.join(ROOT, 'extracted', 'nx', 'IN', 'STAGE')
CLASSES = ['SWORDMAN', 'ROGUE', 'ARCHER', 'MAGICIAN']  # ChangePlayerJob / GetClass 0-3
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from narc import parse_narc


def stage_items(classes):
    items = []
    for p in sorted(glob.glob(os.path.join(STAGES, 'MP*.NARC'))):
        stage = os.path.basename(p)[:-5]
        try:
            names, _, _ = parse_narc(open(p, 'rb').read())
        except Exception:
            continue
        have = {n.split('.')[0] for n in names if n.endswith('.SCENE')}
        num = stage[2:]
        if num.startswith('00') and num[2] in '1234':  # a class's own prologue stage
            cls = [int(num[2]) - 1]
        else:
            cls = [i for i, c in enumerate(CLASSES) if c in have] or [0]
        for c in cls:
            if str(c) in classes:
                items.append((stage, c))
    return items


def script_for(items, states=False):
    out = ['pressuntil A 5 183 513820 4000', 'wait 60']
    for stage, c in items:
        tag = '%s_%d' % (stage, c)
        out += ['lua ChangePlayerJob(%d)' % c,
                "lua ChangeStage('%s')" % stage,
                'luawait 2400', 'wait 240', 'shot %s_a' % tag]
        out += ['press A', 'wait 40'] * 8
        out += ['shot %s_b' % tag, 'hold RIGHT', 'wait 90', 'release RIGHT', 'press B', 'wait 30',
                'hold LEFT', 'wait 90', 'release LEFT', 'shot %s_c' % tag,
                "lua Trace('sweep %s')" % tag, 'luawait 2400']
        if states:  # save, play on, load, play the same again: the game must keep running after the load
            out += ['savestate st', 'wait 120', 'shot %s_d' % tag, 'loadstate st', 'wait 120', 'shot %s_e' % tag,
                    "lua Trace('state %s')" % tag, 'luawait 2400']
    return '\n'.join(out) + '\n'


def black_fraction(path):
    try:
        im = Image.open(path).convert('L').crop((0, 0, 256, 192))
    except Exception:
        return None
    px = im.getdata() if not hasattr(im, 'get_flattened_data') else im.get_flattened_data()
    return sum(1 for v in px if v < 12) / (256 * 192)


def run_worker(wid, items, outdir, save, log, exe=EXE, interp=False, states=False):
    wdir = os.path.join(outdir, 'w%02d' % wid)
    os.makedirs(wdir, exist_ok=True)
    results = {}
    todo = list(items)
    attempt = 0
    while todo:
        attempt += 1
        shutil.copy(save, os.path.join(wdir, 'run.sav'))
        open(os.path.join(wdir, 'sweep.txt'), 'w').write(script_for(todo, states))
        t0 = time.time()
        cmd = [exe] + (['--interp'] if interp else []) + ['--test-script', 'sweep.txt', '--test-save', 'run.sav', ROM]
        p = subprocess.run(cmd,
                           cwd=wdir, capture_output=True, text=True, errors='replace', timeout=3600 * 4)
        text = p.stdout + p.stderr
        open(os.path.join(wdir, 'run%d.log' % attempt), 'w').write(text)
        rlog = ''
        if os.path.exists(os.path.join(wdir, 'recomp.log')):
            rlog = open(os.path.join(wdir, 'recomp.log'), errors='replace').read()
            shutil.copy(os.path.join(wdir, 'recomp.log'), os.path.join(wdir, 'recomp%d.log' % attempt))
        warped = re.findall(r"\[lua\] ok: ChangeStage\('(MP\d+)'\)", text)
        probes = re.findall(r"\[lua\] ok: Trace\('%s (MP\d+)_(\d)'\)" % ('state' if states else 'sweep'), text)
        done = {(s, int(c)) for s, c in probes}
        misses = re.findall(r'no recompiled code at ([0-9a-f]+)', text + rlog)
        failed_at = None
        for it in todo:
            if it in done:
                results['%s_%d' % it] = {'ok': True}
            else:
                failed_at = it
                break
        if failed_at is None:
            break
        reason = 'exit %d' % p.returncode
        if 'savestate st failed' in text:
            reason = 'could not save a state'
        elif 'loadstate st failed' in text:
            reason = 'could not load the state'
        elif 'queued Lua did not run' in text:
            reason = 'hang (frame loop stopped)'
        elif 'fatal' in text.lower() or p.returncode not in (0, 2):
            reason = 'crash: ' + (re.findall(r'.*fatal.*', text, re.I) or ['exit %d' % p.returncode])[-1][:200]
        results['%s_%d' % failed_at] = {'ok': False, 'reason': reason, 'warped': failed_at[0] in warped,
                                        'log': 'run%d.log' % attempt}
        log('[w%02d] %s_%d FAILED: %s (%.0fs)' % (wid, failed_at[0], failed_at[1], reason, time.time() - t0))
        if misses:
            results['%s_%d' % failed_at]['interp_fallback'] = sorted(set(misses))
        todo = todo[todo.index(failed_at) + 1:]
    # screenshots: black screens
    for key, r in results.items():
        if not r.get('ok'):
            continue
        fr = [black_fraction(os.path.join(wdir, '%s_%s.bmp' % (key, s))) for s in 'abc']
        r['black'] = fr
        if all(f is not None and f > 0.97 for f in fr):
            r['ok'] = False
            r['reason'] = 'black top screen in all shots'
            log('[w%02d] %s black' % (wid, key))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('save'); ap.add_argument('outdir')
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--only', default='')
    ap.add_argument('--classes', default='0123')
    ap.add_argument('--exe', default=EXE)
    ap.add_argument('--interp', action='store_true')
    ap.add_argument('--states', action='store_true', help='also save and load a state in every run')
    ap.add_argument('--from-results', default='')
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    items = stage_items(a.classes)
    if a.only:
        keep = set(a.only.split(','))
        items = [it for it in items if it[0] in keep]
    if a.from_results:
        old = json.load(open(a.from_results))
        bad = {k for k, v in old.items() if not v.get('ok')}
        items = [it for it in items if '%s_%d' % it in bad]
    print('%d stage/class runs on %d workers' % (len(items), a.workers), flush=True)
    lock = threading.Lock()

    def log(msg):
        with lock:
            print(msg, flush=True)
    chunks = [items[i::a.workers] for i in range(a.workers)]
    results = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_worker, i, ch, a.outdir, a.save, log, a.exe, a.interp, a.states) for i, ch in enumerate(chunks) if ch]
        for f in cf.as_completed(futs):
            results.update(f.result())
    json.dump(results, open(os.path.join(a.outdir, 'results.json'), 'w'), indent=1, sort_keys=True)
    bad = {k: v for k, v in results.items() if not v.get('ok')}
    lines = ['%d runs, %d ok, %d flagged' % (len(results), len(results) - len(bad), len(bad))]
    lines += ['%s: %s' % (k, v.get('reason')) for k, v in sorted(bad.items())]
    open(os.path.join(a.outdir, 'report.txt'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
