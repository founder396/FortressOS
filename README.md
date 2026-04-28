# Fortress SDK & Tools

Official Open-Source repository for the **Fortress Protocol** ecosystem.
This repository contains reference clients, daemons, and SDKs to integrate with the Fortress Sovereign Architecture.

## Components Included

- **fortress-detect**: Basic SDK for detecting Fortress AI watermarks and cryptographic survivability across PHP, Python, and TypeScript.
- **fortress-scrapling-daemon**: A lightweight Python-based daemon utilizing Scrapling for sovereign data extraction.
- **fortress-telegram-daemon**: A scanner and monitoring tool for continuous field tracking.

## License

This project is dual-licensed:
- **Core SDK (`fortress-detect`)**: Apache License 2.0 (See `LICENSE-APACHE`)
- **Crawlers and Daemons**: MIT License (See `LICENSE-MIT`)

This structure allows maximum permissiveness for developer adoption of our crawler tools, while maintaining industry-standard patent protections (via Apache 2.0) for the core SDK.

## Getting Started
Please refer to the README inside each component's directory for specific installation and usage instructions.

**Note:** No proprietary keys, backend infrastructure secrets, or private models are included in this repository. All provided tools are purely client-side references or stand-alone open source utilities.
