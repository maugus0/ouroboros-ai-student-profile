#!/usr/bin/env python3
"""PII Guard: Scan fixture files for sensitive personal information.

Detects:
- Email addresses
- Phone numbers
- Social security numbers
- Credit card numbers
- API keys (placeholder check)
"""

import argparse
import re
import sys
from pathlib import Path


class PIIScanner:
    """Scans text for common PII patterns."""

    # PII regex patterns
    PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        "phone": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
        "api_key": r"(?:api[_-]?key|apikey|secret|token|sk[-_])\s*[:=]\s*['\"]?[A-Za-z0-9_-]{10,}['\"]?",
    }

    @classmethod
    def scan(cls, text, patterns=None):
        """Scan text for PII.

        Args:
            text: Text to scan
            patterns: List of pattern keys to scan for (all if None)

        Returns:
            List of tuples: (pattern_name, match_text, line_number)
        """
        if patterns is None:
            patterns = list(cls.PATTERNS.keys())

        findings = []
        for line_num, line in enumerate(text.split("\n"), 1):
            for pattern_name in patterns:
                if pattern_name not in cls.PATTERNS:
                    continue

                regex = cls.PATTERNS[pattern_name]
                matches = re.finditer(regex, line, re.IGNORECASE)
                for match in matches:
                    findings.append((pattern_name, match.group(), line_num))

        return findings


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Scan fixture files for PII"
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to directory or file to scan",
    )
    parser.add_argument(
        "--patterns",
        type=str,
        default=None,
        help="Comma-separated list of patterns to check (default: all)",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit with code 1 if findings detected",
    )

    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"❌ Path not found: {path}")
        return 1

    patterns = (
        args.patterns.split(",") if args.patterns else None
    )

    files_to_scan = []
    if path.is_file():
        files_to_scan = [path]
    else:
        files_to_scan = list(path.rglob("*.json")) + list(
            path.rglob("*.txt")
        )

    if not files_to_scan:
        print(f"✅ No files to scan in {path}")
        return 0

    total_findings = 0
    for file_path in sorted(files_to_scan):
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            findings = PIIScanner.scan(content, patterns)

            if findings:
                print(f"\n⚠️  {file_path}:")
                for pattern, match, line_num in findings:
                    # Truncate very long matches
                    display_match = (
                        match[:50] + "..."
                        if len(match) > 50
                        else match
                    )
                    print(
                        f"   Line {line_num}: [{pattern}] {display_match}"
                    )
                total_findings += len(findings)

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"❌ Error scanning {file_path}: {e}")

    if total_findings == 0:
        print(f"✅ No PII detected in {len(files_to_scan)} file(s)")
        return 0

    print(
        f"\n⚠️  Found {total_findings} potential PII indicator(s) "
        "in fixtures"
    )
    if args.fail_on_findings:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
