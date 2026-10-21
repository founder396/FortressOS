#!/usr/bin/env python3
"""INTENTIONALLY WEAK example: a least-significant-bit "watermark" in the red channel (16-bit magic + 8-bit length + payload).
It exists to test the harness end to end and to show the null result honestly: it survives the lossless
copy and nothing else (JPEG, resize, crop all destroy the LSBs). It is not a serious watermark."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
from template_adapter import main

MAGIC = 0xA55A
INFO = dict(name='lsb-example', version='1.0', payload_bits=32, task='other', notes='intentionally weak LSB baseline (red channel)')


def bits(v, n): return [(v >> (n - 1 - i)) & 1 for i in range(n)]


def embed(inp, out, payload_bits, seed):
    n = min(payload_bits or 32, 64)
    payload = random.Random(seed).getrandbits(n)
    a = np.array(Image.open(inp).convert('RGB')); flat = a[..., 0].reshape(-1).copy()
    seq = np.array(bits(MAGIC, 16) + bits(n, 8) + bits(payload, n), dtype=np.uint8)
    flat[:len(seq)] = (flat[:len(seq)] & 0xFE) | seq
    a[..., 0] = flat.reshape(a.shape[:2]); Image.fromarray(a).save(out)  # PNG is lossless
    return dict(payload=f'{payload:0{(n + 3) // 4}x}', payload_bits=n)


def extract(inp):
    flat = np.array(Image.open(inp).convert('RGB'))[..., 0].reshape(-1) & 1
    val = lambda s, n: int(''.join(map(str, flat[s:s + n])), 2)
    if val(0, 16) != MAGIC: return False, None
    n = val(16, 8)
    if not 1 <= n <= 64: return False, None
    return True, f'{val(24, n):0{(n + 3) // 4}x}'


if __name__ == '__main__':
    main(INFO, embed, extract)
