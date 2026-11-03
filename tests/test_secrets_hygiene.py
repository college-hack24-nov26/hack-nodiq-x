#!/usr/bin/env python3
"""
tests/test_secrets_hygiene.py — secrets-hygiene regression tests.

Locks in the secrets audit:
- the real .env is never tracked by git
- no secret literals (API keys, private keys, DB URLs) in any tracked text
- the built browser bundle never contains server-only secrets
- the only VITE_ (browser-shipping) env surface is the Firebase config,
  which is public by design
"""
import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

SKIP_DIRS = {"node_modules", "dist", "__pycache__", "server_data",
             "nodularity_1000_fixed", ".git", ".freebuff", "reports",
             ".pytest_cache", "public", "dataset", ".venv-astm",
             ".venv-cast-iron", ".venv", "venv", ".agents", ".agent",
             ".gemini", ".gsd"}
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md",
                 ".yml", ".yaml", ".html", ".css", ".example", ".txt",
                 ".cfg", ".toml", ".sh", ".ps1", ".bat"}

# high-signal secret families (value prefixes are provider-issued)
SECRET_PATTERNS = {
    "groq":      re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "google":    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "openai":    re.compile(r"sk-(proj|svcacct)-[A-Za-z0-9_\-]{20,}"),
    "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "stripe":    re.compile(r"[sr]k_(live|test)_[A-Za-z0-9]{16,}"),
    "whsec":     re.compile(r"whsec_[A-Za-z0-9]{16,}"),
    "slack":     re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    "github":    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"),
    "aws":       re.compile(r"A[KS]IA[0-9A-Z]{16}"),
    "private":   re.compile(r"BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY"),
    "db_url":    re.compile(r"(postgres(?:ql)?|mysql|mongodb(\+srv)?|redis|amqp)"
                            r"://[^\s'\":]{8,}:[^\s'\":]{3,}@"),
}


def _iter_text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = pathlib.Path(dirpath)
        if (set(rel.parts) & SKIP_DIRS) or any(part.startswith((".venv", "venv")) for part in rel.parts):
            dirnames[:] = []
            continue
        for fn in filenames:
            p = rel / fn
            if p.name == ".env":          # audited separately below
                continue
            if p.suffix.lower() not in TEXT_SUFFIXES and p.name != ".env.example":
                continue
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                yield p, p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def test_env_file_is_not_tracked():
    tracked = _git("ls-files")
    assert ".env" not in tracked.split(), ".env must never be committed"


def test_env_is_gitignored():
    out = _git("check-ignore", "-v", ".env")
    assert ".env" in out, ".env must be covered by .gitignore"


def test_no_secret_literals_in_source():
    leaks = []
    for p, text in _iter_text_files():
        for family, pat in SECRET_PATTERNS.items():
            m = pat.search(text)
            if m:
                line = text[:m.start()].count("\n") + 1
                leaks.append(f"{family}: {p.relative_to(ROOT)}:{line}")
    assert not leaks, "secret literals found in source: " + ", ".join(leaks)


def test_browser_bundle_has_no_server_secrets():
    dist = ROOT / "apps" / "web" / "dist" / "assets"
    if not dist.exists():
        pytest.skip("frontend not built yet")
    server_only = ("gsk_", "sk-ant-", "sk-proj-", "whsec_", "xoxb-",
                   "ghp_", "AKIA", "PRIVATE KEY", "SMTP_PASS")
    for js in dist.glob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        for marker in server_only:
            assert marker not in text, f"server-only secret marker {marker!r} in {js.name}"


