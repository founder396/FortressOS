# fortress-swarm-detector

The **Swarm Police** layer: turn "I found a leak" into a signed report and a bounty. Build crawlers,
bots, and extensions that detect Fortress watermarks and submit findings to the Fortress bounty API.

> Apache-2.0 (see repo `LICENSE-APACHE`). Detection only — it reports whether a Fortress mark is
> present and its public CODE. It cannot forge marks or resolve owners (that stays server-side /
> commercial). More detectors = more leak-tracing coverage.

## Two ways to detect
1. **Hosted API** (no local engine needed) — use the sibling `fortress-detect` clients (PHP/Python/TS,
   `openapi.yaml` → `/detect/image`, `/detect/url`, `/detect/batch`). Best for most contributors.
2. **Local engine** (`detector.cjs`) — runs extraction on-device via `@fortress_os/provenance-sdk`
   (resilient watermark, validated v1.0). Use when you don't want to send media to the API.

## The bounty (Swarm Police)
First valid finder of a leak → instant micro-reward + a tracker for **15% of any downstream legal
recovery**. Anti-fraud: stake-to-report, replay/double-dip prevention, False-Accusation-Burn for
spoofed reports. Protocol: [`SWARM_PROTOCOL.md`](./SWARM_PROTOCOL.md).

## Quickstart
```bash
node examples/detect-file.cjs suspect.png          # local-engine detect (needs the SDK + ffmpeg)
```
```js
const { detect } = require('./detector.cjs');       // local engine
const { report } = require('./swarm-client.cjs');   // bounty client (works with either detect path)
const r = await detect(grayImage1024);
if (r.found) await report({ code: r.code, sourceUrl, finderDid });
```

## Honest survivability (v1.0, reproducible, $0/offline)
Fortress resilient marks survive — on **real photos** — JPEG/recolor/resize **100%**, crop **96–100%**,
0 false positives; video through **H.264/HEVC/VP9/AV1**; audio through **MP3/AAC/Opus/Vorbis**.
They do **not** survive full AI re-generation (information-theoretic — that's the *authenticity*
product, not a defect). Detection confidence drops as a leaked copy gets more degraded. No "uncrackable" claims.

## Status
`@fortress_os/provenance-sdk` (the local engine) publishes from the Fortress org; until then, use the
hosted-API path (`fortress-detect`) or request access. The swarm **protocol + report client** here
work today against the bounty API.
