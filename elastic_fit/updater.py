# updater.py
# In-panel update checker for Elastic Clothing Fit.
# Checks the GitHub releases API, downloads the latest release zip in the
# background, writes a one-shot Blender startup script, then relaunches Blender
# so the startup script can reinstall the add-on automatically.

import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import subprocess
import urllib.error
import urllib.request

import bpy

from . import state


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_state = {
    'status':             'idle',  # idle | checking | available | up_to_date | downloading | ready | error
    'tag':                '',      # e.g. 'v1.0.5'
    'version':            None,    # tuple e.g. (1, 0, 5)
    'url':                '',      # browser_download_url of the release zip asset
    'zip_path':           '',      # local path once downloaded
    'progress':           0.0,     # 0.0-1.0 during download
    'error':              '',      # short error string shown in the panel
    'blender_min':        None,    # minimum blender version tuple required by remote release
    'blender_blocked':    False,   # True if installed Blender is below blender_min
    'blender_min_required': None,  # copy of blender_min for panel display
    'expected_sha256':      None,  # hex SHA-256 parsed from release notes, or None
}

# Protects all multi-key _state write sequences from concurrent read/write tears.
_state_lock = threading.Lock()

# Module-level thread refs used to enforce re-entry guards.
_active_check_thread    = None
_active_download_thread = None


def get_state():
    """Return a snapshot copy of the module-level state dict.

    Returns a shallow copy so that panel draw callbacks reading multiple keys
    do not observe torn state written by a background thread.
    """
    return dict(_state)


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
    except Exception as exc:
        print(f"[ECF] redraw schedule failed: {exc}")


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
NIGHTLY_URL = (
    "https://api.github.com/repos/VRC-Staples/Elastic-Clothing-Fit/releases/tags/nightly"
)

_NIGHTLY_MARKER = os.path.join(os.path.dirname(__file__), "_nightly.txt")

_DEV_MODE_MARKER = os.path.join(os.path.dirname(__file__), "_dev_mode")


def _is_dev_mode():
    return os.path.exists(_DEV_MODE_MARKER)


_VALID_DOWNLOAD_DOMAINS = (
    'https://github.com/',
    'https://objects.githubusercontent.com/',
    'https://github-releases.githubusercontent.com/',
)

_NIGHTLY_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)-nightly-(\d{8,12})\.zip$")

# Matches "SHA256: <64 hex chars>" anywhere in release notes body.
_SHA256_RE = re.compile(r'\bSHA256:\s*([0-9a-fA-F]{64})\b')

# Security constants
# Validates tag_name before it is spliced into a filesystem path.
# Anchored at the start; allows semver suffixes like '-nightly-20240321'.
_SAFE_TAG_RE = re.compile(r'^v?\d+\.\d+\.\d+')

# Maximum bytes accepted from a release zip download (50 MB).
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# Maximum bytes accepted from the GitHub releases API JSON response (1 MB).
# A real response is ~10 KB; this cap guards against a runaway/malicious proxy.
MAX_JSON_BYTES = 1 * 1024 * 1024


def _installed_channel():
    """Return 'nightly' if the installed addon contains the marker file, else 'stable'."""
    return 'nightly' if os.path.exists(_NIGHTLY_MARKER) else 'stable'


def _parse_nightly_asset(assets):
    """Return (version_tuple, download_url, build_ts) from a nightly release asset list.

    build_ts is the 12-digit YYYYMMDDHHMM string embedded in the filename.
    """
    for asset in assets:
        m = _NIGHTLY_RE.search(asset.get('name', ''))
        if m:
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return ver, asset['browser_download_url'], m.group(4)
    return None, None, ''


def _installed_nightly_ts():
    """Return the build timestamp (YYYYMMDDHHMM) from _nightly.txt, or '' if absent.

    _nightly.txt format: '<timestamp> <short-hash>' -- only the timestamp is used
    for version comparison; the hash is display-only.
    """
    try:
        with open(_NIGHTLY_MARKER, 'r', encoding='utf-8') as fh:
            return fh.read().strip().split()[0]
    except Exception:
        return ''


