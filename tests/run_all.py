#!/usr/bin/env python3
"""One-shot regression runner for Elastic Clothing Fit.

Usage:
    python tests/run_all.py [--blender <exe>] [--blend-root <path>] [--json-out <file>]

Exit codes:
    0 — all suites passed
    1 — one or more suites had failures, or setup failed
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).parent.parent
_SUITES_DIR = _ROOT / "tests" / "blender_suites"

sys.path.insert(0, str(_ROOT / "tools"))
import deploy

# Suite registry: (display_name, script_filename, needs_blend_root)
# Order matters: UX Tabs first (fastest), Fit Pipeline before Proximity
# (Proximity skips if Fit Pipeline fails), then self-contained suites.
SUITES = [
    ("UX Tabs",        "suite_ux_tabs.py",        False),
    ("Fit Pipeline",   "suite_fit_pipeline.py",   True),
    ("Proximity",      "suite_proximity.py",       True),
    ("Armature Tools", "suite_armature_tools.py",  False),
    ("Mesh Tools",     "suite_mesh_tools.py",      False),
    ("Proxy Hull",     "suite_proxy_hull.py",      True),
]


def _parse_suite_output(stdout):
    """Parse [PASS] / [FAIL] / [SKIP] lines from a suite's stdout.

    Returns (passed, failed, skipped, failures) where:
      passed   — count of [PASS] lines
      failed   — count of [FAIL] lines
      skipped  — True if any [SKIP] line was present
      failures — list of verbatim [FAIL] lines
    """
    passed = 0
    failed = 0
    skipped = False
    failures = []
    for line in stdout.splitlines():
        s = line.strip()
        if "[PASS]" in s:
            passed += 1
        elif "[FAIL]" in s:
            failed += 1
            failures.append(s)
        elif "[SKIP]" in s:
            skipped = True
    return passed, failed, skipped, failures


def _run_suite(blender, script_path, blend_root, extra_args=None):
    """Run one suite script as a subprocess.

    Returns (returncode, stdout_text).
    """
    cmd = [blender, "--background", "--python", str(script_path), "--"]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    combined = result.stdout + result.stderr
    return result.returncode, combined


def main():
    parser = argparse.ArgumentParser(
        description="One-shot regression runner for Elastic Clothing Fit"
    )
    parser.add_argument(
        "--blender", metavar="EXE",
        help="Path to blender.exe (last-resort fallback after auto-detect)",
    )
    parser.add_argument(
        "--blend-root", metavar="PATH", default=str(_ROOT),
        help="Repo root for resolving .blend file paths (default: repo root)",
    )
    parser.add_argument(
        "--json-out", metavar="FILE",
        help="Also write JSON output to this file",
    )
    args = parser.parse_args()

    blend_root = str(pathlib.Path(args.blend_root).resolve())
    t_start = time.time()

    # ------------------------------------------------------------------
    # 1. Locate Blender
    # ------------------------------------------------------------------
    blender = deploy._find_blender(args.blender)
    if not blender:
        print(
            "[ERROR] Blender not found.\n"
            "  Set BLENDER_PATH environment variable or pass --blender <exe>."
        )
        sys.exit(1)
    print(f"Blender : {blender}")
    print(f"Root    : {blend_root}")

    # ------------------------------------------------------------------
    # 2. Build zip
    # ------------------------------------------------------------------
    version = deploy._read_version()
    zip_path = deploy._build_zip(version)
    print(f"Built   : {zip_path}")

    # ------------------------------------------------------------------
    # 3. Uninstall + install addon
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SETUP: uninstall + install")
    print("=" * 60)
    install_rc = deploy._run_install(blender, zip_path)
    install_ok = install_rc == 0

    suite_results = []

    if not install_ok:
        # Install failed — mark all suites as not run and emit JSON.
        print("\n[ERROR] Addon install failed — skipping all functional suites.")
        for name, _script, _needs_blend in SUITES:
            suite_results.append({
                "name":     name,
                "passed":   0,
                "failed":   0,
                "skipped":  True,
                "failures": ["[ERROR] Suite not run: addon install failed"],
            })
    else:
        # ------------------------------------------------------------------
        # 4. Run each functional suite
        # ------------------------------------------------------------------
        fit_pipeline_failed = False

        for name, script_file, needs_blend_root in SUITES:
            script_path = _SUITES_DIR / script_file
            print("\n" + "=" * 60)
            print(f"SUITE: {name}")
            print("=" * 60)

            # Proximity is conditionally skipped when Fit Pipeline had failures.
            if name == "Proximity" and fit_pipeline_failed:
                extra = ["--skip"]
            elif needs_blend_root:
                extra = ["--blend-root", blend_root]
            else:
                extra = []

            rc, output = _run_suite(blender, script_path, blend_root, extra_args=extra)
            print(output, end="")

            passed, failed, skipped, failures = _parse_suite_output(output)

            suite_results.append({
                "name":     name,
                "passed":   passed,
                "failed":   failed,
                "skipped":  skipped,
                "failures": failures,
            })

            if name == "Fit Pipeline" and failed > 0:
                fit_pipeline_failed = True
                print("  [INFO] Fit Pipeline had failures — Proximity suite will be skipped.")

    # ------------------------------------------------------------------
    # 5. Compute totals and emit JSON
    # ------------------------------------------------------------------
    duration = round(time.time() - t_start, 2)
    total_passed = sum(s["passed"] for s in suite_results)
    total_failed = sum(s["failed"] for s in suite_results)

    output_data = {
        "suites":          suite_results,
        "total_passed":    total_passed,
        "total_failed":    total_failed,
        "duration_seconds": duration,
    }

    json_text = json.dumps(output_data, indent=2)

    print("\n" + "=" * 60)
    print("RESULTS (JSON)")
    print("=" * 60)
    print(json_text)

    if args.json_out:
        out_path = pathlib.Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_text, encoding="utf-8")
        print(f"\nJSON written to: {out_path}")

    print("\n" + "=" * 60)
    if total_failed == 0:
        print(f"ALL SUITES PASSED  ({total_passed} checks, {duration}s)")
    else:
        print(f"FAILED  ({total_failed} failure(s) across {len(suite_results)} suites, {duration}s)")
    print("=" * 60)

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
