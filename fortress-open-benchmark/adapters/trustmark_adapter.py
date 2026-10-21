#!/usr/bin/env python3
"""TrustMark (Adobe, open source, neural) adapter: model Q, BCH_5, text mode (5 characters = 40 payload bits),
as in the original private measurement. Needs `pip install trustmark` (the package fetches/caches its own weights).
Honours BENCH_THREADS (torch intra-op threads) for single-thread normalisation. Persistent `serve` mode comes from
the template, so the model is loaded once."""
import os, random, string, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from template_adapter import main

INFO = dict(name='trustmark', version='0.9.1', payload_bits=40, task='resilient',
            notes='Q model, BCH_5, text mode, 5 chars; payload_bits requested by the harness is ignored (fixed 40)')
TM = None


def init(extra):
    global TM
    import torch
    from trustmark import TrustMark
    if os.environ.get('BENCH_THREADS'): torch.set_num_threads(int(os.environ['BENCH_THREADS']))
    TM = TrustMark(verbose=False, model_type='Q', encoding_type=TrustMark.Encoding.BCH_5)


def embed(inp, out, payload_bits, seed):
    from PIL import Image
    text = ''.join(random.Random(seed).choice(string.ascii_lowercase + string.digits) for _ in range(5))
    TM.encode(Image.open(inp).convert('RGB'), text, MODE='text').convert('RGB').save(out)
    return dict(payload=text.encode().hex(), payload_bits=40)


def extract(inp):
    from PIL import Image
    secret, present, _ = TM.decode(Image.open(inp).convert('RGB'), MODE='text')
    return (True, secret.encode().hex()) if present else (False, None)


if __name__ == '__main__':
    main(INFO, embed, extract, init)