def _parse_blender_min(body):
    """Parse BLENDER_MIN=X.Y.Z from release notes body. Returns tuple or None."""
    if not body:
        return None
    m = re.search(r'BLENDER_MIN=(\d+)\.(\d+)\.(\d+)', body)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _validate_dev_url(url):
    """Validate dev_update_url against a localhost-only allowlist.

    Only http/https scheme is accepted, and the host must be localhost,
    127.0.0.1, or a *.local mDNS hostname — never a public internet address.

    Raises ValueError with a descriptive message on any mismatch.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(
            f"dev_update_url scheme must be http or https, got: {parsed.scheme!r}"
        )
    host = parsed.hostname or ''
    if host not in ('localhost', '127.0.0.1') and not host.endswith('.local'):
        raise ValueError(
            f"dev_update_url host must be localhost/127.0.0.1/*.local, got: {host!r}"
        )


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject HTTP redirects that point outside _VALID_DOWNLOAD_DOMAINS.

    GitHub's CDN (objects.githubusercontent.com, github-releases.githubusercontent.com)
    is the only expected redirect target.  Any other domain indicates a potential
    redirect attack and should fail loudly rather than silently following.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not any(newurl.startswith(d) for d in _VALID_DOWNLOAD_DOMAINS):
            raise urllib.error.URLError(
                f"Redirect to untrusted domain blocked: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen_with_retry(req_or_opener, req=None, timeout=10, max_retries=3):
    """Open a URL with exponential backoff retry.

    Works with both plain ``urllib.request.urlopen`` calls (pass a Request
    object as ``req_or_opener``) and opener.open calls (pass the opener as
    ``req_or_opener`` and the Request as ``req``).

    Retries up to *max_retries* times with exponential backoff: 1s, 2s, 4s …
    Re-raises the last exception when all attempts are exhausted.
    """
    for attempt in range(max_retries):
        try:
            if req is not None:
                return req_or_opener.open(req, timeout=timeout)
            else:
                return urllib.request.urlopen(req_or_opener, timeout=timeout)
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, OSError):
                raise
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)


def check_for_update():
    """Spawn a background thread that queries the GitHub releases API.

    Updates _state and schedules a panel redraw when done.
    Re-entry guarded: a second call while a check is in-flight is a no-op.
    No-op in headless/background mode: bpy.ops.wm.open_mainfile() discards the
    Python environment while the thread is live, causing a use-after-free crash
    in CPython's GC. Background Blender has no update panel to show anyway.
    """
    if bpy.app.background:
        return
    global _active_check_thread
    if _active_check_thread is not None and _active_check_thread.is_alive():
        return

    # Read bpy.* values on the main thread before the thread starts.
    try:
        p            = bpy.context.scene.efit_props
        use_nightly  = p.use_nightly_channel
        dev_url_base = p.dev_update_url.strip() if _is_dev_mode() else ''
    except Exception:
        use_nightly  = False
        dev_url_base = ''

    blender_version = bpy.app.version

    if dev_url_base:
        try:
            _validate_dev_url(dev_url_base)
        except ValueError as e:
            with _state_lock:
                _state['status'] = 'error'
                _state['error']  = str(e)[:120]
            _schedule_redraw()
            return

    with _state_lock:
        _state['status'] = 'checking'
        _state['error']  = ''
    _schedule_redraw()

    t = threading.Thread(
        target=_check_thread,
        kwargs={
            'use_nightly':     use_nightly,
            'dev_url_base':    dev_url_base,
            'blender_version': blender_version,
        },
        daemon=True,
    )
    _active_check_thread = t
    t.start()


def _check_thread(use_nightly=False, dev_url_base='', blender_version=(0, 0, 0)):
    """Background worker for check_for_update().

    All bpy.* accesses have been removed; values are passed as arguments by
    the main-thread caller so this function is safe to run in a daemon thread.
    """
    try:
        current = _get_current_version()

        def _fetch(url):
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'ElasticClothingFit-Updater',
                    'Accept-Encoding': 'gzip',
                },
            )
            opener = urllib.request.build_opener(_AllowlistRedirectHandler)
            with contextlib.closing(_urlopen_with_retry(opener, req=req, timeout=10)) as resp:
                raw = resp.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("Response too large")
            if resp.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            return json.loads(raw.decode('utf-8'))

        # Build API URLs from pre-resolved channel preference
        if dev_url_base:
            _base        = dev_url_base.rstrip('/')
            releases_url = _base + '/repos/VRC-Staples/Elastic-Clothing-Fit/releases/latest'
            nightly_url  = _base + '/repos/VRC-Staples/Elastic-Clothing-Fit/releases/tags/nightly'
        else:
            releases_url = RELEASES_URL
            nightly_url  = NIGHTLY_URL

        installed_channel = _installed_channel()
        remote_ts = ''

        if use_nightly:
            data = _fetch(nightly_url)
            assets = data.get('assets', [])
            remote_version, zip_url, remote_ts = _parse_nightly_asset(assets)
            if remote_version is None or not zip_url:
                with _state_lock:
                    _state['status'] = 'error'
                    _state['error']  = 'No nightly zip asset found'
                _schedule_redraw()
                return
            blender_min = _parse_blender_min(data.get('body', ''))
            tag_name = data.get('tag_name', 'nightly')
        else:
            data = _fetch(releases_url)
            tag_name = data.get('tag_name', '')
            if not tag_name:
                with _state_lock:
                    _state['status'] = 'error'
                    _state['error']  = 'No releases found'
                _schedule_redraw()
                return
            remote_version = _parse_version(tag_name)
            if remote_version is None:
                with _state_lock:
                    _state['status'] = 'error'
                    _state['error']  = f'Could not parse version: {tag_name}'
                _schedule_redraw()
                return
            assets  = data.get('assets', [])
            zip_url = ''
            for asset in assets:
                name = asset.get('name', '')
                if name.endswith('.zip'):
                    zip_url = asset.get('browser_download_url', '')
                    break
            blender_min = _parse_blender_min(data.get('body', ''))

        if not zip_url:
            with _state_lock:
                _state['status'] = 'error'
                _state['error']  = 'No zip asset in release'
            _schedule_redraw()
            return

        valid_domains = _VALID_DOWNLOAD_DOMAINS + (('http://localhost',) if _is_dev_mode() else ())
        if not any(zip_url.startswith(d) for d in valid_domains):
            with _state_lock:
                _state['status'] = 'error'
                _state['error']  = 'Unexpected download URL domain'
            _schedule_redraw()
            return

        # Parse optional SHA-256 from release notes ("SHA256: <64 hex chars>").
        # Stored for post-download verification; None means no hash available.
        body = data.get('body', '') or ''
        sha256_match = _SHA256_RE.search(body)

        # Write all discovered metadata atomically — combines expected_sha256,
        # tag, version, url, blender_min, and blender_blocked into one lock
        # acquisition to prevent the panel from reading a partially-updated state.
        with _state_lock:
            _state['expected_sha256']    = sha256_match.group(1).lower() if sha256_match else None
            _state['tag']                = tag_name
            _state['version']            = remote_version
            _state['url']                = zip_url
            _state['blender_min']        = blender_min
            _state['blender_min_required'] = blender_min
            _state['blender_blocked']    = bool(blender_min and blender_version < blender_min)

        # --- version comparison (single-key writes, no lock needed) ---
        if use_nightly:
            # When fetching nightly: compare semver first, then build timestamp
            # so multiple nightlies on the same day are handled correctly.
            if remote_version > current:
                _state['status'] = 'available'
            elif remote_version == current and installed_channel == 'nightly':
                installed_ts = _installed_nightly_ts()
                _state['status'] = 'available' if remote_ts > installed_ts else 'up_to_date'
            else:
                _state['status'] = 'available' if remote_version >= current else 'up_to_date'
        else:
            # When fetching stable: if we're on nightly of the same version,
            # switching to stable is an upgrade.
            if installed_channel == 'nightly' and remote_version >= current:
                _state['status'] = 'available'
            elif remote_version > current:
                _state['status'] = 'available'
            else:
                _state['status'] = 'up_to_date'

    except Exception as exc:
        with _state_lock:
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
    Re-entry guarded: a second call while a download is in-flight is a no-op.
    No-op in headless/background mode for the same reason as check_for_update.
    """
    if bpy.app.background:
        return
    global _active_download_thread
    if _active_download_thread is not None and _active_download_thread.is_alive():
        return

    # Resolve bpy.* resource path on the main thread before the thread starts.
    scripts_dir = bpy.utils.user_resource('SCRIPTS')

    with _state_lock:
        _state['status']   = 'downloading'
        _state['progress'] = 0.0
        _state['error']    = ''
    _schedule_redraw()

    t = threading.Thread(
        target=_download_thread,
        kwargs={'scripts_dir': scripts_dir},
        daemon=True,
    )
    _active_download_thread = t
    t.start()


