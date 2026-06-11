# Swarm Police — Report Protocol (open spec)
> The contract any community detector follows to submit a leak finding for a bounty.
> Backend (settlement, rewards, litigation) is operated by Fortress/OHM. v1.

## Flow
1. Detector finds a Fortress mark in suspect media → `detect()` → `{ found, code }`.
2. Detector POSTs a report → `POST {api}/swarm/v1/report`.
3. Backend extracts/verifies server-side, runs anti-fraud, returns a status.
4. First valid finder gets an instant micro-reward + a tracker for **15%** of downstream legal recovery.

## Request
```json
POST /swarm/v1/report
{ "code": "ABC123", "sourceUrl": "https://pirate.example/x", "finderDid": "did:finder:42",
  "evidence": { "screenshotHash": "sha256:…", "seenAt": "2026-06-11T…Z" },
  "reportedAt": "2026-06-11T…Z" }
```
## Response
```json
{ "status": "VERIFIED_LEAK", "microReward": 50, "litigationId": "FW-LIT-PENDING-00042" }
```
`status` ∈ `PENDING_EXTRACTION` · `VERIFIED_LEAK` · `REJECTED_SPOOF` · `DUPLICATE_REPLAY` · `ERROR`.

## Anti-fraud rules (enforced server-side)
- **Perceptual pre-filter** — junk/spam dropped before extraction.
- **Replay / double-dip** — a `code` already claimed → `DUPLICATE_REPLAY`, no reward.
- **False-Accusation-Burn** — a report whose payload lacks the valid POAW signature → `REJECTED_SPOOF` + the `finderDid`'s stake is slashed. Report honestly; spoofing costs you.
- **Stake-to-report** — finders may need to stake to submit (prevents extortion rings).

## Honesty (Rule 9)
A detector must not assert ownership or "uncrackable"; it reports presence + the public CODE. Owner
resolution and any legal action are the platform's/Fortress's server-side responsibility.
