/**
 * @fortress/detect — Node.js / Browser SDK
 * Language: TypeScript (compiles to CJS + ESM)
 * 
 * Uses only the fetch API — works in Node 18+, Deno, Bun, modern browsers, Cloudflare Workers.
 * Zero dependencies. The OpenAPI contract (openapi.yaml) is the authoritative spec.
 * 
 * Apache-2.0 License — Patent Retaliation Clause applies.
 * © 2026 Hagen Schmidt / destill.ai
 */

import { createHmac } from "node:crypto"; // Node only — see browser.ts for Web Crypto version

// ─── Types ───────────────────────────────────────────────────────────────────

export type Quadrant =
  | "Q1_SHIELD"
  | "Q2_MONETIZE"
  | "Q3_COMMERCE"
  | "Q4_LICENSE"
  | "Q5_ANTIDOTE";

export type Sensitivity = "low" | "medium" | "high";

export interface WatermarkPayload {
  creator_id_hash: string;
  sku: string;
  embedded_at: string; // ISO 8601
  quadrant: Quadrant;
  buyer_id_hash?: string; // Q3_COMMERCE only
}

export interface ForensicReceipt {
  receipt_hash: string;
  poaw_chain_id: string;
  timestamp: string;
  is_court_admissible: boolean;
}

export interface LicenseInfo {
  status: "authorized" | "unauthorized" | "licensed" | "unlicensed";
  resolution_url?: string;
}

export interface DetectionResult {
  detected: boolean;
  confidence: number; // 0.0 – 1.0
  payload?: WatermarkPayload;
  forensic_receipt?: ForensicReceipt;
  psnr_score?: number;
  generation_survival?: number;
  license_info?: LicenseInfo;
  processing_ms: number;
}

export interface BatchJob {
  job_id: string;
  status_url: string;
}

export interface FortressDetectConfig {
  /** Your Fortress API key.  NEVER commit this — use environment variables. */
  apiKey: string;
  /** Your HMAC signing secret. Used to generate replay-resistant request signatures. */
  hmacSecret: string;
  /** API base URL. Defaults to Fortress OPS production endpoint. */
  baseUrl?: string;
  /** Request timeout in milliseconds. Default: 30_000 */
  timeoutMs?: number;
}

// ─── Client ──────────────────────────────────────────────────────────────────

