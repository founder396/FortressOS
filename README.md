# Fortress SDK & Tools

Official Open-Source repository for the **Fortress Protocol** ecosystem.
This repository contains reference clients, daemons, and SDKs to integrate with the Fortress Sovereign Architecture.

## Components Included

- **fortress-detect**: SDK for detecting Fortress watermarks via the hosted Detect API (PHP, Python, TypeScript; see `fortress-detect/openapi.yaml`).
- **fortress-swarm-detector**: The **Swarm Police** layer — a bounty protocol + report client + local-engine detector. Build crawlers/bots that find leaks and earn a finder's reward + 15% of downstream legal recovery. (Apache-2.0)
- **fortress-scrapling-daemon**: A lightweight Python-based daemon utilizing Scrapling for sovereign data extraction.
- **fortress-telegram-daemon**: A scanner and monitoring tool for continuous field tracking.
- **fortress-open-benchmark**: an open, vendor-neutral benchmark harness for image watermarking and provenance tools (energy per operation, robustness per attack, false hits on unmarked files; three axes, never fused). Bring your own tool through a small adapter. Results and method: https://fortress.destill.ai/benchmark/

## What Fortress detects (v1.0 — honest, reproducible at $0/offline)

Two invisible-watermark modes, opposite physics:
- **Resilient** (leak-tracing / provenance) — survives the distribution pipeline. On a **real photo corpus**: JPEG/recolor/resize **100%**, crop **96–100%**, **0 false positives**; video through **H.264/HEVC/VP9/AV1**; audio through **MP3/AAC/Opus/Vorbis**.
- **Fragile** (tamper-evidence / authenticity) — breaks on any edit; a bit-exact signed hash flags **any** 1-bit change.

**Stated boundaries (information-theoretic, not bugs):** full generative-AI redraw destroys resilient marks (that's *why* the fragile/authenticity product exists), heavy text paraphrase, truly-inaudible audio, blind crop+rotation combined. We publish what we can't do — no "uncrackable" claims.

## License

This project is dual-licensed:
- **Core SDK (`fortress-detect`)**: Apache License 2.0 (See `LICENSE-APACHE`)
- **Crawlers and Daemons**: MIT License (See `LICENSE-MIT`)

This structure allows maximum permissiveness for developer adoption of our crawler tools, while maintaining industry-standard patent protections (via Apache 2.0) for the core SDK.

## Getting Started
Please refer to the README inside each component's directory for specific installation and usage instructions.

**Note:** No proprietary keys, backend infrastructure secrets, or private models are included in this repository. All provided tools are purely client-side references or stand-alone open source utilities.
