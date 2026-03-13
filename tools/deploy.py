#!/usr/bin/env python3
"""
Elastic Clothing Fit: standalone deployment tool.

Usage:
    python tools/deploy.py build [--blender <exe>] [--skip-test]
    python tools/deploy.py select [--zip <path>] [--blender <exe>] [--skip-test]
"""
import argparse
import datetime
import glob
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent
_ADDON_DIR = _ROOT / "elastic_fit"
_INIT_PY = _ADDON_DIR / "__init__.py"
_TESTS_DIR = _ROOT / "tests"
_PHASE1_SCRIPT = _TESTS_DIR / "test_deployment_phase1.py"
_PHASE2_SCRIPT = _TESTS_DIR / "test_deployment_phase2.py"
_UNINSTALL_SCRIPT = _TESTS_DIR / "test_deployment_uninstall.py"
_INSTALL_SCRIPT = _TESTS_DIR / "test_deployment_install.py"

# ---------------------------------------------------------------------------
# Pure utility functions (unit-testable, no side effects)
# ---------------------------------------------------------------------------

def _sha256_file(path):
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _parse_zip_version(filename):
    """Extract (major, minor, patch) from a string containing vX.Y.Z."""
    m = re.search(r"v(\d+)\.(\d+)\.(\d+)", str(filename))
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _read_version(init_path=None):
    """Read version from bl_info in __init__.py. Returns 'major.minor.patch'."""
    path = pathlib.Path(init_path or _INIT_PY)
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', text)
    if not m:
        raise ValueError(f"Could not parse version from {path}")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def _parse_results(stdout):
    """Parse [PASS] / [FAIL] lines from captured Blender stdout."""
    passed = []
    failed = []
    for line in stdout.splitlines():
        s = line.strip()
        if "[PASS]" in s:
            passed.append(s)
        elif "[FAIL]" in s:
            failed.append(s)
    return {"passed": passed, "failed": failed}


# ---------------------------------------------------------------------------
# Blender discovery
# ---------------------------------------------------------------------------

def _version_from_path(path):
    """Extract a sortable (major, minor, 0) version tuple from a path string. Matches the first X.Y or 'X Y' digit pair found."""
    m = re.search(r"(\d+)[.\s](\d+)", str(path))
    if m:
        return (int(m.group(1)), int(m.group(2)), 0)
    return (0, 0, 0)


def _find_blender(cli_override=None):
    """
    Locate blender.exe.

    Priority:
      1. Auto-detect common Windows install locations (highest version wins).
         If any install is found, steps 2 and 3 are skipped entirely.
      2. BLENDER_PATH environment variable (only if auto-detect finds nothing)
      3. cli_override / --blender argument (only if steps 1 and 2 both fail)

    Returns the path string or None if not found.
    """
    candidates = []

    # Program Files
    for p in glob.glob(
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe"
    ):
        candidates.append(p)

    # Steam
    steam = r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
    if pathlib.Path(steam).is_file():
        candidates.append(steam)

    # LocalAppData (user installs)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        for p in glob.glob(
            str(pathlib.Path(local) / "Programs" / "Blender Foundation" / "Blender*" / "blender.exe")
        ):
            candidates.append(p)

    # PATH
    which = shutil.which("blender")
    if which:
        candidates.append(which)

    if candidates:
        candidates.sort(key=_version_from_path, reverse=True)
        return candidates[0]

    # Env var fallback
    env = os.environ.get("BLENDER_PATH", "")
    if env and pathlib.Path(env).is_file():
        return env

    # CLI fallback
    if cli_override and pathlib.Path(str(cli_override)).is_file():
        return str(cli_override)

    return None


# ---------------------------------------------------------------------------
# Zip building
# ---------------------------------------------------------------------------