export class FortressDetectClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly hmacSecret: string;
  private readonly timeoutMs: number;

  constructor(config: FortressDetectConfig) {
    this.apiKey = config.apiKey;
    this.hmacSecret = config.hmacSecret;
    this.baseUrl = config.baseUrl ?? "https://fortress.destill.ai/api/v1";
    this.timeoutMs = config.timeoutMs ?? 30_000;
  }

  /**
   * Detect a DWT watermark from an image file.
   * 
   * @param imageData - Raw image bytes (Buffer, Uint8Array, or Blob)
   * @param filename  - Filename hint for MIME type detection
   * @param sensitivity - Extraction sensitivity (default: 'medium')
   * @returns DetectionResult with payload and forensic receipt if found
   * 
   * @example
   * ```ts
   * const result = await client.detectFile(imageBuffer, 'photo.jpg');
   * if (result.detected) {
   *   console.log('Creator:', result.payload?.creator_id_hash);
   *   console.log('License:', result.license_info?.status);
   * }
   * ```
   */
  async detectFile(
    imageData: Buffer | Uint8Array | Blob,
    filename: string,
    sensitivity: Sensitivity = "medium"
  ): Promise<DetectionResult> {
    const form = new FormData();
    const blobData: BlobPart = imageData instanceof Blob
      ? imageData
      : new Uint8Array(
          imageData instanceof Buffer
            ? imageData.buffer.slice(imageData.byteOffset, imageData.byteOffset + imageData.byteLength)
            : imageData.buffer
        );
    const blob = imageData instanceof Blob
      ? imageData
      : new Blob([blobData], { type: this._mimeFromFilename(filename) });

    form.append("file", blob, filename);
    form.append("sensitivity", sensitivity);

    return this._request<DetectionResult>("/detect/image", {
      method: "POST",
      body: form,
    });
  }

  /**
   * Detect a DWT watermark from a public URL.
   * Fortress fetches and processes the image server-side.
   * 
   * @example
   * ```ts
   * const result = await client.detectUrl('https://example.com/image.jpg');
   * ```
   */
  async detectUrl(
    url: string,
    sensitivity: Sensitivity = "medium"
  ): Promise<DetectionResult> {
    return this._request<DetectionResult>("/detect/url", {
      method: "POST",
      body: JSON.stringify({ url, sensitivity }),
      headers: { "Content-Type": "application/json" },
    });
  }

  /**
   * Submit a batch of up to 50 URLs for async processing.
   * Poll with `getBatchStatus(job.job_id)` or provide a `webhookUrl`.
   * 
   * @example
   * ```ts
   * const job = await client.detectBatch(['https://...', 'https://...']);
   * // Poll:
   * const result = await client.getBatchStatus(job.job_id);
   * ```
   */
  async detectBatch(
    urls: string[],
    webhookUrl?: string
  ): Promise<BatchJob> {
    if (urls.length > 50) {
      throw new Error("Batch limit is 50 URLs per request.");
    }
    return this._request<BatchJob>("/detect/batch", {
      method: "POST",
      body: JSON.stringify({ urls, webhook_url: webhookUrl }),
      headers: { "Content-Type": "application/json" },
    });
  }

  /**
   * Poll the status of a batch job.
   */
  async getBatchStatus(jobId: string) {
    return this._request(`/detect/batch/${encodeURIComponent(jobId)}`, {
      method: "GET",
    });
  }

  /**
   * Verify a POAW forensic receipt for legal use.
   * Returns whether the receipt is cryptographically valid and court-admissible.
   */
  async verifyPoaw(receiptHash: string, signature: string) {
    return this._request("/verify/poaw", {
      method: "POST",
      body: JSON.stringify({ receipt_hash: receiptHash, signature }),
      headers: { "Content-Type": "application/json" },
    });
  }

  // ─── Private ───────────────────────────────────────────────────────────────

  /** Generate a replay-resistant API key header value. Window: ±30 seconds. */
  private _signedKey(): string {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const message = `${this.apiKey}.${timestamp}`;
    const sig = createHmac("sha256", this.hmacSecret)
      .update(message)
      .digest("hex");
    return `${this.apiKey}.${timestamp}.${sig}`;
  }

  private async _request<T>(
    path: string,
    init: RequestInit
  ): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          "X-Fortress-Key": this._signedKey(),
          "X-Fortress-SDK-Version": "1.0.0",
          ...(init.headers ?? {}),
        },
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new FortressDetectError(res.status, (err as any).error ?? res.statusText);
      }

      return res.json() as Promise<T>;
    } finally {
      clearTimeout(timeout);
    }
  }

  private _mimeFromFilename(filename: string): string {
    const ext = filename.split(".").pop()?.toLowerCase();
    const map: Record<string, string> = {
      jpg: "image/jpeg",
      jpeg: "image/jpeg",
      png: "image/png",
      webp: "image/webp",
      tiff: "image/tiff",
      tif: "image/tiff",
    };
    return map[ext ?? ""] ?? "application/octet-stream";
  }
}

// ─── Error ────────────────────────────────────────────────────────────────────

export class FortressDetectError extends Error {
  constructor(
    public readonly statusCode: number,
    message: string
  ) {
    super(`[Fortress Detect] HTTP ${statusCode}: ${message}`);
    this.name = "FortressDetectError";
  }
}

// ─── Convenience factory ──────────────────────────────────────────────────────

/**
 * Create a FortressDetectClient from environment variables.
 * Required: FORTRESS_API_KEY, FORTRESS_HMAC_SECRET
 * Optional: FORTRESS_BASE_URL
 * 
 * @example
 * ```ts
 * const client = fromEnv();
 * const result = await client.detectUrl('https://example.com/image.jpg');
 * ```
 */
export function fromEnv(): FortressDetectClient {
  const apiKey = process.env.FORTRESS_API_KEY;
  const hmacSecret = process.env.FORTRESS_HMAC_SECRET;

  if (!apiKey || !hmacSecret) {
    throw new Error(
      "Missing environment variables: FORTRESS_API_KEY and FORTRESS_HMAC_SECRET are required."
    );
  }

  return new FortressDetectClient({
    apiKey,
    hmacSecret,
    baseUrl: process.env.FORTRESS_BASE_URL,
  });
}

export default FortressDetectClient;
