import pathlib
import re


_WORKFLOWS_DIR = pathlib.Path(__file__).parent.parent / ".github" / "workflows"
_NIGHTLY = _WORKFLOWS_DIR / "nightly.yml"
_RELEASE = _WORKFLOWS_DIR / "release.yml"
_CI = _WORKFLOWS_DIR / "ci.yml"


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# Nightly workflow contract (from T01)
def test_has_dedicated_publish_nightly_job_after_matrix():
    text = _text(_NIGHTLY)
    assert re.search(r"(?m)^\s{2}publish-nightly:\s*$", text)
    assert "needs: [nightly]" in text


def test_publish_is_not_in_nightly_matrix_primary_leg_anymore():
    text = _text(_NIGHTLY)
    assert "if: success() && matrix.primary" not in text
    assert "Publish rolling nightly release" in text


def test_nightly_artifact_handoff_is_explicit_and_fail_closed():
    text = _text(_NIGHTLY)
    assert "Upload nightly zip artifact" in text
    assert "actions/upload-artifact@v4" in text
    assert "name: nightly-zip" in text
    assert "if-no-files-found: error" in text

    assert "Download nightly zip artifact" in text
    assert "actions/download-artifact@v4" in text
    assert "Expected nightly zip artifact was not downloaded" in text


def test_nightly_release_notes_source_blender_min_from_metadata_helper():
    text = _text(_NIGHTLY)
    assert "python tools/deploy.py meta --field blender-min" in text
    assert "BLENDER_MIN=3.2.0" not in text
    assert "BLENDER_MIN=%s" in text


# Stable release workflow contract (T02)
def test_release_uses_three_version_blender_matrix():
    text = _text(_RELEASE)
    assert "blender_version: '3.6.23'" in text
    assert "blender_version: '4.2.19'" in text
    assert "blender_version: '5.1.0'" in text


def test_release_has_single_post_matrix_publish_job():
    text = _text(_RELEASE)
    assert re.search(r"(?m)^\s{2}publish-release:\s*$", text)
    assert "needs: [release]" in text
    assert "Upload release zip artifact (single publisher lane)" in text
    assert "if: matrix.blender_version == '5.1.0'" in text


def test_release_validates_tag_before_blender_work():
    text = _text(_RELEASE)
    assert "Determine release tag" in text
    assert "Validate release tag against bl_info.version" in text
    assert "python tools/deploy.py verify-tag --tag" in text

    validate_idx = text.index("Validate release tag against bl_info.version")
    cache_idx = text.index("Cache Blender")
    assert validate_idx < cache_idx


def test_release_dispatch_and_push_tag_contract_is_explicit():
    text = _text(_RELEASE)
    assert "workflow_dispatch:" in text
    assert "inputs:" in text
    assert "push:" in text
    assert "tags:" in text
    assert "v[0-9]*.[0-9]*.[0-9]*" in text


# Fast CI workflow contract (T02)
def test_ci_stays_fast_python_only_scope():
    text = _text(_CI)
    assert "pull_request:" in text
    assert "branches-ignore:" in text
    assert "- dev" in text

    assert "actions/setup-python@v5" in text
    assert "ruff check elastic_fit/ tests/ tools/" in text
    assert "pytest tests/" in text
    assert "python tests/verify_updater.py" in text


def test_ci_remains_blender_and_release_free():
    text = _text(_CI)
    assert "setup-blender" not in text
    assert "blender-" not in text
    assert "xvfb" not in text
    assert "gh release" not in text
    assert "publish-release" not in text
