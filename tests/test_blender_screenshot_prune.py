# tests/test_blender_screenshot_prune.py
#
# Unit tests for the _prune_old_screenshot_sets logic in tools/blender_screenshot.py.
#
# Because blender_screenshot.py imports bpy at module level it cannot be imported
# directly in a plain Python context.  Instead we copy the pruning function verbatim
# here so it can be exercised with pytest and tmp_path, keeping tests fast and
# independent of a Blender installation.

import re
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Extracted pruning logic (mirrors tools/blender_screenshot.py exactly)
# ---------------------------------------------------------------------------

_MAX_SCREENSHOT_SETS = 25


def _prune_old_screenshot_sets(fit_test_root: Path, max_sets: int) -> list:
    """Remove oldest timestamp subdirectories, keeping at most *max_sets*.

    Returns the list of Path objects that were deleted (for test assertions).
    """
    pattern = re.compile(r"^\d{8}_\d{6}$")

    try:
        entries = [
            d for d in fit_test_root.iterdir()
            if d.is_dir() and pattern.match(d.name)
        ]
    except Exception:
        return []

    if len(entries) <= max_sets:
        return []

    entries.sort(key=lambda d: d.name)
    to_delete = entries[: len(entries) - max_sets]

    deleted = []
    for old_dir in to_delete:
        try:
            shutil.rmtree(old_dir)
            deleted.append(old_dir)
        except Exception:
            pass
    return deleted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sets(base: Path, names: list) -> list:
    """Create empty timestamp subdirectories and return their Path objects."""
    dirs = []
    for name in names:
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        dirs.append(d)
    return dirs


def _timestamp(n: int) -> str:
    """Return a valid YYYYMMDD_HHMMSS name for test set number *n* (1-indexed)."""
    return f"20260101_{n:06d}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPruneOldScreenshotSets:

    def test_no_pruning_when_below_limit(self, tmp_path):
        """With fewer than max_sets dirs, nothing is deleted."""
        names = [_timestamp(i) for i in range(1, 25)]   # 24 sets
        _make_sets(tmp_path, names)
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert deleted == []
        assert len(list(tmp_path.iterdir())) == 24

    def test_no_pruning_when_exactly_at_limit(self, tmp_path):
        """Exactly max_sets dirs — nothing deleted."""
        names = [_timestamp(i) for i in range(1, 26)]   # 25 sets
        _make_sets(tmp_path, names)
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert deleted == []
        assert len(list(tmp_path.iterdir())) == 25

    def test_prunes_one_when_one_over_limit(self, tmp_path):
        """26 dirs → oldest 1 removed, 25 remain."""
        names = [_timestamp(i) for i in range(1, 27)]   # 26 sets
        _make_sets(tmp_path, names)
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert len(deleted) == 1
        assert deleted[0].name == _timestamp(1)          # oldest removed
        remaining = sorted(d.name for d in tmp_path.iterdir())
        assert len(remaining) == 25
        assert _timestamp(1) not in remaining
        assert _timestamp(26) in remaining

    def test_prunes_multiple_oldest(self, tmp_path):
        """30 dirs → 5 oldest removed, 25 remain."""
        names = [_timestamp(i) for i in range(1, 31)]   # 30 sets
        _make_sets(tmp_path, names)
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert len(deleted) == 5
        deleted_names = {d.name for d in deleted}
        for i in range(1, 6):
            assert _timestamp(i) in deleted_names        # oldest 5 gone
        remaining = sorted(d.name for d in tmp_path.iterdir())
        assert len(remaining) == 25
        assert _timestamp(6) in remaining                # 6th survives
        assert _timestamp(30) in remaining               # newest survives

    def test_non_timestamp_dirs_ignored(self, tmp_path):
        """Directories not matching YYYYMMDD_HHMMSS are left untouched."""
        # 26 valid timestamp dirs + 2 unrelated dirs
        ts_names = [_timestamp(i) for i in range(1, 27)]
        other_names = ["some_other_dir", "latest"]
        _make_sets(tmp_path, ts_names + other_names)
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        # Only timestamp dirs counted; 1 oldest removed
        assert len(deleted) == 1
        assert deleted[0].name == _timestamp(1)
        # Unrelated dirs survive
        assert (tmp_path / "some_other_dir").exists()
        assert (tmp_path / "latest").exists()
        # 25 timestamp dirs + 2 other = 27 total
        assert len(list(tmp_path.iterdir())) == 27

    def test_empty_directory_is_safe(self, tmp_path):
        """Empty fit-test dir — no crash, no deletions."""
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert deleted == []

    def test_nonexistent_directory_is_safe(self, tmp_path):
        """Non-existent root — no crash, returns empty list."""
        missing = tmp_path / "does_not_exist"
        deleted = _prune_old_screenshot_sets(missing, 25)
        assert deleted == []

    def test_max_sets_one(self, tmp_path):
        """Edge case: keep only 1 most-recent set."""
        names = [_timestamp(i) for i in range(1, 6)]    # 5 sets
        _make_sets(tmp_path, names)
        deleted = _prune_old_screenshot_sets(tmp_path, 1)
        assert len(deleted) == 4
        remaining = list(tmp_path.iterdir())
        assert len(remaining) == 1
        assert remaining[0].name == _timestamp(5)        # newest survives

    def test_newest_always_survives(self, tmp_path):
        """The most-recent (lexicographically largest) dir is never pruned."""
        names = [_timestamp(i) for i in range(1, 100)]  # 99 sets
        _make_sets(tmp_path, names)
        _prune_old_screenshot_sets(tmp_path, 25)
        assert (tmp_path / _timestamp(99)).exists()

    def test_files_in_root_not_counted(self, tmp_path):
        """Regular files in fit-test root don't affect the dir count."""
        names = [_timestamp(i) for i in range(1, 27)]
        _make_sets(tmp_path, names)
        # add some stray files
        (tmp_path / "README.txt").write_text("note")
        (tmp_path / ".gitkeep").write_text("")
        deleted = _prune_old_screenshot_sets(tmp_path, 25)
        assert len(deleted) == 1
        # Files survive
        assert (tmp_path / "README.txt").exists()
        assert (tmp_path / ".gitkeep").exists()
