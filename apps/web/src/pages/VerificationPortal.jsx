import React, { useState, useEffect, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import AcceptanceVerdictMeter from "../components/common/AcceptanceVerdictMeter";
import "./VerificationPortal.css";

const DEMO_SAMPLE_HASH = "983bf5fde443ca7f007b8a174bfdccc6a5e5f45be37b582eee889d6afa779ef5";

export default function VerificationPortal() {
  const { hash: urlHash } = useParams();
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [inputHash, setInputHash] = useState(urlHash || "");
  const [loading, setLoading] = useState(false);
  const [auditResult, setAuditResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [copied, setCopied] = useState(false);

  // Auto-verify if hash is in URL
  useEffect(() => {
    if (urlHash) {
      verifyHash(urlHash);
    }
  }, [urlHash]);

  const verifyHash = async (targetHash) => {
    if (!targetHash) return;
    setLoading(true);
    setErrorMsg("");
    setDownloadError("");
    setAuditResult(null);

    try {
      const res = await fetch(`/api/verify/${encodeURIComponent(targetHash.trim())}`);
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.message || "Cryptographic certificate not found in the verified authority database.");
      } else {
        setAuditResult(data);
      }
    } catch {
      setErrorMsg("Failed to connect to the verification authority service.");
    } finally {
      setLoading(false);
    }
  };

  const handleManualSearch = (e) => {
    e.preventDefault();
    if (inputHash.trim()) {
      navigate(`/verify/${inputHash.trim()}`);
      verifyHash(inputHash.trim());
    }
  };

  const handleQuickSample = () => {
    setInputHash(DEMO_SAMPLE_HASH);
    navigate(`/verify/${DEMO_SAMPLE_HASH}`);
    verifyHash(DEMO_SAMPLE_HASH);
  };

  const handleFileUpload = async (file) => {
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
      setErrorMsg("Please upload a valid PDF document.");
      return;
    }

    setLoading(true);
    setErrorMsg("");
    setDownloadError("");
    setAuditResult(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/verify/pdf", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.reason || "The uploaded PDF document failed mathematical verification.");
      } else {
        // Fetch full verified details using the extracted hash
        if (data.sha256_fingerprint) {
          navigate(`/verify/${data.sha256_fingerprint}`);
          verifyHash(data.sha256_fingerprint);
        } else {
          setAuditResult({
            verified: true,
            status: data.status,
            report_id: data.report_id,
            sample_id: data.sample_id,
            analysis_type: data.analysis_type,
            sha256_fingerprint: data.sha256_fingerprint,
            created_at: data.created_at,
            operator: data.operator,
            pdf_download_url: `/api/verify/${data.sha256_fingerprint}/pdf`,
            mechanical_properties: {
              available: true,
              acceptance_verdict: data.acceptance_verdict,
            },
          });
        }
      }
    } catch {
      setErrorMsg("Error communicating with verification authority server.");
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handleDownloadPdf = async (e) => {
    if (e) e.preventDefault();
    if (isDownloading || !auditResult) return;

    setIsDownloading(true);
    setDownloadError("");

    try {
      const downloadEndpoint =
        auditResult.pdf_download_url ||
        `/api/verify/${encodeURIComponent(auditResult.sha256_fingerprint || "")}/pdf`;

      const response = await fetch(downloadEndpoint);
      if (!response.ok) {
        let errText = `Server responded with ${response.status}`;
        try {
          const errData = await response.json();
          errText = errData.error || errData.message || errText;
        } catch {
          // not json
        }
        throw new Error(errText);
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const downloadAnchor = document.createElement("a");
      downloadAnchor.href = objectUrl;
      const fileName = `${auditResult.report_id || "certified_report"}_verified.pdf`;
      downloadAnchor.download = fileName;
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      document.body.removeChild(downloadAnchor);
      window.URL.revokeObjectURL(objectUrl);
    } catch (err) {
      console.error("Certified PDF download failed:", err);
      setDownloadError(err.message || "Failed to download certified report PDF. Please try again.");
    } finally {
      setIsDownloading(false);
    }
  };

  const handleCopyShareLink = () => {
    const shareableUrl = `${window.location.origin}/verify/${auditResult.sha256_fingerprint || ""}`;
    navigator.clipboard.writeText(shareableUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2400);
    }).catch(() => {
      // fallback
      prompt("Copy verification link:", shareableUrl);
    });
  };

  return (
    <div className="verify-portal-page">
      <div className="verify-portal-container">
        {/* Navigation Bar */}
        <header className="verify-nav-header">
          <Link to="/" className="verify-brand-link">
            <div className="verify-brand-logo">N</div>
            <div className="verify-brand-text">
              <h1>NODIQ-X</h1>
              <span>Public Verification Authority</span>
            </div>
          </Link>

          <Link to="/login" className="verify-login-btn">
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>lock</span>
            Foundry Staff Login
          </Link>
        </header>

        {/* Hero Banner */}
        <div className="verify-hero">
          <h2>Cryptographic Certificate Verification</h2>
          <p>
            Zero-Trust Metallographic Audit Trail (ISO 17025 / 21 CFR Part 11). Verify the mathematical
            authenticity of any analysis report against raw micrograph pixels, optical calibration, and QA sign-off.
          </p>
        </div>

        {/* Drag-and-Drop Zone */}
        <div
          className={`verify-dropzone-card ${isDragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: "none" }}
            accept=".pdf,application/pdf"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                handleFileUpload(e.target.files[0]);
              }
            }}
          />
          <span className="material-symbols-outlined dropzone-icon">
            {isDragging ? "download" : "upload_file"}
          </span>
          <div className="dropzone-title">
            {isDragging ? "Drop Report PDF Here" : "Drag & Drop Report PDF to Verify"}
          </div>
          <div className="dropzone-hint">
            or click to browse from your device · Inspects cryptographic trailer for zero-tampering proof
          </div>
        </div>

        {/* Hash Search Bar */}
        <form className="verify-hash-search" onSubmit={handleManualSearch}>
          <input
            type="text"
            className="verify-hash-input"
            placeholder="Or enter 64-character SHA-256 fingerprint (e.g. 8a4fe92b...)"
            value={inputHash}
            onChange={(e) => setInputHash(e.target.value)}
          />
          <button type="submit" className="verify-hash-submit" disabled={loading}>
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              {loading ? "sync" : "search"}
            </span>
            {loading ? "Verifying…" : "Verify"}
          </button>
        </form>

        {/* Quick Sample Chip */}
        <div className="verify-quick-samples">
          <span className="quick-samples-label">Quick Sample Test:</span>
          <button
            type="button"
            className="quick-sample-chip"
            onClick={handleQuickSample}
            title="Load sample ISO 945-1 verified cast iron analysis"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>verified_user</span>
            RPT-DEMO77 (ISO 945-1 Certified)
          </button>
        </div>

        {/* Error Alert */}
        {errorMsg && (
          <div className="verify-result-card danger" style={{ marginBottom: 24 }}>
            <div className="result-status-header">
              <div className="result-status-icon danger">
                <span className="material-symbols-outlined">gpp_bad</span>
              </div>
              <div className="result-status-text">
                <h3 style={{ color: "#ef4444" }}>Verification Failed / Tamper Warning</h3>
                <p>{errorMsg}</p>
              </div>
            </div>
          </div>
        )}

        {/* Successful Audit Result */}
        {auditResult && auditResult.verified && (
          <div className="verify-result-card success">
            {/* Status Header */}
            <div className="result-status-header">
              <div className="result-status-icon success">
                <span className="material-symbols-outlined">verified</span>
              </div>
              <div className="result-status-text">
                <h3 style={{ color: "#10b981" }}>Cryptographically Authentic & Untampered</h3>
                <p>
                  Mathematical proof verified bit-for-bit against NODIQ-X server authority records.
                  Micrograph pixels, calibration, and QA metrics are intact.
                </p>
              </div>
            </div>

            {/* Core Metadata */}
            <div className="result-data-grid">
              <div className="result-data-item">
                <div className="label">Report Identifier</div>
                <div className="val">{auditResult.report_id}</div>
              </div>
              <div className="result-data-item">
                <div className="label">Sample / Heat ID</div>
                <div className="val">{auditResult.sample_id}</div>
              </div>
              <div className="result-data-item">
                <div className="label">Material Family</div>
                <div className="val">{auditResult.analysis_type}</div>
              </div>
              <div className="result-data-item">
                <div className="label">Certified By</div>
                <div className="val">{auditResult.operator || "QA Metallurgist"}</div>
              </div>
              <div className="result-data-item">
                <div className="label">Certification Date</div>
                <div className="val">{auditResult.created_at}</div>
              </div>
              <div className="result-data-item">
                <div className="label">Audit Standard</div>
                <div className="val">ISO 17025 / 21 CFR Part 11</div>
              </div>
            </div>

            {/* SHA-256 Hash Box */}
            <div className="result-hash-box">
              <div className="label">Verified SHA-256 Certificate Fingerprint:</div>
              <code>{auditResult.sha256_fingerprint}</code>
            </div>

            {/* Pillar 2: Mechanical Properties Verdict */}
            {auditResult.mechanical_properties && auditResult.mechanical_properties.available && (
              <div style={{ marginTop: 20 }}>
                <AcceptanceVerdictMeter mechanicalProperties={auditResult.mechanical_properties} />
              </div>
            )}

            {/* Action Links */}
            <div className="verify-action-footer">
              <div className="verify-action-buttons">
                <button
                  type="button"
                  className="crypto-btn-secondary"
                  onClick={handleCopyShareLink}
                  title="Copy permanent audit verification URL"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                    {copied ? "check_circle" : "share"}
                  </span>
                  {copied ? "Audit Link Copied!" : "Share Audit URL"}
                </button>

                <button
                  type="button"
                  className="crypto-btn-primary"
                  onClick={handleDownloadPdf}
                  disabled={isDownloading}
                  title="Download authentic certified PDF document"
                >
                  <span
                    className={`material-symbols-outlined ${isDownloading ? "verify-spin" : ""}`}
                    style={{ fontSize: 18 }}
                  >
                    {isDownloading ? "progress_activity" : "download"}
                  </span>
                  {isDownloading ? "Generating Certified PDF…" : "Download Certified PDF"}
                </button>
              </div>

              {downloadError && (
                <div className="verify-download-error">
                  <span className="material-symbols-outlined" style={{ fontSize: 16 }}>error</span>
                  {downloadError}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