def _build_zip(version, nightly=False):
    """
    Build the release zip from the elastic_fit/ directory.
    Excludes .pyc files and __pycache__ directories.
    When nightly=True the zip is named with a date suffix.
    Returns the zip path as a pathlib.Path.
    """
    if nightly:
        ts = datetime.datetime.now().strftime('%Y%m%d%H%M')
        zip_name = f"ElasticClothingFit-v{version}-nightly-{ts}.zip"
    else:
        zip_name = f"ElasticClothingFit-v{version}.zip"
    zip_path = _ROOT / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in _ADDON_DIR.rglob("*"):
            if f.suffix == ".pyc" or "__pycache__" in f.parts:
                continue
            if f.name == "_dev_mode":
                continue
            zf.write(f, f.relative_to(_ROOT))
        if nightly:
            ts = datetime.datetime.now().strftime('%Y%m%d%H%M')
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', '--short=7', 'HEAD'],
                    capture_output=True, text=True, cwd=str(_ROOT),
                )
                short_hash = result.stdout.strip() if result.returncode == 0 else 'unknown'
            except Exception:
                short_hash = 'unknown'
            zf.writestr("elastic_fit/_nightly.txt", f"{ts} {short_hash}")
    return zip_path


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def _run_phase(blender, script, zip_path):
    """
    Run one Blender background test phase.
    --factory-startup prevents user addons (including MCP servers) from loading,
    which avoids port conflicts with a running interactive Blender session.
    Returns (returncode, combined_stdout_stderr).
    """
    result = subprocess.run(
        [blender, "--background", "--factory-startup",
         "--python", str(script), "--", "--zip", str(zip_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _print_summary(phase1_results, phase2_results):
    """Print a PHASE_1 / PHASE_2 results table and list any failures."""
    p1 = phase1_results
    p2 = phase2_results

    def _row(label, r):
        total = len(r["passed"]) + len(r["failed"])
        return f"  {label:<10} {total:<8} {len(r['passed']):<8} {len(r['failed'])}"

    print("\n" + "=" * 52)
    print(f"  {'Phase':<10} {'Tests':<8} {'Passed':<8} {'Failed'}")
    print("  " + "-" * 48)
    print(_row("PHASE_1", p1))
    print(_row("PHASE_2", p2))
    print("=" * 52)

    all_failed = (
        [("PHASE_1", line) for line in p1["failed"]]
        + [("PHASE_2", line) for line in p2["failed"]]
    )
    if all_failed:
        print("\nFailed tests:")
        for phase, line in all_failed:
            print(f"  [{phase}] {line}")


def _run_tests(blender, zip_path):
    """Execute PHASE_1 and PHASE_2, print output and summary. Returns exit code."""
    print(f"\nBlender : {blender}")
    print(f"Zip     : {zip_path}")

    print("\n--- PHASE 1 ---")
    _rc1, out1 = _run_phase(blender, _PHASE1_SCRIPT, zip_path)
    print(out1)
    r1 = _parse_results(out1)

    print("\n--- PHASE 2 ---")
    _rc2, out2 = _run_phase(blender, _PHASE2_SCRIPT, zip_path)
    print(out2)
    r2 = _parse_results(out2)

    _print_summary(r1, r2)

    return 0 if (len(r1["failed"]) + len(r2["failed"])) == 0 else 1


def _run_install(blender, zip_path):
    """Uninstall any existing addon, then reinstall from zip and leave it enabled."""
    print(f"\nBlender : {blender}")
    print(f"Zip     : {zip_path}")

    # UNINSTALL: --factory-startup so user addons (incl. MCP) never load.
    # The uninstall script only needs to delete files, not touch prefs.
    print("\n--- UNINSTALL ---")
    result_u = subprocess.run(
        [blender, "--background", "--factory-startup",
         "--python", str(_UNINSTALL_SCRIPT)],
        capture_output=True,
        text=True,
    )
    out_u = result_u.stdout + result_u.stderr
    print(out_u)
    r_u = _parse_results(out_u)

    # INSTALL: user prefs needed so the enable persists.
    # Disable any MCP addons via --python-expr before the install script runs,
    # preventing port conflicts with a running interactive Blender session.
    _mcp_disable = (
        "import bpy\n"
        "[bpy.ops.preferences.addon_disable(module=k) "
        "for k in list(bpy.context.preferences.addons.keys()) "
        "if 'mcp' in k.lower()]"
    )
    print("\n--- INSTALL ---")
    result_i = subprocess.run(
        [blender, "--background",
         "--python-expr", _mcp_disable,
         "--python", str(_INSTALL_SCRIPT), "--", "--zip", str(zip_path)],
        capture_output=True,
        text=True,
    )
    out_i = result_i.stdout + result_i.stderr
    print(out_i)
    r_i = _parse_results(out_i)

    total_u = len(r_u["passed"]) + len(r_u["failed"])
    total_i = len(r_i["passed"]) + len(r_i["failed"])
    print("\n" + "=" * 52)
    print(f"  {'Phase':<10} {'Tests':<8} {'Passed':<8} {'Failed'}")
    print("  " + "-" * 48)
    print(f"  {'UNINSTALL':<10} {total_u:<8} {len(r_u['passed']):<8} {len(r_u['failed'])}")
    print(f"  {'INSTALL':<10} {total_i:<8} {len(r_i['passed']):<8} {len(r_i['failed'])}")
    print("=" * 52)

    all_failed = (
        [("UNINSTALL", line) for line in r_u["failed"]]
        + [("INSTALL",   line) for line in r_i["failed"]]
    )
    if all_failed:
        print("\nFailed tests:")
        for phase, line in all_failed:
            print(f"  [{phase}] {line}")

    return 0 if not all_failed else 1


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_build(args):
    """build subcommand: read version, create zip, run deployment test."""
    version = _read_version()
    nightly = getattr(args, 'nightly', False)
    zip_path = _build_zip(version, nightly=nightly)
    digest   = _sha256_file(zip_path)
    print(f"Built: {zip_path}")
    print(f"SHA256: {digest}")

    if args.skip_test:
        return 0

    blender = _find_blender(getattr(args, "blender", None))
    if not blender:
        print(
            "ERROR: Blender not found.\n"
            "  Set BLENDER_PATH environment variable or pass --blender <exe>."
        )
        return 1

    return _run_tests(blender, zip_path)


def cmd_select(args):
    """select subcommand: pick an existing zip, run deployment test."""
    if getattr(args, "zip", None):
        zip_path = pathlib.Path(args.zip)
        if not zip_path.is_file():
            print(f"ERROR: Zip not found: {zip_path}")
            return 1
    else:
        zips = sorted(
            _ROOT.glob("ElasticClothingFit-v*.zip"),
            key=lambda p: _parse_zip_version(p.name),
            reverse=True,
        )
        if not zips:
            print("No ElasticClothingFit-v*.zip files found in project root.")
            return 1

        print("\nAvailable zips (newest first):")
        for i, z in enumerate(zips, 1):
            print(f"  {i}. {z.name}")

        choice = input("\nSelect zip number: ").strip()
        try:
            zip_path = zips[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"Invalid selection: {choice!r}")
            return 1

    if args.skip_test:
        print(f"Selected: {zip_path}")
        return 0

    blender = _find_blender(getattr(args, "blender", None))
    if not blender:
        print(
            "ERROR: Blender not found.\n"
            "  Set BLENDER_PATH environment variable or pass --blender <exe>."
        )
        return 1

    return _run_tests(blender, zip_path)


def cmd_install(args):
    """install subcommand: build zip and install addon into Blender, leaving it enabled."""
    version = _read_version()
    zip_path = _build_zip(version)
    digest   = _sha256_file(zip_path)
    print(f"Built: {zip_path}")
    print(f"SHA256: {digest}")

    blender = _find_blender(getattr(args, "blender", None))
    if not blender:
        print(
            "ERROR: Blender not found.\n"
            "  Set BLENDER_PATH environment variable or pass --blender <exe>."
        )
        return 1

    return _run_install(blender, zip_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        description="Elastic Clothing Fit: standalone deployment tool"
    )
    parser.add_argument(
        "--blender",
        metavar="EXE",
        help="Path to blender.exe (last-resort fallback after auto-detect and BLENDER_PATH)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Build zip from source and run deployment test")
    build_p.add_argument(
        "--skip-test", action="store_true", dest="skip_test",
        help="Build zip only, skip deployment test"
    )
    build_p.add_argument(
        "--nightly", action="store_true",
        help="Name zip with nightly timestamp suffix (ElasticClothingFit-vX.Y.Z-nightly-YYYYMMDDHHMM.zip)"
    )

    select_p = sub.add_parser("select", help="Select an existing zip and run deployment test")
    select_p.add_argument(
        "--zip", metavar="PATH", help="Use this zip directly (skips interactive prompt)"
    )
    select_p.add_argument(
        "--skip-test", action="store_true", dest="skip_test",
        help="Select zip only, skip deployment test"
    )

    sub.add_parser("install", help="Build zip and install addon into Blender (leaves it enabled)")

    args = parser.parse_args()

    if args.command == "build":
        sys.exit(cmd_build(args))
    elif args.command == "select":
        sys.exit(cmd_select(args))
    elif args.command == "install":
        sys.exit(cmd_install(args))


if __name__ == "__main__":
    main()
