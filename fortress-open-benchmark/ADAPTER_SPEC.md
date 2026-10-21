# Adapter contract (v0.1)

An adapter is any executable that answers three sub-commands on the command line. It may be written in any language.
The harness starts it as `python x.py`, `node x.cjs`, or directly (any other extension). Extra flags given with
`--adapter "path --profile foo"` are appended to every call.

Rules for all commands: **stdout carries exactly one JSON line** (anything else goes to stderr). **Exit code != 0 is a failure and is counted as a miss** (a failed `embed` is a miss in every robustness row; a failed `extract` is "not found").

## embed

```
<adapter> embed --in <png> --out <png> --payload-bits <int> --seed <int>
-> {"ok":true,"payload":"<hex>"}            optional: "payload_bits": <int actually used>
```

- Read the PNG `--in` (8-bit RGB), write the marked image as PNG to `--out`.
- `--seed` makes the payload (or the key) deterministic per image. `--payload-bits` is a request; if your tool has a fixed payload, ignore it and report the real size in `payload_bits`. Different payload sizes make robustness rows not like-for-like; the report prints the actual bits.
- `payload` is whatever `extract` will return when the mark is read back intact (hex string; for a key-based tool, the key).

## extract

```
<adapter> extract --in <png>
-> {"found":true,"payload":"<hex>"}   or   {"found":false,"payload":null}
```

- The harness counts a **hit** only if `found` is true **and** `payload` equals the one `embed` returned (case-insensitive).
- On an **unmarked** image any `"found":true` is a **false hit** (axis 3), whatever the payload.
- Extract must not need side information from `embed` beyond the image (no sidecar files, no passing the key in). If your tool needs a key, derive it from `--seed` inside the adapter or fix it per adapter, and say so in `notes`.

## info (optional)

```
<adapter> info
-> {"name":"...","version":"...","payload_bits":<int>,"task":"resilient|fragile|other","notes":"..."}
```

`payload_bits` is used as the default request for `embed`. `task` is a label only; the harness never ranks tools by it. A *fragile* (tamper-evidence) tool should say so; it has no counterpart in the robustness table (a fragile mark is supposed to break).

## serve (optional, persistent mode)

Neural tools load a model for seconds; paying that on every call would measure the loader, not the tool. So an adapter may offer:

```
<adapter> serve
```

- It loads whatever it needs, then prints `{"ready":true}` (one line).
- Then it reads one JSON request per line on stdin and answers with exactly one JSON line on stdout:
  `{"op":"embed","in":"a.png","out":"b.png","payload_bits":40,"seed":7}` -> same answer as `embed`;
  `{"op":"extract","in":"b.png"}` -> same answer as `extract`; `{"op":"quit"}` -> exit.
- On an error it answers `{"ok":false,"found":false,"error":"..."}` and keeps running.

### What the harness does with the two modes

| | per-process (`--mode oneshot`) | persistent (`serve`, default when offered) |
|---|---|---|
| every call | new process, model load included | one process, model loaded once |
| robustness / false-hit runs | same results (the contract is the same) | same |
| energy loop | measures load + op | **measures only the operation loop** |
| CPU-seconds | CPU time of the finished child process | CPU time of the adapter's process tree, read before/after the loop |

With `--mode auto` the harness uses `serve` if the adapter answers it and falls back to per-process otherwise. When serve is used it reports **both**: the time until `{"ready":true}` (model/process load) and, as a probe, the median wall time of three per-process `extract` calls (which include the load). Nothing is hidden by choosing one.

## Environment variables the harness sets

- `BENCH_THREADS=<N>` when `--cpu-affinity N` is used: the adapter process is pinned to N logical CPUs; adapters that control their own thread pool (torch, OpenMP) should honour this so the pin is not fought by oversubscription. The reference TrustMark adapter does. Whether an adapter honours it is visible in the CPU-seconds, which is the point.

## Writing one

Copy `adapters/template_adapter.py` (Python, ~50 lines of contract plumbing already done; you write `embed` and `extract`) or follow the same shape in any language. `adapters/lsb_example_adapter.py` is a complete working example (intentionally weak).