def _download_thread(scripts_dir=''):
    """Background worker for download_and_prepare().

    All bpy.* accesses have been removed; scripts_dir is passed as an argument
    by the main-thread caller so this function is safe to run in a daemon thread.
    """
    zip_path = ''
    try:
        tag       = _state['tag']
        url       = _state['url']
        cache_dir = os.path.join(scripts_dir, 'efit_update_cache')
        os.makedirs(cache_dir, exist_ok=True)
        # Validate tag_name before splicing it into a filesystem path to prevent
        # path traversal.  Tags like '../../etc/passwd' must be rejected.
        if not _SAFE_TAG_RE.match(tag):
            with _state_lock:
                _state['status'] = 'error'
                _state['error']  = 'Invalid tag format'
            _schedule_redraw()
            return
        zip_path  = os.path.join(cache_dir, f'ElasticClothingFit-{tag}.zip')

        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'ElasticClothingFit-Updater',
                'Accept-Encoding': 'gzip',
            },
        )

        def _open(req):
            opener = urllib.request.build_opener(_AllowlistRedirectHandler)
            resp = _urlopen_with_retry(opener, req=req, timeout=60)
            if resp.headers.get('Content-Encoding') == 'gzip':
                # Wrap the response so that resp.read(chunk_size) transparently
                # decompresses — GzipFile expects a file-like object.
                return gzip.GzipFile(fileobj=resp)
            return resp

        resp = _open(req)

        total      = int(resp.headers.get('Content-Length', 0) or 0)
        chunk_size = 65536  # 64 KB

        # Initialise SHA-256 hash so we compute the digest inline during the
        # write loop — no second full-file read needed after download completes.
        h = hashlib.sha256()

        downloaded         = 0
        _last_redraw_pct   = 0.0
        with contextlib.closing(resp), open(zip_path, 'wb') as fh:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                downloaded += len(chunk)
                # Abort if the download exceeds the size cap — prevents an
                # unbounded write that could fill the disk.
                if downloaded > MAX_DOWNLOAD_BYTES:
                    fh.close()
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass
                    with _state_lock:
                        _state['status'] = 'error'
                        _state['error']  = 'Download too large'
                    _schedule_redraw()
                    return
                if total > 0:
                    _state['progress'] = downloaded / total
                # Throttle redraws to ≥5% progress increments to reduce UI thrash.
                if _state['progress'] - _last_redraw_pct >= 0.05:
                    _schedule_redraw()
                    _last_redraw_pct = _state['progress']

        # Verify SHA-256 against the hash embedded in the release notes.
        # If the release provides no hash, the download is rejected outright —
        # silently skipping verification would allow a tampered zip to be installed.
        expected = _state.get('expected_sha256')
        if expected:
            if h.hexdigest() != expected:
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                with _state_lock:
                    _state['status'] = 'error'
                    _state['error']  = 'SHA-256 mismatch -- download may be corrupt'
                _schedule_redraw()
                return
        else:
            with _state_lock:
                _state['status'] = 'error'
                _state['error']  = 'Release has no SHA-256 hash \u2014 cannot verify download integrity'
            _schedule_redraw()
            return

        with _state_lock:
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
        with _state_lock:
            _state['status'] = 'error'
            _state['error']  = str(exc)[:120]

    _schedule_redraw()