def test_vite_surface_is_firebase_only():
    """Everything the browser reads via import.meta.env must be the public
    Firebase config — no other value may use a public prefix."""
    src = ROOT / "apps" / "web" / "src"
    used = set()
    for p in src.rglob("*"):
        if p.suffix.lower() in (".js", ".jsx", ".ts", ".tsx"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            used |= set(re.findall(r"import\.meta\.env\.([A-Z_]+)", text))
    bad = [k for k in used if not k.startswith("VITE_FIREBASE_")]
    assert not bad, f"non-Firebase VITE_ usage found: {bad}"
    assert used, "firebase config expected in src"


def test_env_example_has_empty_values():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for m in re.finditer(r"^([A-Z][A-Z0-9_]+)=(.+)$", example, re.M):
        key, val = m.group(1), m.group(2).strip()
        assert val == "" or val.startswith(("true", "false", "auto", "http://127",
                                            "587", "25")), \
            f".env.example must not ship real values: {key}={val[:6]}…"


# ------------------------------------------------------ infrastructure ----

def _tracked_logs():
    out = subprocess.run(
        ["git", "ls-files", "*.log"], cwd=ROOT, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def test_no_runtime_logs_are_tracked():
    tracked = _tracked_logs()
    assert not tracked, f"runtime logs must not be committed: {tracked}"


def test_security_headers_on_every_response():
    server = pytest.importorskip("nodiq.api.server")
    c = server.app.test_client()
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    # CSP ships Report-Only until a violation-free window (see
    # docs/SECURITY_ROTATION.md); either form must be present.
    assert (r.headers.get("Content-Security-Policy")
            or r.headers.get("Content-Security-Policy-Report-Only"))


def test_csp_keeps_recaptcha_sources_allowed():
    """Regression: Phone login needs Firebase reCAPTCHA, whose bootstrap
    (/recaptcha/api.js) and verdict pings live on www.google.com — distinct
    hosts from gstatic/googleapis. Blocking them surfaced to users as
    `auth/internal-error` on signInWithPhoneNumber. The policy must stay
    strict (no unsafe-inline/eval in script-src) while allowing exactly
    these Firebase-required hosts."""
    server = pytest.importorskip("nodiq.api.server")
    csp = server._SECURITY_HEADERS["Content-Security-Policy"]
    directives = dict(
        part.strip().split(" ", 1)
        for part in csp.split(";") if part.strip()
    )
    script_src = directives["script-src"].split()
    connect_src = directives["connect-src"].split()
    assert "https://www.google.com" in script_src
    assert "https://www.google.com" in connect_src
    # Google sign-in popup machinery loads /js/api.js from apis.google.com
    # (blocking it surfaced as auth/internal-error on Continue with Google)
    assert "https://apis.google.com" in script_src
    # keep the Firebase reCAPTCHA widget hosts reachable
    assert "https://www.gstatic.com" in script_src
    assert any(d == "frame-src" and "https://www.google.com" in v.split()
               for d, v in directives.items())
    # the policy must not be loosened as a shortcut
    assert "unsafe-inline" not in script_src
    assert "unsafe-eval" not in script_src
    assert "*" not in script_src


def test_cors_is_allowlisted_not_reflect_all():
    server = pytest.importorskip("nodiq.api.server")
    c = server.app.test_client()
    r = c.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") != "*"
    assert "evil.example" not in r.headers.get("Access-Control-Allow-Origin", "")


def test_docker_build_excludes_secrets():
    """The build context rules must keep .env, server_data and logs out of
    the image (the image itself is verified live in the hardening pass)."""
    di = ROOT / ".dockerignore"
    assert di.exists(), ".dockerignore missing"
    text = di.read_text(encoding="utf-8")
    for required in (".env", "server_data", "*.log", ".git"):
        assert required in text, f".dockerignore must exclude {required}"


def test_no_debug_server_in_production_entrypoint():
    dockerfile_path = ROOT / "deploy" / "Dockerfile"
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    assert "gunicorn" in dockerfile, "production must run a real WSGI server"
    assert "app.run" not in dockerfile
    server_path = ROOT / "src" / "nodiq" / "api" / "server.py"
    server_src = server_path.read_text(encoding="utf-8")
    # the __main__ dev entry stays available for local use but must never
    # enable the interactive debugger
    assert "debug=True" not in server_src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
