# updater.py
# In-panel update checker for Elastic Clothing Fit.
# Checks the GitHub releases API, downloads the latest release zip in the
# background, writes a one-shot Blender startup script, then relaunches Blender
# so the startup script can reinstall the add-on automatically.

import os
import sys
import threading
import subprocess

import bpy

from . import state


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_state = {
    'status':   'idle',   # idle | checking | available | up_to_date | downloading | ready | error
    'tag':      '',       # e.g. 'v1.0.5'
    'version':  None,     # tuple e.g. (1, 0, 5)
    'url':      '',       # browser_download_url of the release zip asset
    'zip_path': '',       # local path once downloaded
    'progress': 0.0,      # 0.0-1.0 during download
    'error':    '',       # short error string shown in the panel
}


def get_state():
    """Return the module-level state dict (read-only reference for the panel)."""
    return _state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_current_version():
    """Return the add-on version tuple from bl_info, e.g. (1, 0, 4)."""
    return _CURRENT_VERSION


def _schedule_redraw():
    """Tag all VIEW_3D areas for redraw from a background thread.

    Uses bpy.app.timers so the actual tag_redraw() call runs on the
    main thread (Blender's UI is not thread-safe).
    """
    def _do_redraw():
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return None  # returning None unregisters the timer

    try:
        bpy.app.timers.register(_do_redraw, first_interval=0.0)
    except Exception:
        pass


def _parse_version(tag):
    """Convert a tag string like 'v1.0.5' or '1.0.5' to a tuple (1, 0, 5).

    Returns None if the tag cannot be parsed.
    """
    tag = tag.lstrip('vV').strip()
    parts = tag.split('.')
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


# Capture the installed version once at import time on the main thread.
# Background threads cannot reliably query sys.modules or bpy.context, so
# we resolve the version here where the module environment is fully loaded.
def _read_installed_version():
    pkg = sys.modules.get(__package__)
    if pkg and hasattr(pkg, 'bl_info'):
        v = pkg.bl_info.get('version')
        if isinstance(v, (tuple, list)) and len(v) >= 2:
            return tuple(v)
    return (1, 0, 4)

_CURRENT_VERSION = _read_installed_version()


# ---------------------------------------------------------------------------
# Check for update
# ---------------------------------------------------------------------------

RELEASES_URL = (
    "https://api.github.com/repos/VRC-Staples/Elastic-Clothing-Fit/releases/latest"
)


def check_for_update():
    """Spawn a background thread that queries the GitHub releases API.

    Updates _state and schedules a panel redraw when done.
    """
    _state['status']  = 'checking'
    _state['error']   = ''
    _schedule_redraw()

    t = threading.Thread(target=_check_thread, daemon=True)
    t.start()


def _check_thread():
    """Background worker for check_for_update()."""
    try:
        import urllib.request
        import json
        import ssl

        # --- read dev overrides from add-on preferences + scene properties ---
        try:
            addon_prefs  = bpy.context.preferences.addons.get(__package__)
            dev_testing  = addon_prefs.preferences.dev_update_testing if addon_prefs else False
            p            = bpy.context.scene.efit_props
            dev_newer    = p.dev_override_newer
            dev_uptodate = p.dev_override_uptodate
        except Exception:
            dev_testing  = False
            dev_newer    = False
            dev_uptodate = False

        # --- fetch latest release from GitHub ---
        req = urllib.request.Request(
            RELEASES_URL,
            headers={'User-Agent': 'ElasticClothingFit-Updater'},
        )

        def _fetch(req):
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8'))

        try:
            data = _fetch(req)
        except Exception as ssl_err:
            # Retry with unverified SSL context as a fallback.
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))

        tag_name = data.get('tag_name', '')
        if not tag_name:
            _state['status'] = 'error'
            _state['error']  = 'No releases found'
            _schedule_redraw()
            return

        remote_version = _parse_version(tag_name)
        if remote_version is None:
            _state['status'] = 'error'
            _state['error']  = f'Could not parse version: {tag_name}'
            _schedule_redraw()
            return

        # Find the zip asset.
        assets  = data.get('assets', [])
        zip_url = ''
        for asset in assets:
            name = asset.get('name', '')
            if name.endswith('.zip'):
                zip_url = asset.get('browser_download_url', '')
                break

        if not zip_url:
            _state['status'] = 'error'
            _state['error']  = 'No zip asset in release'
            _schedule_redraw()
            return

        _state['tag']     = tag_name
        _state['version'] = remote_version
        _state['url']     = zip_url

        # --- version comparison (with dev override support) ---
        # In dev mode, overrides only apply when explicitly checked.
        # Neither override checked → fall through to the real comparison.
        current = _get_current_version()
        if dev_testing and dev_uptodate:
            _state['status'] = 'up_to_date'
        elif dev_testing and dev_newer:
            _state['status'] = 'available'
        else:
            if remote_version > current:
                _state['status'] = 'available'
            else:
                _state['status'] = 'up_to_date'

    except Exception as exc:
        _state['status'] = 'error'
        _state['error']  = str(exc)[:120]

    _schedule_redraw()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_and_prepare():
    """Spawn a background thread that streams the release zip to disk.

    Updates _state['progress'] as the download proceeds and schedules
    panel redraws so the user sees a live percentage.
    """
    _state['status']   = 'downloading'
    _state['progress'] = 0.0
    _state['error']    = ''
    _schedule_redraw()

    t = threading.Thread(target=_download_thread, daemon=True)
    t.start()


