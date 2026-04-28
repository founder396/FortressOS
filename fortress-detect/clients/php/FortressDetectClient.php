<?php
/**
 * @fortress/detect — PHP SDK
 * PHP 8.1+ required (uses enums and readonly properties)
 * Zero dependencies — uses only PHP built-in cURL extension.
 *
 * Apache-2.0 License — Patent Retaliation Clause applies.
 * © 2026 Hagen Schmidt / destill.ai
 *
 * Install via Composer:
 *   composer require fortress/detect
 *
 * Quick start:
 *   $client = FortressDetectClient::fromEnv();
 *   $result = $client->detectUrl('https://example.com/image.jpg');
 *   if ($result->detected) {
 *       echo "Creator: " . $result->payload->creatorIdHash;
 *   }
 */

declare(strict_types=1);

namespace Fortress\Detect;

// ─── Enums ───────────────────────────────────────────────────────────────────

enum Quadrant: string {
    case SHIELD   = 'Q1_SHIELD';
    case MONETIZE = 'Q2_MONETIZE';
    case COMMERCE = 'Q3_COMMERCE';
    case LICENSE  = 'Q4_LICENSE';
    case ANTIDOTE = 'Q5_ANTIDOTE';
}

enum LicenseStatus: string {
    case AUTHORIZED   = 'authorized';
    case UNAUTHORIZED = 'unauthorized';
    case LICENSED     = 'licensed';
    case UNLICENSED   = 'unlicensed';
}

// ─── DTOs ────────────────────────────────────────────────────────────────────

final class WatermarkPayload {
    public function __construct(
        public readonly string    $creatorIdHash,
        public readonly string    $sku,
        public readonly string    $embeddedAt,
        public readonly Quadrant  $quadrant,
        public readonly ?string   $buyerIdHash = null,
    ) {}
}

final class ForensicReceipt {
    public function __construct(
        public readonly string $receiptHash,
        public readonly string $poawChainId,
        public readonly string $timestamp,
        public readonly bool   $isCourtAdmissible,
    ) {}
}

final class LicenseInfo {
    public function __construct(
        public readonly LicenseStatus $status,
        public readonly ?string       $resolutionUrl = null,
    ) {}
}

final class DetectionResult {
    public function __construct(
        public readonly bool              $detected,
        public readonly float             $confidence,
        public readonly int               $processingMs,
        public readonly ?WatermarkPayload $payload         = null,
        public readonly ?ForensicReceipt  $forensicReceipt = null,
        public readonly ?float            $psnrScore       = null,
        public readonly ?int              $generationSurvival = null,
        public readonly ?LicenseInfo      $licenseInfo     = null,
    ) {}
}

final class BatchJob {
    public function __construct(
        public readonly string $jobId,
        public readonly string $statusUrl,
    ) {}
}

// ─── Exception ───────────────────────────────────────────────────────────────

final class FortressDetectException extends \RuntimeException {
    public function __construct(public readonly int $statusCode, string $message) {
        parent::__construct("[Fortress Detect] HTTP {$statusCode}: {$message}");
    }
}

// ─── Client ──────────────────────────────────────────────────────────────────

final class FortressDetectClient {
    private const SDK_VERSION  = '1.0.0';
    private const DEFAULT_BASE = 'https://fortress.destill.ai/api/v1';

    public function __construct(
        private readonly string $apiKey,
        private readonly string $hmacSecret,
        private readonly string $baseUrl   = self::DEFAULT_BASE,
        private readonly int    $timeoutS  = 30,
    ) {}

    public static function fromEnv(): self {
        $apiKey     = getenv('FORTRESS_API_KEY')     ?: throw new \InvalidArgumentException('FORTRESS_API_KEY not set');
        $hmacSecret = getenv('FORTRESS_HMAC_SECRET') ?: throw new \InvalidArgumentException('FORTRESS_HMAC_SECRET not set');
        $baseUrl    = getenv('FORTRESS_BASE_URL') ?: self::DEFAULT_BASE;
        return new self($apiKey, $hmacSecret, $baseUrl);
    }

    /**
     * Detect a DWT watermark from a local image file path.
     */
    public function detectFile(string $filePath, string $sensitivity = 'medium'): DetectionResult {
        if (!is_readable($filePath)) {
            throw new \InvalidArgumentException("File not readable: {$filePath}");
        }
        $curlFile = new \CURLFile($filePath, $this->mimeFromPath($filePath), basename($filePath));
        $raw = $this->request('POST', '/detect/image', [
            'file'        => $curlFile,
            'sensitivity' => $sensitivity,
        ], multipart: true);
        return $this->parseDetection($raw);
    }

    /**
     * Detect a DWT watermark from a public image URL.
     */
    public function detectUrl(string $url, string $sensitivity = 'medium'): DetectionResult {
        $raw = $this->request('POST', '/detect/url', [
            'url'         => $url,
            'sensitivity' => $sensitivity,
        ]);
        return $this->parseDetection($raw);
    }

