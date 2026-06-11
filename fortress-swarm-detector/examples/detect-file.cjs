#!/usr/bin/env node
/**
 * Example detector (Apache-2.0): detect a Fortress mark in an image file.
 * Usage: node examples/detect-file.cjs <image> [--merchant did:...]
 * Requires ffmpeg on PATH (decode to gray) + @fortress/provenance-sdk installed.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { detect } = require('../detector.cjs');

const W = 1024;
const file = process.argv[2];
const mi = process.argv.indexOf('--merchant');
const merchant = mi >= 0 ? process.argv[mi + 1] : undefined;
if (!file) { console.log('usage: node examples/detect-file.cjs <image> [--merchant did:...]'); process.exit(1); }

function toGray(f) {
  const out = path.join(os.tmpdir(), 'fdet_' + Date.now() + '.gray');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', f, '-vf', `scale=${W}:${W}`, '-pix_fmt', 'gray', '-f', 'rawvideo', out], { stdio: ['ignore', 'ignore', 'inherit'] });
  const b = fs.readFileSync(out); fs.unlinkSync(out);
  return new Float64Array(Uint8ClampedArray.from(b.subarray(0, W * W)));
}

(async () => {
  const r = await detect(toGray(file), { merchant });
  if (r.found) console.log(`✓ Fortress mark FOUND\n  code: ${r.code}\n  via:  ${r.via}\n  → report via swarm-client.cjs to claim the bounty`);
  else console.log('✗ no Fortress mark detected (clean, or too degraded / AI-regenerated)');
  process.exit(0);
})();
