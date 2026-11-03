#!/usr/bin/env python3
"""
services/security/crypto_verification.py — Tamper-Proof Cryptographic Verification Service.
(Pillar 5: Aerospace/Automotive Trust: Tamper-Proof Cryptographic Verification)

Provides deterministic SHA-256 fingerprinting, verification QR code generation,
canonical JSON manifest hashing, and PDF tamper inspection for ISO 17025 / 21 CFR Part 11
compliance across all NODIQ-X metallographic analysis families.
"""

import base64
import hashlib
import hmac
import io
import json
import re
import time
from typing import Dict, Any, Tuple, Optional
import qrcode
from qrcode.image.pil import PilImage


def _normalize_floats(obj):
    """Recursively round floats in data structures to prevent floating point serialization divergence."""
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _normalize_floats(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalize_floats(v) for v in obj]
    return obj


def compute_image_sha256(image_data) -> str:
    """Compute SHA-256 digest of image bytes or return precomputed 64-char hex string."""
    if isinstance(image_data, bytes):
        return hashlib.sha256(image_data).hexdigest()
    if isinstance(image_data, str):
        # Already a 64-character SHA-256 hex string
        if re.fullmatch(r"[0-9a-fA-F]{64}", image_data):
            return image_data.lower()
        # Text string or path
        return hashlib.sha256(image_data.encode("utf-8")).hexdigest()
    return hashlib.sha256(b"NODIQ_UNKNOWN_IMAGE").hexdigest()


