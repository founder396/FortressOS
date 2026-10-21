#!/usr/bin/env python3
"""Open watermark benchmark harness (MIT). Vendor-neutral: any tool that speaks the tiny adapter contract
(see ADAPTER_SPEC.md) gets the same three, never-fused axes:
  1. energy / compute per operation   2. robustness per attack   3. false hits on unmarked images
plus pixel distortion (PSNR - NOT visibility).

  python harness.py --photos <dir> --adapter adapters/lsb_example_adapter.py --out run1
"""
import argparse, glob, hashlib, io, json, multiprocessing, os, platform, queue, re, shlex, statistics, subprocess
import sys, tempfile, threading, time
import numpy as np
from PIL import Image, ImageFilter
import psutil

VERSION = '0.1.0'


# ---------------------------------------------------------------- attacks (table: add rows to extend)
def _jpeg(q):
    def f(im):
        b = io.BytesIO(); im.save(b, 'JPEG', quality=q); b.seek(0); return Image.open(b).convert(im.mode)
    return f


def _crop10(im):  # centre crop 5 % per side, rescaled back to the original size (the EASY crop case)
    w, h = im.size; m = int(w * .05); return im.crop((m, m, w - m, h - m)).resize((w, h), Image.BICUBIC)


ATTACKS = {  # name: (function, extended_only)
    'none':     (lambda im: im, False),
    'jpeg90':   (_jpeg(90), False),
    'jpeg75':   (_jpeg(75), False),
    'jpeg50':   (_jpeg(50), False),
    'resize75': (lambda im: im.resize((int(im.size[0] * .75), int(im.size[1] * .75)), Image.BICUBIC), False),
    'crop10':   (_crop10, False),
    'rotate3':  (lambda im: im.rotate(3, resample=Image.BICUBIC, fillcolor=(0, 0, 0)), True),
    'screenshot_like': (lambda im: _jpeg(70)(im.filter(ImageFilter.GaussianBlur(1.0))), True),  # blur + jpeg70
}


def psnr(a, b):
    """Pixel distortion over all RGB channels. NOT visibility."""
    a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64); mse = np.mean((a - b) ** 2)
    return 99.0 if mse == 0 else float(10 * np.log10(255 ** 2 / mse))


# ---------------------------------------------------------------- photos
def prepare_photos(src, size, n_max, dst):
    """Centre-crop square, resize to size, save PNG into dst. Refuses < 8. Never copies photos into the package."""
    os.makedirs(dst, exist_ok=True); out = []; hashes = []
    files = set()
    for e in ('jpg', 'jpeg', 'png', 'tif', 'tiff', 'bmp'):
        for f in os.listdir(src):
            if f.lower().endswith('.' + e): files.add(os.path.join(src, f))
    for f in sorted(files):
        try: im = Image.open(f).convert('RGB')
        except Exception: continue
        w, h = im.size
        if min(w, h) < size: continue  # no upscaling: it would fake detail
        s = min(w, h); l, t = (w - s) // 2, (h - s) // 2
        im = im.crop((l, t, l + s, t + s)).resize((size, size), Image.LANCZOS)
        p = os.path.join(dst, f'{len(out):02d}.png'); im.save(p); out.append(p)
        hashes.append(hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16])
        if len(out) >= n_max: break
    if len(out) < 8:
        sys.exit(f'refusing to run: only {len(out)} usable photos (short side >= {size} px) in {src}; need at least 8')
    return out, hashes


# ---------------------------------------------------------------- power meters
class PowerMeter:
    """start() ... stop() -> (mean_watts or None, n_samples). This base class is the `none` meter."""
    name = 'none'
    def available(self): return False
    def start(self): pass
    def stop(self): return None, 0


