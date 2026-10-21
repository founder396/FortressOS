# Open watermark benchmark

A small, vendor-neutral harness that measures **any** image-watermarking tool through a tiny adapter contract. It was built from the private measurement scripts behind the AIS26 benchmark page so that a university, a competitor or an independent lab can re-run the same measurement on their own machine and their own photos, and publish the result.

It does not rank tools and it does not produce a single score.

## The three axes, and why they are never fused

1. **Energy / compute per operation** - wall time, CPU-seconds of the adapter's process tree, and (where a power meter is informative) net joules per embed / extract.
2. **Robustness per attack** - after each attack, is the original payload read back identically? Counted per photo.
3. **False hits on unmarked images** - how often does the extractor claim a mark on a clean photo?

Plus **pixel distortion (PSNR)**, which is labelled everywhere as *not visibility*.

They are not fused because they trade against each other and a weighted sum hides which trade was made: a tool can be cheap and fragile, or heavy and robust, or robust because it fires on everything (that shows up only on axis 3). Any fused number would encode someone's weights. Read the tables side by side.

## Run it

Requirements: Python 3.10+ with `numpy`, `Pillow`, `psutil`; your own tool's dependencies.

```
python tests/test_selftest.py                      # proves the harness can report a failure (no photos needed)

python harness.py --photos <dir-of-your-photos> --out run1 \
    --adapter adapters/lsb_example_adapter.py \
    --adapter adapters/trustmark_adapter.py
```

Key options: `--size 1024` (centre-crop square then resize; photos with a shorter side are skipped, never upscaled), `--n 12` (max photos, **at least 8 required**), `--extended` (adds rotate3 and a blur+JPEG "screenshot-like" attack), `--seconds 40 --reps 3 --idle-seconds 12` (energy loop; the defaults reproduce the original protocol), `--power auto|windows|rapl|none`, `--cpu-affinity N`, `--mode auto|serve|oneshot`, `--no-energy`.

Output in `--out`: `results.json` (every run, raw), `report.md` (the three tables), `work/` (prepared photos and marked images; delete before sharing). **The package never ships photos.**

### Energy measurement

- Each repetition: an idle baseline (`--idle-seconds`, default 12 s) first, then the arm for `--seconds`. Net energy per op = (P_run - P_idle) x wall / ops. 3 repetitions.
- Power meter, pluggable (`PowerMeter` in `harness.py`): **Windows** `\Energy Meter(CPU Power)\Power` via `typeperf`; **Linux** RAPL `/sys/class/powercap/intel-rapl*/energy_uj` (Intel and AMD; usually needs root); **none**.
- Do **not** use the Windows `Apu Power` counter: on the reference machine it is a flat budget value that did not move under an all-core load.
- **Self-check before any joule is reported:** a 6 s idle and a 10 s all-core burn; if the counter does not rise by at least 3 W the harness prints `power meter not informative, reporting CPU-seconds only` and reports CPU-seconds only.
- **Noise floor** = standard deviation of all idle baselines of the run. A net power below 2x that is flagged `BELOW NOISE FLOOR` in the report. With one repetition the noise floor is unknown and everything is flagged.
- **Single-thread normalisation:** `--cpu-affinity N` pins the adapter to N logical CPUs and passes `BENCH_THREADS=N`. CPU-seconds per op then show thread-count differences (a multithreaded tool burns more CPU-seconds for the same work; a single-thread tool cannot).
- The loop measures operations only, not model load; load is reported separately (see `ADAPTER_SPEC.md`, persistent mode).

## Add your tool

Implement `embed`, `extract` (and optionally `info`, `serve`) - see `ADAPTER_SPEC.md`. In Python, copy `adapters/template_adapter.py` and fill in two functions. Run the self-test and the harness with `--adapter your_adapter.py`. Open a pull request or send the adapter: we will list it next to the others without edits to your numbers.

## How an independent body reproduces it

1. Use your own photos (>= 8, real, not generated; tell us the source type) and record `source_sha256_16` from `results.json`.
2. Install each tool yourself; adapters are thin and readable. FORTRESS requires the licensed SDK (below).
3. Run on a machine you control, note the CPU and the meter in `results.json`. Run the energy part when the machine is otherwise idle.
4. Publish `results.json` unedited. The report is generated from it.
5. If the self-check says the meter is not informative, publish CPU-seconds only; that is a valid result.

The attacks are defined in the `ATTACKS` table at the top of `harness.py` (one row per attack): none, jpeg90/75/50, resize75, crop10 (5 % per side, rescaled back), and with `--extended` rotate3 and screenshot_like. Add rows to extend.

## Known limitations (read before quoting any number)

- **Mild attacks.** No AI redraw, no screenshot of a screen, no heavy rotation or perspective. The crop attack rescales back to the original size, which is the easy case. A tool passing every row here is not shown to be robust in the wild.
- **Small n.** The reference run used n = 12 photos; the harness requires only 8. 0 false hits in 12 trials is consistent with a true rate of up to about 25 % (rule of three). Differences of one or two photos are not significant.
- **Power meter noise.** Software power counters resolve heavy multi-threaded loads and cannot resolve a single light thread (idle drifted by about 5 W on the reference machine). Joules below the noise floor are flagged, not hidden. No wall-socket meter was used.
- **No GPU arm yet.** Neural tools are measured on CPU only; a GPU number is not provided.
- **PSNR is not visibility.** It is an image-average pixel error; it cannot show a local blemish. No colour-difference (visibility) test is included.
- **Different payload sizes.** Tools carry different payloads (e.g. 128-bit key vs. 40-bit coded text). Robustness rows are not like-for-like; the report prints the actual bits.
- **Fragile seal has no counterpart.** A tamper-evident (fragile) mark is supposed to break on any edit; the robustness table does not apply to it.
- **CPU-seconds in one-shot mode** count the direct child process only (grandchildren are not counted); in persistent mode a child that exits between two readings is lost.
- One machine, one run, one photo set per published result; that is a measurement, not a law.

## Adapters

| file | what | notes |
|---|---|---|
| `adapters/template_adapter.py` | skeleton for your tool | contract plumbing done |
| `adapters/lsb_example_adapter.py` | trivial LSB watermark | **intentionally weak**; exists to test the harness and show a null result honestly |
| `adapters/trustmark_adapter.py` | TrustMark (Adobe, open source) | model Q, BCH_5, text mode, 5 characters; `pip install trustmark` |
| FORTRESS adapter | FORTRESS | **Not in this repository.** The FORTRESS SDK is licensed; the adapter that calls it is available to participants under NDA (ip@destill.ai), so the FORTRESS rows can be re-run by an independent body. Until then FORTRESS numbers are published by DESTILL.ai with raw files, labelled as such. |

## Licence

Harness and adapters: MIT (see `LICENSE`). **Photos and the FORTRESS SDK are not included** and not covered by this licence; TrustMark and any other tool keep their own licences.

## Right of reply and correction policy

Every tool measured here may be re-run by its authors. If you believe your tool was measured wrongly (adapter bug, wrong settings, unfair attack, outdated version), send the corrected adapter or the evidence: we re-run, publish the new result next to the old one, and state what changed and why. Corrections are logged, not silently overwritten. Authors of measured tools may add a short statement of their own, published unedited next to the table. Errors in this harness are fixed in the open and noted in the version history; a number that turns out to be wrong is withdrawn and marked as withdrawn.
