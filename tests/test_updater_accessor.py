"""Tests for updater.get_status() accessor logic.

The actual updater module imports bpy (Blender's Python API) which is not
available outside a Blender process.  We therefore test the *logic* of
get_status() by extracting it as a pure-Python helper that operates on a
plain dict — identical to what updater.get_status() does on _state.

This mirrors the pattern used in test_run_all_timeout.py where
_parse_suite_output is extracted verbatim for testability.
"""


# ---------------------------------------------------------------------------
# Pure-Python extraction of get_status logic
# ---------------------------------------------------------------------------

def get_status(state_dict: dict) -> str:
    """Equivalent to updater.get_status(), parameterised for testability.

    updater.get_status() does exactly: return _state['status']
    """
    return state_dict['status']


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_status_string():
    """get_status returns the string value stored at the 'status' key."""
    state = {'status': 'idle', 'tag': '', 'progress': 0.0}
    result = get_status(state)
    assert result == 'idle', f"expected 'idle', got {result!r}"


def test_returns_available():
    """get_status returns 'available' when the update has been found."""
    state = {'status': 'available', 'tag': 'v1.2.0', 'progress': 0.0}
    result = get_status(state)
    assert result == 'available', f"expected 'available', got {result!r}"


def test_returns_ready():
    """get_status returns 'ready' when the download is complete."""
    state = {'status': 'ready', 'tag': 'v1.2.0', 'progress': 1.0, 'zip_path': '/tmp/x.zip'}
    result = get_status(state)
    assert result == 'ready', f"expected 'ready', got {result!r}"


def test_returns_correct_key_not_full_dict():
    """get_status returns a string, NOT the full state dict."""
    state = {'status': 'checking', 'tag': '', 'progress': 0.0}
    result = get_status(state)
    # Must be the string, not the dict itself
    assert isinstance(result, str), f"expected str, got {type(result).__name__}"
    assert result != state, "get_status must not return the entire state dict"


def test_all_valid_status_values():
    """All documented status strings are returned unchanged."""
    valid_statuses = [
        'idle', 'checking', 'available', 'up_to_date',
        'downloading', 'ready', 'error',
    ]
    for status in valid_statuses:
        state = {'status': status}
        result = get_status(state)
        assert result == status, f"expected {status!r}, got {result!r}"