class WindowsTypeperf(PowerMeter):
    """\\Energy Meter(CPU Power)\\Power via typeperf (milliwatts). Do NOT use the 'Apu Power' counter:
    it is a flat budget value on the reference machine (unchanged under all-core load)."""
    name = 'windows'
    COUNTER = '\\Energy Meter(CPU Power)\\Power'
    def available(self): return os.name == 'nt'
    def start(self):
        self.path = tempfile.mktemp(suffix='.csv')
        self.p = subprocess.Popen(['typeperf', self.COUNTER, '-si', '1', '-o', self.path, '-y'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
    def stop(self):
        self.p.terminate(); time.sleep(0.6); v = []
        try:
            for r in open(self.path, encoding='utf-8', errors='ignore').read().strip().splitlines()[1:]:
                try: v.append(float(r.split(',')[1].strip('"')) / 1000.0)
                except Exception: pass
            os.remove(self.path)
        except OSError: pass
        v = v[2:]  # drop warm-up samples
        return (statistics.mean(v), len(v)) if v else (None, 0)


class LinuxRapl(PowerMeter):
    """/sys/class/powercap/intel-rapl*/energy_uj (Intel and AMD). Sums the package domains, handles counter wrap.
    Usually needs root or relaxed permissions on energy_uj."""
    name = 'rapl'
    def __init__(self):
        self.doms = [d for d in glob.glob('/sys/class/powercap/intel-rapl*') if re.search(r'intel-rapl:\d+$', d)]
    def _read(self): return [int(open(d + '/energy_uj').read()) for d in self.doms]
    def available(self):
        try: return bool(self.doms) and bool(self._read())
        except OSError: return False
    def start(self): self.e0 = self._read(); self.t0 = time.time()
    def stop(self):
        e1 = self._read(); dt = time.time() - self.t0; tot = 0
        for d, a, b in zip(self.doms, self.e0, e1):
            if b < a: b += int(open(d + '/max_energy_range_uj').read())  # counter wrapped
            tot += b - a
        return (tot / 1e6 / dt, int(dt)) if dt > 0 else (None, 0)


def make_meter(kind):
    if kind == 'auto': kind = 'windows' if os.name == 'nt' else 'rapl'
    meter = {'none': PowerMeter, 'windows': WindowsTypeperf, 'rapl': LinuxRapl}[kind]()
    if kind != 'none' and not meter.available():
        print(f'power meter "{kind}" not available here -> reporting CPU-seconds only'); return PowerMeter()
    return meter


def _burn(deadline):
    x = 0
    while time.time() < deadline: x += 1


def meter_self_check(meter, burn_s=10, idle_s=6):
    """Refuse joules unless an all-core burn raises the counter by >= 3 W over idle."""
    meter.start(); time.sleep(idle_s); idle, _ = meter.stop()
    meter.start(); dl = time.time() + burn_s
    ps = [multiprocessing.Process(target=_burn, args=(dl,)) for _ in range(os.cpu_count())]
    [p.start() for p in ps]; [p.join() for p in ps]; burn, _ = meter.stop()
    if idle is None or burn is None:
        print('power meter not informative, reporting CPU-seconds only'); return dict(ok=False, reason='no samples')
    rise = burn - idle; ok = rise >= 3.0
    if not ok: print('power meter not informative, reporting CPU-seconds only')
    return dict(ok=ok, idle_w=round(idle, 2), burn_w=round(burn, 2), rise_w=round(rise, 2))


# ---------------------------------------------------------------- adapter wrapper (one-shot or persistent serve)
def _win_cpu_times(handle):
    """kernel + user seconds of a (finished) child via its still-open handle."""
    import ctypes
    from ctypes import wintypes
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    if not ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(int(handle)), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
        return None
    t = lambda f: ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7
    return t(k) + t(u)


class Adapter:
    def __init__(self, spec, mode, timeout, env):
        # spec = path to the adapter, or "path extra args" (extras are appended to every call)
        self.spec = spec
        toks = [spec] if os.path.exists(spec) else shlex.split(spec)
        script, self.extra = toks[0], toks[1:]
        ext = os.path.splitext(script)[1]
        self.base = [sys.executable, script] if ext == '.py' else ['node', script] if ext in ('.cjs', '.js', '.mjs') else [script]
        self.label = os.path.basename(script) + (' ' + ' '.join(self.extra) if self.extra else '')
        self.timeout, self.env, self.want = timeout, env, mode
        self.proc = None; self.serve = False; self.load_s = None; self.restarts = 0; self.cpu_done = 0.0; self.mode = 'oneshot'

    def _oneshot(self, args):
        t0 = time.perf_counter()
        try:
            import resource; r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        except ImportError: resource = None
        p = subprocess.Popen(self.base + args + self.extra, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self.env)
        try: out, _ = p.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired: p.kill(); out = b''; p.returncode = -9
        wall = time.perf_counter() - t0; cpu = None
        if os.name == 'nt':
            try: cpu = _win_cpu_times(p._handle)  # direct child only; grandchildren are not counted
            except Exception: cpu = None
        elif resource:
            r1 = resource.getrusage(resource.RUSAGE_CHILDREN); cpu = (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)
        self.cpu_done += cpu or 0
        return self._parse(out.decode(errors='ignore'), p.returncode), wall

    @staticmethod
    def _parse(text, rc):
        if rc != 0: return dict(ok=False, error=f'exit code {rc}')
        for line in reversed(text.strip().splitlines()):
            try: return json.loads(line)
            except Exception: continue
        return dict(ok=False, error='no JSON on stdout')

    def start(self):
        """Try serve mode (unless one-shot is forced); model-load time = time until {"ready":true}."""
        if self.want != 'oneshot':
            t0 = time.perf_counter()
            self.proc = subprocess.Popen(self.base + ['serve'] + self.extra, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=self.env, text=True, bufsize=1)
            self.q = queue.Queue()
            threading.Thread(target=lambda p=self.proc, q=self.q: [q.put(l) for l in p.stdout], daemon=True).start()
            try: self.serve = bool(json.loads(self.q.get(timeout=self.timeout)).get('ready'))
            except Exception: self.serve = False
            if self.serve:
                if self.load_s is None: self.load_s = time.perf_counter() - t0
            else:
                self.proc.kill(); self.proc = None
                if self.want == 'serve': sys.exit(f'{self.label}: serve mode requested but not supported')
        self.mode = 'serve' if self.serve else 'oneshot'

    def cpu_total(self):
        """Cumulative CPU seconds: process tree (serve) plus finished/replaced processes. A child that exits
        between two readings is lost (documented limitation)."""
        t = self.cpu_done
        if self.serve:
            try:
                p = psutil.Process(self.proc.pid)
                for q in [p] + p.children(recursive=True):
                    try: c = q.cpu_times(); t += c.user + c.system
                    except psutil.Error: pass
            except psutil.Error: pass
        return t

    def call(self, op, **kw):
        """-> (response dict, wall seconds). Any failure comes back as ok:false / no `found`."""
        if not self.serve:
            return self._oneshot([op] + sum(([f'--{k.replace("_", "-")}', str(v)] for k, v in kw.items()), []))
        t0 = time.perf_counter()
        try:
            self.proc.stdin.write(json.dumps(dict(op=op, **kw)) + '\n'); self.proc.stdin.flush()
            r = json.loads(self.q.get(timeout=self.timeout))
        except Exception as e:  # dead or hung: bank its CPU, kill, restart; this call counts as a failure
            self.cpu_done = self.cpu_total(); self.proc.kill(); self.restarts += 1
            r = dict(ok=False, error=f'serve failure: {type(e).__name__}'); self.serve = False; self.start()
        return r, time.perf_counter() - t0

    def info(self):
        r, _ = self._oneshot(['info']); return r if r.get('name') else dict(name=self.label, payload_bits=None)

    def close(self):
        if self.proc:
            try: self.proc.stdin.write('{"op":"quit"}\n'); self.proc.stdin.flush(); self.proc.wait(5)
            except Exception: self.proc.kill()


# ---------------------------------------------------------------- measurement phases
def hit(emb, resp):
    return bool(resp.get('found')) and str(resp.get('payload') or '').lower() == str(emb).lower()


def loop(ad, op, items, seconds):
    """Cycle `op` over items for >= `seconds` (at least one op). -> ops, wall, cpu_s_per_op."""
    c0 = ad.cpu_total(); t0 = time.perf_counter(); n = 0
    while n == 0 or time.perf_counter() - t0 < seconds:
        ad.call(op, **items[n % len(items)]); n += 1
    return n, time.perf_counter() - t0, (ad.cpu_total() - c0) / n


def measure_adapter(ad, photos, work, a):
    ad.start(); R = dict(label=ad.label, mode=ad.mode, load_s=None if ad.load_s is None else round(ad.load_s, 2), info=ad.info())
    bits = a.payload_bits or R['info'].get('payload_bits') or 32
    att = {k: v[0] for k, v in ATTACKS.items() if a.extended or not v[1]}
    wd = os.path.join(work, re.sub(r'\W+', '_', ad.label)); os.makedirs(wd, exist_ok=True)
    # 1. embed (timed first pass) + PSNR
    marked, payloads, ps, ems, fails = {}, {}, [], [], 0
    for k, p in enumerate(photos):
        out = os.path.join(wd, f'm{k:02d}.png')
        r, w = ad.call('embed', **{'in': p, 'out': out, 'payload_bits': bits, 'seed': a.seed + k})
        if r.get('ok') and os.path.exists(out):
            marked[k] = out; payloads[k] = r.get('payload'); ems.append(w * 1000)
            ps.append(psnr(Image.open(p).convert('RGB'), Image.open(out).convert('RGB')))
            R['payload_bits_actual'] = r.get('payload_bits') or len(str(r.get('payload'))) * 4
        else: fails += 1
    R['embed'] = dict(n=len(photos), failed=fails)
    R['psnr_db'] = dict(median=round(statistics.median(ps), 1) if ps else None, min=round(min(ps), 1) if ps else None, note='pixel distortion, NOT visibility')
    # 2. robustness: attack the marked image, extract, compare payload. A failed embed is a miss.
    R['robustness'] = {}
    for name, fn in att.items():
        hits = wrong = 0
        for k in marked:
            ap = os.path.join(wd, f'a{k:02d}-{name}.png'); fn(Image.open(marked[k]).convert('RGB')).save(ap)
            r, _ = ad.call('extract', **{'in': ap})
            if hit(payloads[k], r): hits += 1
            elif r.get('found'): wrong += 1
        R['robustness'][name] = dict(hits=hits, n=len(photos), found_wrong_payload=wrong)
    # 3. unmarked control: ANY found counts as a false hit
    R['control'] = dict(false_hits=sum(1 for p in photos if ad.call('extract', **{'in': p})[0].get('found')), n=len(photos))
    # 4. energy / compute loop
    R['energy'] = {}
    if not a.no_energy and marked:
        arms = dict(embed=[{'in': photos[k], 'out': os.path.join(wd, 'loop.png'), 'payload_bits': bits, 'seed': a.seed + k} for k in marked],
                    extract=[{'in': marked[k]} for k in marked])
        use_meter = a.meter.name != 'none' and a.meter_ok
        for op, items in arms.items():
            for i in range(3): ad.call(op, **items[i % len(items)])  # warm-up
            runs = []
            for rep in range(a.reps):
                pi = pr = None
                if use_meter:
                    a.meter.start(); time.sleep(a.idle_seconds); pi, _ = a.meter.stop(); a.idle_samples.append(pi)
                    a.meter.start()
                n, wall, cpu = loop(ad, op, items, a.seconds)
                if use_meter: pr, _ = a.meter.stop()
                net = (pr - pi) if (pr is not None and pi is not None) else None
                runs.append(dict(rep=rep, ops=n, wall_s=round(wall, 2), ms_per_op=round(wall * 1000 / n, 2), cpu_s_per_op=round(cpu, 4),
                                 p_idle_w=None if pi is None else round(pi, 2), p_run_w=None if pr is None else round(pr, 2),
                                 net_w=None if net is None else round(net, 2), mj_per_op_net=None if net is None else round(net * wall / n * 1000, 1)))
                print('  ', ad.label, op, runs[-1], flush=True)
            R['energy'][op] = runs
    # 5. when a persistent process was used: what one per-process call costs (includes model load)
    if ad.serve and not a.no_energy and marked:
        ad2 = Adapter(ad.spec, 'oneshot', ad.timeout, ad.env); k = next(iter(marked)); t = []
        for i in range(3): t.append(ad2._oneshot(['extract', '--in', marked[k]])[1] * 1000)
        R['oneshot_extract_ms_median'] = round(statistics.median(t))
    ad.close(); R['restarts'] = ad.restarts
    return R


# ---------------------------------------------------------------- report
def report(res):
    pw, A = res['power'], res['adapters']; c = res['config']
    L = ['# Open watermark benchmark report', '',
         f"Harness {res['harness_version']}, {res['date']}, {res['machine']['cpu']} ({res['machine']['logical_cpus']} logical CPUs"
         f"{', adapter pinned to ' + str(c['cpu_affinity']) if c['cpu_affinity'] else ''}), {res['photos']['n']} photos at {res['photos']['size']} px.", '',
         'Three axes, deliberately never fused into one score. No tool is declared a winner; read each table on its own and read the limitations in README.md.', '',
         '## Axis 1 - Energy / compute per operation', '']
    if pw['meter'] == 'none' or not (pw.get('self_check') or {}).get('ok'):
        L += [f"Power meter: **not used** ({pw.get('why') or 'none'}). CPU-seconds only - a work metric, not joules.", '']
    else:
        L += [f"Power meter: `{pw['meter']}` (self-check: idle {pw['self_check']['idle_w']} W, all-core burn {pw['self_check']['burn_w']} W). "
              f"Idle noise floor (std of idle baselines): **{pw['noise_floor_w']} W**; a net power below 2x that is flagged. Net energy = (P_run - P_idle) x wall / ops.", '']
    L += ['| tool | op | mode | ms/op | CPU-s/op | net W (median) | mJ/op net (median, min-max) | flag |', '|---|---|---|---|---|---|---|---|']
    for r in A:
        for op, runs in r['energy'].items():
            med = lambda key: statistics.median(x[key] for x in runs)
            mj = [x['mj_per_op_net'] for x in runs if x['mj_per_op_net'] is not None]; nets = [x['net_w'] for x in runs if x['net_w'] is not None]
            if mj:
                nf = pw.get('noise_floor_w'); low = nf is None or statistics.median(nets) < 2 * nf
                e = f"{statistics.median(nets):.2f} | {statistics.median(mj):.0f} ({min(mj):.0f}-{max(mj):.0f}) | {'BELOW NOISE FLOOR: treat joules as unmeasured' if low else ''}"
            else: e = 'n/a | n/a | CPU-seconds only'
            L.append(f"| {r['label']} | {op} | {r['mode']} | {med('ms_per_op'):.1f} | {med('cpu_s_per_op'):.3f} | {e} |")
    L += ['', '| tool | mode | model/process load (s, time to ready) | one-shot extract incl. load (ms) |', '|---|---|---|---|']
    for r in A: L.append(f"| {r['label']} | {r['mode']} | {r['load_s'] if r['load_s'] is not None else 'n/a'} | {r.get('oneshot_extract_ms_median', 'n/a')} |")
    L += ['', 'The energy loop measures only the operation loop, not model load; load is reported separately above.']
    if c['cpu_affinity']: L.append(f"Adapter pinned to {c['cpu_affinity']} logical CPU(s) (`BENCH_THREADS` passed to the adapter): thread-count differences show up in CPU-s/op.")
    L += ['', '## Axis 2 - Robustness per attack', '',
          'Hit = payload read back identical to what `embed` reported, after the attack. n = number of photos; a failed embed is a miss. `wrong` = something was found but the payload differed (counted as a miss).', '',
          '| attack | ' + ' | '.join(r['label'] for r in A) + ' |', '|---|' + '---|' * len(A)]
    for n in (A[0]['robustness'] if A else []):
        L.append(f'| {n} | ' + ' | '.join(f"{r['robustness'][n]['hits']}/{r['robustness'][n]['n']}" + (f" (wrong {r['robustness'][n]['found_wrong_payload']})" if r['robustness'][n]['found_wrong_payload'] else '') for r in A) + ' |')
    L += ['', '## Axis 3 - False hits on unmarked images', '', '| tool | false hits (any `found:true` on an unmarked original) |', '|---|---|']
    for r in A: L.append(f"| {r['label']} | {r['control']['false_hits']}/{r['control']['n']} |")
    L += ['', f"n = {res['photos']['n']} gives only a loose bound: 0 false hits in n trials is consistent with a true rate up to about {3 / max(res['photos']['n'], 1):.0%} (rule of three, 95 %).",
          '', '## Pixel distortion (PSNR - NOT visibility)', '', '| tool | median dB | min dB | payload bits | embed failures |', '|---|---|---|---|---|']
    for r in A: L.append(f"| {r['label']} | {r['psnr_db']['median']} | {r['psnr_db']['min']} | {r.get('payload_bits_actual', 'n/a')} | {r['embed']['failed']}/{r['embed']['n']} |")
    L += ['', 'PSNR is an average pixel error; it cannot show a local blemish. Payload sizes differ between tools, so robustness rows are not like-for-like.']
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--photos', required=True); ap.add_argument('--adapter', action='append', required=True, help='adapter path, or "path --extra args"; repeatable')
    ap.add_argument('--out', default='results'); ap.add_argument('--size', type=int, default=1024); ap.add_argument('--n', type=int, default=12)
    ap.add_argument('--payload-bits', type=int, default=0, help="0 = the adapter's own default"); ap.add_argument('--seed', type=int, default=1000)
    ap.add_argument('--extended', action='store_true', help='also rotate3 and screenshot_like'); ap.add_argument('--mode', default='auto', choices=['auto', 'serve', 'oneshot'])
    ap.add_argument('--seconds', type=int, default=40); ap.add_argument('--reps', type=int, default=3); ap.add_argument('--idle-seconds', type=int, default=12)
    ap.add_argument('--power', default='auto', choices=['auto', 'windows', 'rapl', 'none']); ap.add_argument('--cpu-affinity', type=int, default=0)
    ap.add_argument('--no-energy', action='store_true'); ap.add_argument('--timeout', type=int, default=600)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True); work = os.path.join(a.out, 'work')
    photos, hashes = prepare_photos(a.photos, a.size, a.n, os.path.join(work, 'photos'))
    a.meter = make_meter(a.power); a.meter_ok = False; a.idle_samples = []
    power = dict(meter=a.meter.name, why='power none' if a.meter.name == 'none' else '')
    if a.meter.name != 'none' and not a.no_energy:  # self-check BEFORE pinning, so the burn can use all cores
        power['self_check'] = meter_self_check(a.meter); a.meter_ok = power['self_check']['ok']
        if not a.meter_ok: power['why'] = 'self-check failed: counter did not rise by >= 3 W under an all-core burn'
    env = dict(os.environ)
    if a.cpu_affinity:
        psutil.Process().cpu_affinity(list(range(a.cpu_affinity))); env['BENCH_THREADS'] = str(a.cpu_affinity)  # children inherit the pin
    res = dict(harness_version=VERSION, date=time.strftime('%Y-%m-%d %H:%M'),
               machine=dict(cpu=platform.processor(), logical_cpus=os.cpu_count(), os=platform.platform(), python=platform.python_version()),
               config=dict(size=a.size, seconds=a.seconds, reps=a.reps, idle_seconds=a.idle_seconds, extended=a.extended, cpu_affinity=a.cpu_affinity, mode=a.mode, seed=a.seed),
               photos=dict(n=len(photos), size=a.size, source_sha256_16=hashes), power=power, adapters=[])
    for spec in a.adapter:
        print('==', spec, flush=True); res['adapters'].append(measure_adapter(Adapter(spec, a.mode, a.timeout, env), photos, work, a))
    power['noise_floor_w'] = round(statistics.stdev(a.idle_samples), 2) if len(a.idle_samples) >= 2 else None
    if a.meter_ok and power['noise_floor_w'] is None: power['why'] = 'fewer than 2 idle baselines: noise floor unknown, joules flagged'
    json.dump(res, open(os.path.join(a.out, 'results.json'), 'w'), indent=1)
    open(os.path.join(a.out, 'report.md'), 'w', encoding='utf-8').write(report(res))
    print(report(res))


if __name__ == '__main__':
    multiprocessing.freeze_support(); main()
