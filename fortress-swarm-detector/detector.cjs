/**
 * Fortress Detector (Open Source, Apache-2.0) — detect a Fortress watermark in suspect media.
 * Wraps the public extraction API of @fortress/provenance-sdk. Detection only: reports whether a
 * mark is present + its public CODE. Does NOT derive owners or forge keys (that stays commercial).
 *
 * Community detectors (crawlers/bots/extensions) call detect() on a canonical 1024² grayscale image,
 * then report finds via swarm-client.cjs for a bounty. See README.md / SWARM_PROTOCOL.md.
 */
'use strict';
// The extraction engine is the public, validated provenance SDK (install separately).
// Detector wrapper is Apache-2.0; the SDK it calls is BUSL-1.1.
let FortressProvenance;
try { ({ FortressProvenance } = require('@fortress/provenance-sdk')); }
catch { /* allow require for docs/tests without the SDK installed */ }

/**
 * Detect a Fortress resilient mark in a 1024² grayscale image (Float64Array/Uint8 length 1024*1024).
 * @param {object} gray canonical grayscale
 * @param {{merchant?:string}} [opts] merchant DID the content was protected under (defaults to generic)
 * @returns {Promise<{found:boolean, code:string|null, via:string|null}>}
 */
async function detect(gray, opts) {
  if (!FortressProvenance) throw new Error('Install @fortress/provenance-sdk to run the detector.');
  const fp = new FortressProvenance({ merchant: (opts && opts.merchant) || 'did:ohm:fortress' });
  // Adaptive extraction covers both the invisible (stealth) and robust (crop-hardened) profiles.
  const r = fp.extractImageAdaptive(gray);
  return { found: !!r.found, code: r.found ? (r.keyHex || null) : null, via: r.via || r.profile || null };
}

module.exports = { detect };
