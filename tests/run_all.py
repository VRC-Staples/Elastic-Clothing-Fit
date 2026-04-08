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
    ("Armature Tools", "suite_armature_tools.py",  True),
    ("Mesh Tools",     "suite_mesh_tools.py",      False),
    ("Proxy Hull",     "suite_proxy_hull.py",      True),
    ("VG Stability",   "suite_vg_stability.py",    True),
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        combined = result.stdout + result.stderr
        return result.returncode, combined
    except subprocess.TimeoutExpired:
        return 1, f"[TIMEOUT] Suite '{script_path.name}' timed out after 300s\n"


def _run_screenshots(blender, blend_path, out_root):
    """Run blender_screenshot.py for a blend file after a suite completes.

    blender    -- path to blender executable (already resolved)
    blend_path -- absolute path string to the .blend file
    out_root   -- repo root used to construct the output directory (tmp/ subdir)

    Returns the [SCREENSHOTS] output directory path on success, or None on failure.
    Failure is non-fatal: a [WARN] line is printed but nothing is raised.
    """
    screenshot_script = str(_ROOT / "tools" / "blender_screenshot.py")
    out_dir = str(pathlib.Path(out_root) / "tmp")
    cmd = [
        blender, "--background",
        "--python", screenshot_script,
        "--",
        "--blend-file", str(blend_path),
        "--out-dir", out_dir,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        combined = result.stdout + result.stderr
        if result.returncode != 0:
            # include truncated stderr so the warning is self-describing
            reason = f"exit code {result.returncode}"
            stderr_snippet = result.stderr.strip()
            if stderr_snippet:
                # limit to last 200 chars to keep output readable
                reason += ": " + stderr_snippet[-200:]
            return None, reason
        # extract the [SCREENSHOTS] line for the output path
        for line in combined.splitlines():
            if line.strip().startswith("[SCREENSHOTS]"):
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    return parts[1], None
        return None, "no [SCREENSHOTS] line found in output"
    except Exception as exc:
        return None, str(exc)


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
    parser.add_argument(
        "--programmatic",
        action="store_true",
        help="Create all geometry programmatically (no .blend files required)",
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
        # Blend file to use for screenshots after each blend-using suite.
        # Suites not in this mapping (mesh_tools, ux_tabs) do not trigger screenshots.
        SCREENSHOT_BLEND = {
            "Fit Pipeline":   "ECF_Test.blend",
            "Proximity":      "ECF_Test3.blend",
            "Armature Tools": "ECF_Test2.blend",
            "Proxy Hull":     "ECF_Test.blend",
        }

        fit_pipeline_failed = False

        for name, script_file, needs_blend_root in SUITES:
            script_path = _SUITES_DIR / script_file
            print("\n" + "=" * 60)
            print(f"SUITE: {name}")
            print("=" * 60)

            # Proximity is conditionally skipped when Fit Pipeline had failures.
            if name == "Proximity" and fit_pipeline_failed:
                extra = ["--skip"]
            elif args.programmatic and needs_blend_root:
                extra = ["--programmatic"]
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

            if not args.programmatic and name in SCREENSHOT_BLEND:
                blend_file = SCREENSHOT_BLEND[name]
                blend_abs = str(pathlib.Path(blend_root) / "tests" / blend_file)
                screenshot_dir, err = _run_screenshots(blender, blend_abs, blend_root)
                if err is not None:
                    print(f"[WARN] screenshots failed for {name}: {err}")
                else:
                    print(f"[SCREENSHOTS] {screenshot_dir}")

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
