import pytest
from nodiq.api.server import app, store


def test_public_verification_and_certified_pdf_download():
    """Verify that public auditors/users can verify a report hash and download the certified PDF."""
    client = app.test_client()

    v_hash = "a" * 64
    report_record = {
        "id": "RPT-TEST-VERIFY-1",
        "sample_id": "HEAT-TEST-001",
        "analysis_type": "nodularity_iso_945",
        "created_at": "2026-11-01T20:00:00",
        "verification_hash": v_hash,
        "verification": {
            "sha256_fingerprint": v_hash,
            "manifest": {"source_image_sha256": "b" * 64}
        },
        "full_report": {
            "report_id": "RPT-TEST-VERIFY-1",
            "report_meta": {"report_kind": "nodularity_iso_945"},
            "sample_information": {
                "sample_id": "HEAT-TEST-001",
                "operator": "Dr. Quality Inspector"
            },
            "summary": {
                "nodularity_pct": 85.5,
                "verdict": "ACCEPT"
            },
            "mechanical_properties": {
                "available": True,
                "acceptance_verdict": {
                    "overall_status": "COMPLIANT",
                    "confidence_score": 0.95
                }
            },
            "verification": {
                "sha256_fingerprint": v_hash
            }
        }
    }

    # Insert report into store
    store.insert_report(report_record, user_id=None)

    # 1. Unauthenticated verification lookup
    verify_resp = client.get(f"/api/verify/{v_hash}")
    assert verify_resp.status_code == 200
    payload = verify_resp.get_json()
    assert payload["verified"] is True
    assert payload["sha256_fingerprint"] == v_hash
    assert "pdf_download_url" in payload

    # 2. Unauthenticated certified PDF download via returned URL
    dl_url = payload["pdf_download_url"]
    dl_resp = client.get(dl_url)
    assert dl_resp.status_code == 200
    assert dl_resp.headers["Content-Type"] == "application/pdf"
    assert dl_resp.data.startswith(b"%PDF")
    assert len(dl_resp.data) > 500

    # 3. Direct route via /api/verify/<hash>/pdf
    direct_resp = client.get(f"/api/verify/{v_hash}/pdf")
    assert direct_resp.status_code == 200
    assert direct_resp.headers["Content-Type"] == "application/pdf"
    assert direct_resp.data.startswith(b"%PDF")

    # 4. Unknown hash returns 404
    bad_resp = client.get("/api/verify/0000000000000000000000000000000000000000000000000000000000000000/pdf")
    assert bad_resp.status_code == 404
