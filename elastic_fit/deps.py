# deps.py
# Bundled dependency loader for performance-critical third-party packages.
#
# pykdtree is a fast KD-tree with OpenMP-enabled batch queries (~66 KB wheel on Windows,
# ~350 KB on macOS/Linux). It replaces the sequential mathutils.KDTree.find_n loop in the
# preserve-follow section, cutting ~60-130ms per preview tick down to ~1-2ms on ECF_Test scale.
#
# Bundled wheels live at elastic_fit/wheels/ and are committed to the repository.
# On first addon load, attempt_import() installs the matching wheel into Blender's
# user scripts/modules directory silently — no network access required, no user action needed.
#
# Import rules:
#   - Import this module at the top of preview.py and pipeline.py.
#   - Check `deps.PYKDTREE_AVAILABLE` before using `deps.BatchKDTree`.
#   - When unavailable (unsupported platform / install failed), fall back to mathutils.KDTree.

import os
import pathlib
import platform
import site
import struct
import subprocess
import sys

import bpy

# ---------------------------------------------------------------------------
# Public state
# ---------------------------------------------------------------------------

#: True once pykdtree has been successfully imported.
PYKDTREE_AVAILABLE: bool = False

#: The pykdtree.kdtree.KDTree class, or None when not available.
BatchKDTree = None

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _modules_path() -> str:
    """Return the user-writable scripts/modules directory for this Blender version."""
    return bpy.utils.user_resource("SCRIPTS", path="modules", create=True)


def _ensure_sys_path(modules_path: str) -> None:
    """Add *modules_path* to sys.path and site directories."""
    if modules_path not in sys.path:
        sys.path.insert(0, modules_path)
    site.addsitedir(modules_path)


def _try_import() -> bool:
    """Attempt to import pykdtree. Returns True on success."""
    global PYKDTREE_AVAILABLE, BatchKDTree
    try:
        from pykdtree.kdtree import KDTree as _pyKDTree  # noqa: PLC0415
        BatchKDTree = _pyKDTree
        PYKDTREE_AVAILABLE = True
        return True
    except ImportError:
        return False


def _python_tag() -> str:
    """Return the cpython ABI tag for the running interpreter, e.g. 'cp311'."""
    major = sys.version_info.major
    minor = sys.version_info.minor
    return f"cp{major}{minor}"


def _platform_tag() -> str:
    """Return the wheel platform tag for the current OS/arch, or '' if unknown."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        # Blender only ships 64-bit; ARM Windows is uncommon but handled.
        if machine in ("amd64", "x86_64"):
            return "win_amd64"
        if machine == "arm64":
            return "win_arm64"

    if system == "Darwin":
        if machine == "arm64":
            return "macosx_14_0_arm64"
        return "macosx_13_0_x86_64"

    if system == "Linux":
        if machine in ("x86_64", "amd64"):
            return "manylinux2014_x86_64"
        if "aarch64" in machine or "arm64" in machine:
            return "manylinux2014_aarch64"

    return ""


def _find_bundled_wheel() -> "pathlib.Path | None":
    """Locate the bundled .whl file that matches the current Python/platform.

    Wheels are stored in elastic_fit/wheels/ alongside the addon source.
    Returns the path if a compatible wheel is found, else None.
    """
    wheels_dir = pathlib.Path(__file__).parent / "wheels"
    if not wheels_dir.is_dir():
        return None

    py_tag = _python_tag()
    plat_tag = _platform_tag()
    if not plat_tag:
        return None

    for whl in wheels_dir.glob("pykdtree-*.whl"):
        name = whl.name
        if py_tag in name and plat_tag in name:
            return whl

    return None


def _install_bundled_wheel(modules_path: str) -> bool:
    """Install the bundled pykdtree wheel into *modules_path*.

    Uses ``pip install --no-deps --target`` so only pykdtree itself is installed
    (numpy is already available in Blender's bundled Python). Returns True on
    success, False on any failure.
    """
    wheel = _find_bundled_wheel()
    if wheel is None:
        print("[ECF] deps: no bundled wheel for this platform — skipping install.")
        return False

    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m", "pip",
                "install",
                "--no-deps",
                "--upgrade",
                "--target", modules_path,
                str(wheel),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ECF] deps: bundled wheel install failed: {exc}")
        return False
    except Exception as exc:
        print(f"[ECF] deps: bundled wheel install error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attempt_import() -> bool:
    """Try to import pykdtree, installing the bundled wheel if needed.

    Called once during addon registration. The sequence is:
      1. Add the user modules directory to sys.path.
      2. Try importing pykdtree — succeeds on second+ Blender launches after
         a prior install.
      3. If import fails, install the bundled wheel and retry once.
      4. If still unavailable (unsupported platform, pip absent), log a warning
         and return False. The caller falls back to mathutils.KDTree.

    Returns True if pykdtree is now available.
    """
    modules_path = _modules_path()
    _ensure_sys_path(modules_path)

    if _try_import():
        return True

    # First launch: wheel not yet installed — install from bundle.
    print("[ECF] deps: installing pykdtree from bundled wheel…")
    installed = _install_bundled_wheel(modules_path)
    if not installed:
        print("[ECF] deps: pykdtree unavailable — preserve-follow uses mathutils.KDTree fallback.")
        return False

    _ensure_sys_path(modules_path)
    if _try_import():
        print("[ECF] deps: pykdtree installed — preserve-follow is accelerated.")
        return True

    print("[ECF] deps: pykdtree installed but import failed; will retry on next Blender launch.")
    return False