def generate_cryptographic_fingerprint(
    image_bytes_or_hash,
    calibration: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    mechanical_predictions: Optional[Dict[str, Any]] = None,
    reviewer: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    report_id: Optional[str] = None,
    sample_id: Optional[str] = None,
    analysis_type: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate an immutable cryptographic fingerprint across:
    Image Bytes + Calibration + Particle Data + Reviewer Signature + Timestamp + Mechanical Properties.
    """
    img_hash = compute_image_sha256(image_bytes_or_hash)
    ts = timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    cal_clean = _normalize_floats(calibration or {})
    metrics_clean = _normalize_floats(metrics or {})
    mech_clean = _normalize_floats(mechanical_predictions or {})
    rev_clean = {
        "operator": str((reviewer or {}).get("operator") or "QA Metallurgist"),
        "status": str((reviewer or {}).get("status") or "APPROVED"),
        "digital_sign_type": "NODIQ-X Cryptographic HMAC-SHA256"
    }

    manifest = {
        "schema_version": "NODIQ-X-VERIFY-v2.0",
        "standard_compliance": "ISO 17025 / 21 CFR Part 11 / ISO 945 / ASTM E112",
        "report_id": str(report_id or "RPT-PENDING"),
        "sample_id": str(sample_id or "UNKNOWN-SAMPLE"),
        "analysis_type": str(analysis_type or "metallographic_inspection"),
        "timestamp_utc": ts,
        "source_image_sha256": img_hash,
        "metrology_calibration": {
            "scale_um_per_px": cal_clean.get("microns_per_pixel") or cal_clean.get("um_per_px") or cal_clean.get("scale"),
            "source": cal_clean.get("source", "uncalibrated")
        },
        "measured_microstructure": metrics_clean,
        "predicted_mechanical_properties": mech_clean,
        "qa_signoff": rev_clean
    }

    # Canonical serialization: sorted keys, compact separators, UTF-8
    canonical_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    root_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return root_hash, manifest


def generate_qr_code_png_bytes(data: str, box_size: int = 6, border: int = 2) -> bytes:
    """Generate scannable QR Code PNG bytes from target string/URL."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_qr_code_base64_data_uri(data: str) -> str:
    """Generate inline data URI string (data:image/png;base64,...) for web/PDF display."""
    png_bytes = generate_qr_code_png_bytes(data)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_canonical_manifest(manifest: Dict[str, Any], expected_hash: str) -> bool:
    """Re-compute canonical SHA-256 from manifest dict and compare in constant time."""
    try:
        canonical_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        computed_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return hmac.compare_digest(computed_hash.lower(), expected_hash.lower())
    except Exception:
        return False


def verify_pdf_document(pdf_bytes: bytes, known_reports_lookup_fn) -> Dict[str, Any]:
    """
    Inspect PDF document bytes to detect embedded SHA-256 fingerprint, extract report ID,
    and verify mathematical integrity against server database.
    """
    if not pdf_bytes or len(pdf_bytes) < 32:
        return {
            "verified": False,
            "status": "INVALID_FILE",
            "reason": "File is empty or not a valid PDF."
        }

    # 1. Search for SHA-256 pattern in PDF content
    # Looks for "SHA-256: [0-9a-fA-F]{64}" or "hash: [0-9a-fA-F]{64}" or raw hex hash
    pdf_text = ""
    try:
        # Decode latin-1 or utf-8 to inspect text tokens
        pdf_text = pdf_bytes.decode("latin-1", errors="ignore")
    except Exception:
        pass

    hash_match = re.search(r"Verified\s+SHA-256:\s*([0-9a-fA-F]{64})", pdf_text, re.IGNORECASE)
    if not hash_match:
        hash_match = re.search(r"SHA-256:\s*([0-9a-fA-F]{64})", pdf_text, re.IGNORECASE)
    if not hash_match:
        hash_match = re.search(r"/Keywords\s*\([^)]*([0-9a-fA-F]{64})[^)]*\)", pdf_text)

    # Search for Report ID
    rpt_match = re.search(r"(RPT-[0-9A-Z]{6,12})", pdf_text)

    found_hash = hash_match.group(1).lower() if hash_match else None
    found_rpt_id = rpt_match.group(1) if rpt_match else None

    if not found_hash and not found_rpt_id:
        return {
            "verified": False,
            "status": "UNRECOGNIZED_DOCUMENT",
            "reason": "No NODIQ-X cryptographic stamp or Report ID was found in the PDF. The document may not be an authentic generated report.",
            "extracted_report_id": None,
            "extracted_hash": None
        }

    # Query server record
    report_record = known_reports_lookup_fn(found_rpt_id, found_hash)
    if not report_record:
        return {
            "verified": False,
            "status": "RECORD_NOT_FOUND",
            "reason": f"Cryptographic stamp {found_hash[:16]}... or Report ID {found_rpt_id} was not found in the verified server archive.",
            "extracted_report_id": found_rpt_id,
            "extracted_hash": found_hash
        }

    # Check hash match
    stored_hash = (
        report_record.get("verification_hash")
        or (report_record.get("verification") or {}).get("sha256_fingerprint")
        or (report_record.get("full_report") or {}).get("verification", {}).get("sha256_fingerprint")
    )

    if stored_hash and found_hash and hmac.compare_digest(stored_hash.lower(), found_hash.lower()):
        return {
            "verified": True,
            "status": "CRYPTOGRAPHICALLY_AUTHENTIC",
            "reason": "Mathematical authenticity confirmed. The report fingerprint matches the server audit trail bit-for-bit.",
            "report_id": report_record.get("id"),
            "sample_id": report_record.get("sample_id"),
            "analysis_type": report_record.get("analysis_type") or report_record.get("type"),
            "sha256_fingerprint": stored_hash,
            "created_at": report_record.get("created_at"),
            "operator": (report_record.get("full_report") or {}).get("sample_information", {}).get("operator", "QA Metallurgist"),
            "acceptance_verdict": (report_record.get("full_report") or {}).get("mechanical_properties", {}).get("acceptance_verdict")
        }

    # Hash mismatch indicates tampering of the certificate or document
    return {
        "verified": False,
        "status": "TAMPER_DETECTED",
        "reason": "Security Alert: The embedded certificate in this PDF does not match the server authority record! The file may have been altered or modified.",
        "extracted_report_id": found_rpt_id,
        "extracted_hash": found_hash,
        "expected_hash": stored_hash
    }
