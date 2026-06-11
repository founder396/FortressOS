#!/usr/bin/env node
/**
 * Skeleton community crawler-bot (Apache-2.0). YOU supply the target list + respect each site's
 * robots.txt / ToS / your jurisdiction's law. This shows the shape: fetch → decode → detect → report.
 * Not run by default; fill in fetchSuspectImages() and your finderDid.
 */
'use strict';
const { detect } = require('../detector.cjs');
const { report } = require('../swarm-client.cjs');

const FINDER_DID = process.env.FINDER_DID || 'did:finder:CHANGE_ME';

// YOU implement this: return [{ url, grayImage1024 }] from your (lawful) crawl targets.
async function fetchSuspectImages() { return []; /* community-supplied */ }

(async () => {
  const suspects = await fetchSuspectImages();
  for (const s of suspects) {
    try {
      const r = await detect(s.grayImage1024);
      if (r.found) {
        const res = await report({ code: r.code, sourceUrl: s.url, finderDid: FINDER_DID });
        console.log(`leak @ ${s.url} → ${r.code} → ${res.status}${res.microReward ? ' (+' + res.microReward + ')' : ''}`);
      }
    } catch (e) { console.error('skip', s.url, e.message); }
  }
})();
