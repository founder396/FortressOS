"""
@fortress/detect — Python SDK
Language: Python 3.9+ (no external dependencies beyond stdlib + httpx optional)

Uses only stdlib `urllib` by default. Zero required dependencies.
Install httpx for async support: pip install httpx

Apache-2.0 License — Patent Retaliation Clause applies.
© 2026 Hagen Schmidt / destill.ai
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import BinaryIO, Literal, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# ─── Enums & Types ────────────────────────────────────────────────────────────

class Quadrant(str, Enum):
    SHIELD = "Q1_SHIELD"
    MONETIZE = "Q2_MONETIZE"
    COMMERCE = "Q3_COMMERCE"
    LICENSE = "Q4_LICENSE"
    ANTIDOTE = "Q5_ANTIDOTE"


class LicenseStatus(str, Enum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    LICENSED = "licensed"
    UNLICENSED = "unlicensed"


@dataclass
class WatermarkPayload:
    creator_id_hash: str
    sku: str
    embedded_at: str
    quadrant: Quadrant
    buyer_id_hash: Optional[str] = None


@dataclass
class ForensicReceipt:
    receipt_hash: str
    poaw_chain_id: str
    timestamp: str
    is_court_admissible: bool


@dataclass
class LicenseInfo:
    status: LicenseStatus
    resolution_url: Optional[str] = None


@dataclass
class DetectionResult:
    detected: bool
    confidence: float
    processing_ms: int
    payload: Optional[WatermarkPayload] = None
    forensic_receipt: Optional[ForensicReceipt] = None
    psnr_score: Optional[float] = None
    generation_survival: Optional[int] = None
    license_info: Optional[LicenseInfo] = None


@dataclass
class BatchJob:
    job_id: str
    status_url: str


# ─── Exception ────────────────────────────────────────────────────────────────

class FortressDetectError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"[Fortress Detect] HTTP {status_code}: {message}")
        self.status_code = status_code


# ─── Client ──────────────────────────────────────────────────────────────────

class FortressDetectClient:
    """
    Python client for the Fortress Detect API.

    Example usage:
        client = FortressDetectClient.from_env()
        result = client.detect_url("https://example.com/stolen-image.jpg")
        if result.detected:
            print(f"Creator: {result.payload.creator_id_hash}")
            print(f"License: {result.license_info.status}")
    """

    DEFAULT_BASE_URL = "https://fortress.destill.ai/api/v1"

    def __init__(
        self,
        api_key: str,
        hmac_secret: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 30.0,
    ):
        self._api_key = api_key
        self._hmac_secret = hmac_secret.encode()
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> "FortressDetectClient":
        """
        Create client from environment variables.
        Required: FORTRESS_API_KEY, FORTRESS_HMAC_SECRET
        Optional: FORTRESS_BASE_URL
        """
        api_key = os.environ.get("FORTRESS_API_KEY")
        hmac_secret = os.environ.get("FORTRESS_HMAC_SECRET")
        if not api_key or not hmac_secret:
            raise ValueError(
                "Missing environment variables: "
                "FORTRESS_API_KEY and FORTRESS_HMAC_SECRET are required."
            )
        return cls(
            api_key=api_key,
            hmac_secret=hmac_secret,
            base_url=os.environ.get("FORTRESS_BASE_URL", cls.DEFAULT_BASE_URL),
        )

    def detect_file(
        self,
        file: BinaryIO,
        filename: str,
        sensitivity: Literal["low", "medium", "high"] = "medium",
    ) -> DetectionResult:
        """
        Detect a DWT watermark from an image file.

        Args:
            file: File-like object opened in binary mode.
            filename: Filename for MIME type detection.
            sensitivity: Extraction sensitivity.

        Returns:
            DetectionResult with payload and forensic receipt if watermark found.
        """
        data = file.read()
        boundary = "fortress_boundary_8675309"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {self._mime_from_filename(filename)}\r\n\r\n"
        ).encode() + data + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="sensitivity"\r\n\r\n'
            f"{sensitivity}\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        raw = self._request(
            path="/detect/image",
            method="POST",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return self._parse_detection(raw)

    def detect_url(
        self,
        url: str,
        sensitivity: Literal["low", "medium", "high"] = "medium",
    ) -> DetectionResult:
        """
        Detect a DWT watermark from a publicly accessible image URL.

        Example:
            result = client.detect_url("https://example.com/image.jpg")
        """
        raw = self._request(
            path="/detect/url",
            method="POST",
            body=json.dumps({"url": url, "sensitivity": sensitivity}).encode(),
            content_type="application/json",
        )
        return self._parse_detection(raw)

    def detect_batch(
        self,
        urls: list[str],
        webhook_url: Optional[str] = None,
    ) -> BatchJob:
        """
        Submit a batch of up to 50 URLs for async processing.
        Poll with get_batch_status(job.job_id) or provide a webhook_url.
        """
        if len(urls) > 50:
            raise ValueError("Batch limit is 50 URLs per request.")
        payload = {"urls": urls}
        if webhook_url:
            payload["webhook_url"] = webhook_url
        raw = self._request(
            path="/detect/batch",
            method="POST",
            body=json.dumps(payload).encode(),
            content_type="application/json",
        )
        return BatchJob(**raw)

    def get_batch_status(self, job_id: str) -> dict:
        """Poll the status of a previously submitted batch job."""
        return self._request(
            path=f"/detect/batch/{job_id}",
            method="GET",
        )

    def verify_poaw(self, receipt_hash: str, signature: str) -> dict:
        """
        Verify a POAW forensic receipt for legal use.
        Returns validity, creator hash, and chain position.
        """
        return self._request(
            path="/verify/poaw",
            method="POST",
            body=json.dumps({"receipt_hash": receipt_hash, "signature": signature}).encode(),
            content_type="application/json",
        )

    # ─── Internal ─────────────────────────────────────────────────────────

    def _signed_key(self) -> str:
        """Generate HMAC-signed API key. Replay window: ±30 seconds."""
        timestamp = str(int(time.time()))
        message = f"{self._api_key}.{timestamp}".encode()
        sig = hmac.new(self._hmac_secret, message, hashlib.sha256).hexdigest()
        return f"{self._api_key}.{timestamp}.{sig}"

    def _request(
        self,
        path: str,
        method: str,
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ) -> dict:
        url = f"{self._base_url}{path}"
        headers = {
            "X-Fortress-Key": self._signed_key(),
            "X-Fortress-SDK-Version": "1.0.0",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type

        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self._timeout_s) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            body_text = e.read().decode(errors="replace")
            try:
                err = json.loads(body_text)
                msg = err.get("error", body_text)
            except json.JSONDecodeError:
                msg = body_text
            raise FortressDetectError(e.code, msg) from e

    def _parse_detection(self, raw: dict) -> DetectionResult:
        payload = None
        if raw.get("payload"):
            p = raw["payload"]
            payload = WatermarkPayload(
                creator_id_hash=p["creator_id_hash"],
                sku=p["sku"],
                embedded_at=p["embedded_at"],
                quadrant=Quadrant(p["quadrant"]),
                buyer_id_hash=p.get("buyer_id_hash"),
            )
        receipt = None
        if raw.get("forensic_receipt"):
            r = raw["forensic_receipt"]
            receipt = ForensicReceipt(**r)

        license_info = None
        if raw.get("license_info"):
            li = raw["license_info"]
            license_info = LicenseInfo(
                status=LicenseStatus(li["status"]),
                resolution_url=li.get("resolution_url"),
            )

        return DetectionResult(
            detected=raw["detected"],
            confidence=raw["confidence"],
            processing_ms=raw["processing_ms"],
            payload=payload,
            forensic_receipt=receipt,
            psnr_score=raw.get("psnr_score"),
            generation_survival=raw.get("generation_survival"),
            license_info=license_info,
        )

    @staticmethod
    def _mime_from_filename(filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower()
        return {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "tiff": "image/tiff",
            "tif": "image/tiff",
        }.get(ext, "application/octet-stream")
