/**
 * Fortress Swarm Police — report client (Apache-2.0). Submits a leak finding to the bounty API.
 * Protocol contract: SWARM_PROTOCOL.md. The settlement/reward backend is operated by Fortress/OHM.
 */
'use strict';

const DEFAULT_API = process.env.FORTRESS_SWARM_API || 'https://api.fortress.ohm/swarm/v1';

/**
 * Report a detected leak for a bounty.
 * @param {{code:string, sourceUrl:string, finderDid:string, evidence?:object, api?:string}} finding
 * @returns {Promise<object>} server result: { status, microReward?, litigationId?, reason? }
 *   status ∈ PENDING_EXTRACTION | VERIFIED_LEAK | REJECTED_SPOOF | DUPLICATE_REPLAY
 */
async function report(finding) {
  if (!finding || !finding.code || !finding.finderDid) throw new Error('report() needs { code, sourceUrl, finderDid }');
  const api = finding.api || DEFAULT_API;
  const body = {
    code: finding.code, sourceUrl: finding.sourceUrl || null,
    finderDid: finding.finderDid, evidence: finding.evidence || null,
    reportedAt: new Date().toISOString(),
  };
  const res = await fetch(api + '/report', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) return { status: 'ERROR', httpStatus: res.status };
  return res.json();
}

module.exports = { report, DEFAULT_API };