# ---------------------------------------------------------------------------
# Install and restart
# ---------------------------------------------------------------------------

def install_and_restart(reopen_filepath=''):
    """Write a one-shot startup script and relaunch Blender.

    The startup script installs the downloaded zip.
    If reopen_filepath is provided the startup script will reopen that
    .blend file after the addon is installed.

    Paths are serialised via a JSON sidecar file (_efit_update_paths.json)
    written atomically with os.replace() — no path embedding in the script
    source string.  The static template script reads the sidecar at timer
    callback time (deferred), not at import time.

    Called on the main thread from the operator.
    """
    install_zip = _state.get('zip_path', '')
    if not install_zip or not os.path.isfile(install_zip):
        with _state_lock:
            _state['status'] = 'error'
            _state['error']  = 'Downloaded zip not found'
        return

    startup_dir = os.path.join(bpy.utils.user_resource('SCRIPTS'), 'startup')
    os.makedirs(startup_dir, exist_ok=True)
    script_path  = os.path.join(startup_dir, '_efit_pending_update.py')
    sidecar_path = os.path.join(startup_dir, '_efit_update_paths.json')

    # Write sidecar JSON atomically so the startup script never reads a
    # half-written file.  Always include reopen_filepath (empty string if not
    # reopening); the static template checks `if reopen_filepath:` at runtime.
    sidecar_data = {
        'zip_path':        install_zip,
        'script_path':     script_path,
        'reopen_filepath': reopen_filepath or '',
        'expected_sha256': _state.get('expected_sha256'),
    }
    tmp_sidecar = sidecar_path + '.tmp'
    with open(tmp_sidecar, 'w', encoding='utf-8') as fh:
        json.dump(sidecar_data, fh)
    os.replace(tmp_sidecar, sidecar_path)

    # Static template — no f-string path interpolation, no dynamic path injection.
    # Paths are loaded from the sidecar JSON at timer-callback time.
    script_src = (
        "import bpy, os, json\n"
        "\n"
        "def _run():\n"
        "    sidecar = os.path.join(os.path.dirname(__file__), '_efit_update_paths.json')\n"
        "    with open(sidecar) as f:\n"
        "        d = json.load(f)\n"
        "    zip_path = d['zip_path']\n"
        "    script_path = d['script_path']\n"
        "    reopen_filepath = d.get('reopen_filepath', '')\n"
        "    if os.path.exists(zip_path):\n"
        "        bpy.ops.preferences.addon_install(overwrite=True, filepath=zip_path)\n"
        "        bpy.ops.preferences.addon_enable(module='elastic_fit')\n"
        "        bpy.ops.wm.save_userpref()\n"
        "        try: os.remove(zip_path)\n"
        "        except: pass\n"
        "    try: os.remove(script_path)\n"
        "    except: pass\n"
        "    try: os.remove(sidecar)\n"
        "    except: pass\n"
        "    if reopen_filepath:\n"
        "        def _reopen():\n"
        "            bpy.ops.wm.open_mainfile(filepath=reopen_filepath)\n"
        "        bpy.app.timers.register(_reopen, first_interval=3.5)\n"
        "\n"
        "bpy.app.timers.register(_run, first_interval=2.0)\n"
    )

    # Write startup script atomically.
    tmp_script = script_path + '.tmp'
    with open(tmp_script, 'w', encoding='utf-8') as fh:
        fh.write(script_src)
    os.replace(tmp_script, script_path)

    # Guard: verify Blender binary exists before attempting Popen.
    if not os.path.isfile(bpy.app.binary_path):
        with _state_lock:
            _state['status'] = 'error'
            _state['error']  = f'Blender binary not found: {bpy.app.binary_path}'
        try:
            os.remove(script_path)
        except Exception:
            pass
        try:
            os.remove(sidecar_path)
        except Exception:
            pass
        return

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
        with _state_lock:
            _state['status'] = 'error'
            _state['error']  = f'Could not launch Blender: {exc}'
        # Remove the script and sidecar so they do not run stale on a manual restart.
        try:
            os.remove(script_path)
        except Exception:
            pass
        try:
            os.remove(sidecar_path)
        except Exception:
            pass
        return

    bpy.ops.wm.quit_blender()
