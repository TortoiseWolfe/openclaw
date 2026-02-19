"""Security utilities for handling untrusted external content.

Python equivalent of src/security/external-content.ts.

Usage:
    from content_security import wrap_external, detect_suspicious

    # Wrap external content before printing to stdout (which the LLM sees)
    safe_output = wrap_external(job_description, source="linkedin")
    print(safe_output)

    # Check for suspicious patterns
    flags = detect_suspicious(some_text)
    if flags:
        print(f"[security] Suspicious patterns: {flags}", file=sys.stderr)
"""

import re

SUSPICIOUS_PATTERNS = [
    ("ignore-instructions", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.I)),
    ("disregard-instructions", re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I)),
    ("forget-instructions", re.compile(r"forget\s+(everything|all|your)\s+(instructions?|rules?|guidelines?)", re.I)),
    ("role-override", re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I)),
    ("new-instructions", re.compile(r"new\s+instructions?:", re.I)),
    ("system-prompt-override", re.compile(r"system\s*:?\s*(prompt|override|command)", re.I)),
    ("code-exec", re.compile(r"\bexec\b.*command\s*=", re.I)),
    ("privilege-escalation", re.compile(r"elevated\s*=\s*true", re.I)),
    ("destructive-command", re.compile(r"rm\s+-rf", re.I)),
    ("bulk-delete", re.compile(r"delete\s+all\s+(emails?|files?|data)", re.I)),
    ("fake-system-tag", re.compile(r"</?system>", re.I)),
    ("fake-role-tag", re.compile(r"\]\s*\n\s*\[?(system|assistant|user)\]?:", re.I)),
]

BOUNDARY_START = "<<<EXTERNAL_UNTRUSTED_CONTENT>>>"
BOUNDARY_END = "<<<END_EXTERNAL_UNTRUSTED_CONTENT>>>"


def detect_suspicious(text: str) -> list[str]:
    """Check text for prompt injection patterns. Returns list of matched pattern names."""
    return [name for name, pattern in SUSPICIOUS_PATTERNS if pattern.search(text)]


def sanitize_field(text: str, max_len: int = 200) -> str:
    """Sanitize a single field from external content.

    Strips newlines (prevents injection via multi-line fields) and limits length.
    """
    if not text:
        return ""
    # Collapse newlines and excessive whitespace
    cleaned = re.sub(r"[\r\n]+", " ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned[:max_len]


def wrap_external(content: str, source: str = "external",
                  sender: str | None = None) -> str:
    """Wrap untrusted content with security boundaries.

    Args:
        content: The untrusted text content
        source: Source label (e.g. "linkedin", "email", "web", "youtube")
        sender: Optional sender/origin info
    """
    meta_lines = [f"Source: {source}"]
    if sender:
        meta_lines.append(f"From: {sender}")

    return "\n".join([
        BOUNDARY_START,
        "\n".join(meta_lines),
        "---",
        content,
        BOUNDARY_END,
    ])
