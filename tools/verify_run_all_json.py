#!/usr/bin/env python3
"""Verify tests/run_all.py JSON artifacts for CI fail-closed guarantees.

This checker validates structural and semantic invariants for run_all `--json-out`
output so workflow runs cannot silently pass with under-executed suites.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_REQUIRED_SUITES = [
    "UX Tabs",
    "Fit Pipeline",
    "Proximity",
    "Armature Tools",
    "Mesh Tools",
    "Proxy Hull",
    "VG Stability",
]


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def verify_payload(
    payload: Any,
    *,
    expected_suites: int,
    min_checks: int,
    required_suite_names: list[str] | None = None,
) -> list[str]:
    """Return a list of invariant violations for the run_all JSON payload."""
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["Payload must be a JSON object at top level."]

    if "suites" not in payload:
        return ["Missing required key: suites"]

    suites = payload.get("suites")
    if not isinstance(suites, list):
        return ["Invalid type for suites: expected list"]

    total_passed = payload.get("total_passed")
    total_failed = payload.get("total_failed")

    if "total_passed" not in payload:
        errors.append("Missing required key: total_passed")
    elif not _is_non_negative_int(total_passed):
        errors.append("Invalid type/value for total_passed: expected non-negative int")

    if "total_failed" not in payload:
        errors.append("Missing required key: total_failed")
    elif not _is_non_negative_int(total_failed):
        errors.append("Invalid type/value for total_failed: expected non-negative int")

    suite_names: list[str] = []
    suite_pass_sum = 0
    suite_fail_sum = 0

    for idx, suite in enumerate(suites):
        prefix = f"suites[{idx}]"
        if not isinstance(suite, dict):
            errors.append(f"{prefix} must be an object")
            continue

        name = suite.get("name")
        passed = suite.get("passed")
        failed = suite.get("failed")

        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}.name must be a non-empty string")
        else:
            suite_names.append(name)

        if not _is_non_negative_int(passed):
            errors.append(f"{prefix}.passed must be a non-negative int")
        else:
            suite_pass_sum += passed

        if not _is_non_negative_int(failed):
            errors.append(f"{prefix}.failed must be a non-negative int")
        else:
            suite_fail_sum += failed

    if len(suites) != expected_suites:
        errors.append(
            f"Suite count mismatch: expected {expected_suites}, got {len(suites)}"
        )

    seen: dict[str, int] = {}
    for name in suite_names:
        seen[name] = seen.get(name, 0) + 1

    duplicates = sorted([name for name, count in seen.items() if count > 1])
    if duplicates:
        errors.append(f"Duplicate suite names: {', '.join(duplicates)}")

    required = required_suite_names or []
    if required:
        missing = sorted([name for name in required if seen.get(name, 0) == 0])
        unexpected = sorted([name for name in seen if name not in required])
        if missing:
            errors.append(f"Missing required suites: {', '.join(missing)}")
        if unexpected:
            errors.append(f"Unexpected suites present: {', '.join(unexpected)}")

    if _is_non_negative_int(total_passed) and total_passed != suite_pass_sum:
        errors.append(
            "total_passed mismatch: "
            f"header={total_passed}, computed_from_suites={suite_pass_sum}"
        )

    if _is_non_negative_int(total_failed) and total_failed != suite_fail_sum:
        errors.append(
            "total_failed mismatch: "
            f"header={total_failed}, computed_from_suites={suite_fail_sum}"
        )

    if _is_non_negative_int(total_failed) and total_failed > 0:
        errors.append(f"Run reported failing checks: total_failed={total_failed}")

    if _is_non_negative_int(total_passed) and _is_non_negative_int(total_failed):
        total_checks = total_passed + total_failed
        if total_checks < min_checks:
            errors.append(
                "Total check count below minimum: "
                f"{total_checks} < min_checks={min_checks}"
            )

    return errors


def verify_json_file(
    json_path: Path,
    *,
    expected_suites: int,
    min_checks: int,
    required_suite_names: list[str] | None = None,
) -> list[str]:
    """Load and verify a JSON artifact, returning invariant violations."""
    try:
        raw = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"Unable to read JSON file '{json_path}': {exc}"]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [
            f"Invalid JSON in '{json_path}' at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ]

    return verify_payload(
        payload,
        expected_suites=expected_suites,
        min_checks=min_checks,
        required_suite_names=required_suite_names,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate tests/run_all.py --json-out artifacts for nightly CI."
    )
    parser.add_argument("--json", required=True, help="Path to run_all JSON artifact.")
    parser.add_argument(
        "--expected-suites",
        type=int,
        default=7,
        help="Expected number of suite records in artifact (default: 7).",
    )
    parser.add_argument(
        "--min-checks",
        type=int,
        default=240,
        help="Minimum total checks (total_passed + total_failed) required to pass.",
    )
    parser.add_argument(
        "--required-suite",
        action="append",
        default=None,
        help=(
            "Required suite name. Repeat for multiple values. "
            "If omitted, defaults to the 7 canonical run_all suites."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.expected_suites < 1:
        print("FAIL: --expected-suites must be >= 1")
        return 2
    if args.min_checks < 0:
        print("FAIL: --min-checks must be >= 0")
        return 2

    required_suite_names = args.required_suite or DEFAULT_REQUIRED_SUITES

    errors = verify_json_file(
        Path(args.json),
        expected_suites=args.expected_suites,
        min_checks=args.min_checks,
        required_suite_names=required_suite_names,
    )

    if errors:
        print("FAIL: run_all JSON contract verification failed")
        for error in errors:
            print(f" - {error}")
        return 1

    print(
        "PASS: run_all JSON contract verified "
        f"(expected_suites={args.expected_suites}, min_checks={args.min_checks})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
