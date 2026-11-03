# NODIQ-X Documentation Index

This directory contains technical specifications, architecture diagrams, compliance manuals, and security audits for the NODIQ-X platform.

---

## Architecture & System Overview
- [`architecture.md`](architecture.md) — Comprehensive architecture specification, folder map, request flow, worker process spawning, and storage topologies.
- [`JUDGE_ARCHITECTURE.md`](JUDGE_ARCHITECTURE.md) — Simplified visual architecture and end-to-end request pipelines for evaluators.
- [`JUDGE_CODE_MAP.md`](JUDGE_CODE_MAP.md) — Direct mapping from UI buttons and routes to backend handlers, database records, and processing algorithms.
- [`JUDGE_FILE_GUIDE.md`](JUDGE_FILE_GUIDE.md) — Codebase guide answering "where does X live in this repository?".
- [`JUDGE_VIVA_CHEAT_SHEET.md`](JUDGE_VIVA_CHEAT_SHEET.md) — Quick question-and-answer guide for metallurgical, architectural, and security questions.

---

## Metallurgical Standards & Pipeline Setup
- [`ACCURACY.md`](ACCURACY.md) — Validation methodology, 1000/1000 verified reference dataset, and ground-truth metrics.
- [`GROUND_TRUTH.md`](GROUND_TRUTH.md) — Schema and workflow for expert-annotated ground-truth validation datasets.
- [`STEEL_GRAIN_SIZE_SETUP.md`](STEEL_GRAIN_SIZE_SETUP.md) — Setup and deployment manual for ASTM E112 Heyn linear intercept and Cellpose-SAM Jeffries planimetric analyses.

---

## Deployment & Operations
- [`HOSTING_CHECKLIST.md`](HOSTING_CHECKLIST.md) — Production deployment checklist, worker sizing, and health check monitoring.
- [`DEPLOY_SUPABASE.md`](DEPLOY_SUPABASE.md) — PostgreSQL and object storage schema setup for Supabase persistence.
- [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md) — Repository reorganization plan and phase tracking.

---

## Security & Governance
- [`SECURITY.md`](SECURITY.md) — Security policies, threat model, and vulnerability reporting procedures.
- [`SECURITY_ROTATION.md`](SECURITY_ROTATION.md) — Secrets hygiene and LLM key rotation protocols.
- [`FINAL_SECURITY_REPORT.md`](FINAL_SECURITY_REPORT.md) — Comprehensive security assessment covering session cookies, rate limits, and injection defenses.
- [`reports/security-report.md`](reports/security-report.md) — Authorized penetration testing report.

---

## Frontend, Design & Rules
- [`DESIGN.md`](DESIGN.md) — Design system, typography tiers, color tokens, and layout guidelines.
- [`RULES.md`](RULES.md) — Code hygiene, engineering principles, and contributor guidelines.
- [`TEST_PLAN.md`](TEST_PLAN.md) — Automated testing matrix and validation procedures.