    /**
     * Submit a batch of up to 50 URLs.
     */
    public function detectBatch(array $urls, ?string $webhookUrl = null): BatchJob {
        if (count($urls) > 50) {
            throw new \InvalidArgumentException('Batch limit is 50 URLs per request.');
        }
        $payload = ['urls' => array_values($urls)];
        if ($webhookUrl !== null) {
            $payload['webhook_url'] = $webhookUrl;
        }
        $raw = $this->request('POST', '/detect/batch', $payload);
        return new BatchJob($raw['job_id'], $raw['status_url']);
    }

    /**
     * Poll a batch job status.
     */
    public function getBatchStatus(string $jobId): array {
        return $this->request('GET', '/detect/batch/' . urlencode($jobId));
    }

    /**
     * Verify a POAW forensic receipt for legal use.
     */
    public function verifyPoaw(string $receiptHash, string $signature): array {
        return $this->request('POST', '/verify/poaw', [
            'receipt_hash' => $receiptHash,
            'signature'    => $signature,
        ]);
    }

    // ─── Private ─────────────────────────────────────────────────────────

    private function signedKey(): string {
        $timestamp = (string) time();
        $message   = "{$this->apiKey}.{$timestamp}";
        $sig       = hash_hmac('sha256', $message, $this->hmacSecret);
        return "{$this->apiKey}.{$timestamp}.{$sig}";
    }

    private function request(string $method, string $path, array $body = [], bool $multipart = false): array {
        $ch = curl_init($this->baseUrl . $path);
        $headers = [
            'X-Fortress-Key: ' . $this->signedKey(),
            'X-Fortress-SDK-Version: ' . self::SDK_VERSION,
            'Accept: application/json',
        ];

        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => $this->timeoutS,
            CURLOPT_FOLLOWLOCATION => false,
        ]);

        if ($method === 'POST') {
            curl_setopt($ch, CURLOPT_POST, true);
            if ($multipart) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
                // cURL sets multipart/form-data automatically
            } else {
                $json = json_encode($body, JSON_THROW_ON_ERROR);
                curl_setopt($ch, CURLOPT_POSTFIELDS, $json);
                $headers[] = 'Content-Type: application/json';
                $headers[] = 'Content-Length: ' . strlen($json);
            }
        }

        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

        $responseBody = curl_exec($ch);
        $statusCode   = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curlError    = curl_error($ch);
        curl_close($ch);

        if ($curlError) {
            throw new FortressDetectException(0, "cURL error: {$curlError}");
        }

        $data = json_decode((string) $responseBody, associative: true, flags: JSON_THROW_ON_ERROR);

        if ($statusCode < 200 || $statusCode >= 300) {
            $msg = $data['error'] ?? $responseBody;
            throw new FortressDetectException($statusCode, (string) $msg);
        }

        return $data;
    }

    private function parseDetection(array $raw): DetectionResult {
        $payload = null;
        if (!empty($raw['payload'])) {
            $p = $raw['payload'];
            $payload = new WatermarkPayload(
                creatorIdHash: $p['creator_id_hash'],
                sku:           $p['sku'],
                embeddedAt:    $p['embedded_at'],
                quadrant:      Quadrant::from($p['quadrant']),
                buyerIdHash:   $p['buyer_id_hash'] ?? null,
            );
        }

        $receipt = null;
        if (!empty($raw['forensic_receipt'])) {
            $r = $raw['forensic_receipt'];
            $receipt = new ForensicReceipt(
                receiptHash:       $r['receipt_hash'],
                poawChainId:       $r['poaw_chain_id'],
                timestamp:         $r['timestamp'],
                isCourtAdmissible: (bool) $r['is_court_admissible'],
            );
        }

        $licenseInfo = null;
        if (!empty($raw['license_info'])) {
            $li = $raw['license_info'];
            $licenseInfo = new LicenseInfo(
                status:        LicenseStatus::from($li['status']),
                resolutionUrl: $li['resolution_url'] ?? null,
            );
        }

        return new DetectionResult(
            detected:           (bool) $raw['detected'],
            confidence:         (float) $raw['confidence'],
            processingMs:       (int) $raw['processing_ms'],
            payload:            $payload,
            forensicReceipt:    $receipt,
            psnrScore:          isset($raw['psnr_score']) ? (float) $raw['psnr_score'] : null,
            generationSurvival: $raw['generation_survival'] ?? null,
            licenseInfo:        $licenseInfo,
        );
    }

    private function mimeFromPath(string $path): string {
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        return match($ext) {
            'jpg', 'jpeg' => 'image/jpeg',
            'png'         => 'image/png',
            'webp'        => 'image/webp',
            'tiff', 'tif' => 'image/tiff',
            default       => 'application/octet-stream',
        };
    }
}
