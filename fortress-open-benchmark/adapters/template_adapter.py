#!/usr/bin/env python3
"""Adapter skeleton for the open watermark benchmark (MIT). Copy this file, fill in the two functions, done.
It gives you the whole contract (embed / extract / info / serve) so you only write the watermark part.

Contract (details in ../ADAPTER_SPEC.md):
  embed   --in a.png --out b.png --payload-bits N --seed S   -> {"ok":true,"payload":"<hex>"}
  extract --in b.png                                          -> {"found":bool,"payload":"<hex>"|null}
  info                                                        -> {"name","version","payload_bits","task","notes"}
  serve   (optional) JSON lines on stdin/stdout, prints {"ready":true} once models are loaded.
Rules: stdout carries ONLY the JSON line (library prints are redirected to stderr here);
exit code != 0 = failure = counted as a miss. Extra command-line flags (e.g. --profile) reach init() as a list.
"""
import argparse, json, sys

REAL_OUT = sys.stdout  # keep the real stdout for JSON; anything printed by libraries goes to stderr
sys.stdout = sys.stderr


def emit(obj):
    REAL_OUT.write(json.dumps(obj) + '\n'); REAL_OUT.flush()


def main(info, embed, extract, init=None):
    """embed(in_path, out_path, payload_bits, seed) -> dict with "payload" (hex) [, "payload_bits"]
       extract(in_path) -> (found: bool, payload_hex or None)
       init(extra_args: list) -> None, called once before any operation (load models here)."""
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['embed', 'extract', 'info', 'serve'])
    ap.add_argument('--in', dest='inp'); ap.add_argument('--out'); ap.add_argument('--payload-bits', type=int, default=0); ap.add_argument('--seed', type=int, default=0)
    a, extra = ap.parse_known_args()
    if a.cmd == 'info': return emit(info)
    if init: init(extra)

    def do(op, inp, out=None, bits=0, seed=0):
        if op == 'embed': return dict(ok=True, **embed(inp, out, bits, seed))
        f, p = extract(inp); return dict(found=bool(f), payload=p if f else None)

    if a.cmd == 'serve':
        emit(dict(ready=True))
        for line in sys.stdin:
            q = json.loads(line)
            if q['op'] == 'quit': break
            try: emit(do(q['op'], q['in'], q.get('out'), q.get('payload_bits', 0), q.get('seed', 0)))
            except Exception as e: emit(dict(ok=False, found=False, error=str(e)[:200]))
        return
    emit(do(a.cmd, a.inp, a.out, a.payload_bits, a.seed))  # an exception here -> non-zero exit -> counted as a miss


# ---- fill these in ----
INFO = dict(name='my-tool', version='0.0', payload_bits=32, task='other', notes='template: does nothing')


def my_embed(in_path, out_path, payload_bits, seed):
    raise NotImplementedError('write your embedder')   # save the marked image to out_path (PNG), return {"payload": hex}


def my_extract(in_path):
    raise NotImplementedError('write your extractor')  # return (found, payload_hex)


if __name__ == '__main__':
    main(INFO, my_embed, my_extract)
