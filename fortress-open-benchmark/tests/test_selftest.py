"""Self-test: can the harness express a failure? Runs it on 8 synthetic textured images with the intentionally weak LSB adapter.
Run: python tests/test_selftest.py   (no photos needed; images are generated here and deleted afterwards)"""
import json, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)


def synth(path, seed, n=320):
    """Textured image: smooth gradients + noise + a few hard edges (so JPEG/resize really change pixels)."""
    r = np.random.default_rng(seed); y, x = np.mgrid[0:n, 0:n] / n
    img = np.stack([np.sin(8 * x + seed) * 60 + 128, np.cos(6 * y + seed) * 60 + 128, (x + y) * 100 + 50], -1)
    img += r.normal(0, 12, img.shape); img[n // 3:n // 2, n // 4:n // 2] = 230
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)


def run(args):
    return subprocess.run([sys.executable, os.path.join(ROOT, 'harness.py')] + args, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    ph = os.path.join(tmp, 'photos'); os.makedirs(ph)
    for i in range(8): synth(os.path.join(ph, f'{i}.png'), i)
    out = os.path.join(tmp, 'out')
    p = run(['--photos', ph, '--adapter', os.path.join(ROOT, 'adapters', 'lsb_example_adapter.py'), '--size', '256', '--n', '8',
             '--seconds', '3', '--reps', '1', '--power', 'none', '--out', out])
    print(p.stdout[-2500:]); assert p.returncode == 0, p.stderr
    r = json.load(open(os.path.join(out, 'results.json'))); a = r['adapters'][0]
    # the three axes exist
    assert a['energy']['embed'] and a['energy']['extract'], 'axis 1 (energy/compute) missing'
    assert a['energy']['embed'][0]['cpu_s_per_op'] is not None
    assert set(['none', 'jpeg90', 'jpeg75', 'jpeg50', 'resize75', 'crop10']) <= set(a['robustness']), 'axis 2 (attacks) missing'
    assert a['control']['n'] == 8, 'axis 3 (control) missing'
    # sane adapter: no false hits on unmarked images
    assert a['control']['false_hits'] == 0, 'false hits on unmarked images'
    # positive control: the harness can express a PASS ...
    assert a['robustness']['none']['hits'] == 8, 'LSB must read back the lossless copy'
    # ... and a FAIL (a check that cannot report failure is not measuring)
    assert a['robustness']['jpeg75']['hits'] == 0, 'LSB must FAIL jpeg75'
    assert a['robustness']['resize75']['hits'] == 0 and a['robustness']['crop10']['hits'] == 0
    assert a['psnr_db']['median'] > 50, 'LSB changes almost no pixels'
    # report exists and says "not visibility"
    assert 'NOT visibility' in open(os.path.join(out, 'report.md'), encoding='utf-8').read()
    # fewer than 8 photos must be refused
    few = os.path.join(tmp, 'few'); os.makedirs(few)
    for i in range(5): synth(os.path.join(few, f'{i}.png'), i)
    q = run(['--photos', few, '--adapter', os.path.join(ROOT, 'adapters', 'lsb_example_adapter.py'), '--size', '256', '--power', 'none', '--out', os.path.join(tmp, 'o2')])
    assert q.returncode != 0 and 'at least 8' in (q.stderr + q.stdout), 'must refuse < 8 photos'
print('SELF-TEST PASSED: 3 axes present, 0 false hits, LSB fails jpeg75/resize75/crop10 (failure is expressible), <8 photos refused')
