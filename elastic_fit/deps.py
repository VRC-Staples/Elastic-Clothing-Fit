# deps.py
# Optional dependency management for performance-critical third-party packages.
#
# pykdtree is a fast KD-tree with OpenMP-enabled batch queries (~66 KB wheel).
# It replaces the sequential mathutils.KDTree.find_n loop in the preserve-follow
# section and cuts ~60-130ms per preview tick down to ~1-2ms on ECF_Test scale.
#
# Import rules:
#   - Import this module at the top of preview.py and pipeline.py.
#   - Check `deps.PYKDTREE_AVAILABLE` before using `deps.BatchKDTree`.
#   - When unavailable, fall back to mathutils.KDTree (existing behaviour).

import sys
import os
import site
import subprocess
import threading

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
    """Add modules_path to sys.path so Blender can find installed packages."""
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attempt_import() -> bool:
    """Try to import pykdtree from the Blender user scripts/modules directory.

    Called once during addon registration. Adds the user modules path to
    sys.path first so packages installed via ``install_async()`` are found on
    subsequent Blender sessions without a restart.

    Returns True if pykdtree is now available.
    """
    _ensure_sys_path(_modules_path())
    return _try_import()


def install_async(on_complete=None) -> None:
    """Install pykdtree into Blender's user scripts/modules directory in a
    background thread so the UI stays responsive.

    Args:
        on_complete: optional callable(success: bool, message: str) invoked on
                     the main thread (via bpy.app.timers) when the install
                     finishes.
    """
    modules_path = _modules_path()

    def _run():
        success = False
        message = ""
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m", "pip",
                    "install",
                    "--upgrade",
                    "--target", modules_path,
                    "pykdtree",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _ensure_sys_path(modules_path)
            success = _try_import()
            message = "pykdtree installed — preserve-follow is now accelerated." if success \
                      else "pykdtree installed but import failed; please restart Blender."
        except subprocess.CalledProcessError as exc:
            message = f"pykdtree install failed: {exc}"
        except Exception as exc:
            message = f"pykdtree install error: {exc}"

        print(f"[ECF] deps: {message}")

        if on_complete is not None:
            def _notify():
                on_complete(success, message)
                return None  # do not reschedule
            bpy.app.timers.register(_notify, first_interval=0.0)

    threading.Thread(target=_run, daemon=True).start()