def _download_thread():
    """Background worker for download_and_prepare()."""
    zip_path = ''
    try:
        import urllib.request
        import ssl

        tag         = _state['tag']
        url         = _state['url']
        scripts_dir = bpy.utils.user_resource('SCRIPTS')
        cache_dir   = os.path.join(scripts_dir, 'efit_update_cache')
        os.makedirs(cache_dir, exist_ok=True)
        zip_path    = os.path.join(cache_dir, f'ElasticClothingFit-{tag}.zip')

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'ElasticClothingFit-Updater'},
        )

        def _open(req):
            return urllib.request.urlopen(req, timeout=60)

        try:
            resp = _open(req)
        except Exception:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            resp = urllib.request.urlopen(req, timeout=60, context=ctx)

        total = int(resp.headers.get('Content-Length', 0) or 0)
        chunk_size = 65536  # 64 KB

        downloaded = 0
        with open(zip_path, 'wb') as fh:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    _state['progress'] = downloaded / total
                _schedule_redraw()

        resp.close()
        _state['zip_path'] = zip_path
        _state['status']   = 'ready'
        _state['progress'] = 1.0

    except Exception as exc:
        # Clean up partial file.
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        _state['status'] = 'error'
        _state['error']  = str(exc)[:120]

    _schedule_redraw()


# ---------------------------------------------------------------------------
# Install and restart
# ---------------------------------------------------------------------------

def install_and_restart(reopen_filepath=''):
    """Write a one-shot startup script and relaunch Blender.

    In normal mode the startup script installs the downloaded zip.
    In dev-testing mode it installs the user-specified local zip instead.
    If reopen_filepath is provided the startup script will reopen that
    .blend file after the addon is installed.

    Called on the main thread from the operator.
    """
    try:
        addon_prefs = bpy.context.preferences.addons.get(__package__)
        dev_mode    = addon_prefs.preferences.dev_update_testing if addon_prefs else False
        p           = bpy.context.scene.efit_props
        local_zip   = p.dev_local_zip.strip() if dev_mode else ''
    except Exception:
        dev_mode  = False
        local_zip = ''

    # Determine which zip to install and whether to delete it after install.
    # local zip provided → use it, keep it (reusable across test cycles)
    # dev mode + no local zip → fall through to GitHub downloaded zip
    # normal mode → GitHub downloaded zip, delete after install
    using_local_zip = False
    if dev_mode and local_zip:
        if not os.path.isfile(local_zip):
            _state['status'] = 'error'
            _state['error']  = f'Dev mode: file not found: {local_zip}'
            return
        install_zip     = local_zip
        using_local_zip = True
    elif dev_mode:
        install_zip = _state.get('zip_path', '')
        if not install_zip or not os.path.isfile(install_zip):
            _state['status'] = 'error'
            _state['error']  = 'No downloaded zip found. Click Download first.'
            return
    else:
        install_zip = _state.get('zip_path', '')
        if not install_zip or not os.path.isfile(install_zip):
            _state['status'] = 'error'
            _state['error']  = 'Downloaded zip not found'
            return

    startup_dir = os.path.join(bpy.utils.user_resource('SCRIPTS'), 'startup')
    os.makedirs(startup_dir, exist_ok=True)
    script_path = os.path.join(startup_dir, '_efit_pending_update.py')

    # Build the startup script as a string.
    # Use repr() for the paths so backslashes are safely escaped.
    # Local dev zips are kept so they can be reused across test cycles.
    # GitHub-downloaded zips are always deleted after install.
    delete_zip_line = "" if using_local_zip else "        try: os.remove(zip_path)\n        except: pass\n"
    reopen_block = (
        "\n"
        "def _reopen():\n"
        f"    bpy.ops.wm.open_mainfile(filepath={repr(reopen_filepath)})\n"
        "\n"
        "bpy.app.timers.register(_reopen, first_interval=3.5)\n"
    ) if reopen_filepath else ""
    script_src = (
        "import bpy, os\n"
        "\n"
        "def _run():\n"
        f"    zip_path    = {repr(install_zip)}\n"
        f"    script_path = {repr(script_path)}\n"
        "    if os.path.exists(zip_path):\n"
        "        bpy.ops.preferences.addon_install(overwrite=True, filepath=zip_path)\n"
        "        bpy.ops.preferences.addon_enable(module='elastic_fit')\n"
        "        bpy.ops.wm.save_userpref()\n"
        f"{delete_zip_line}"
        "    try: os.remove(script_path)\n"
        "    except: pass\n"
        "\n"
        "bpy.app.timers.register(_run, first_interval=2.0)\n"
        f"{reopen_block}"
    )

    with open(script_path, 'w', encoding='utf-8') as fh:
        fh.write(script_src)

    # Launch a new Blender instance then quit the current one.
    # On Windows, DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP prevent the child
    # from being killed when the parent process exits via quit_blender().
    try:
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        subprocess.Popen([bpy.app.binary_path], **kwargs)
    except Exception as exc:
        _state['status'] = 'error'
        _state['error']  = f'Could not launch Blender: {exc}'
        # Remove the script so it does not run stale on a manual restart.
        try:
            os.remove(script_path)
        except Exception:
            pass
        return

    bpy.ops.wm.quit_blender()
