import pathlib
import re


_WORKFLOW = pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "nightly.yml"


def _nightly_text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_has_dedicated_publish_nightly_job_after_matrix():
    text = _nightly_text()
    assert re.search(r"(?m)^\s{2}publish-nightly:\s*$", text)
    assert "needs: [nightly]" in text


def test_publish_is_not_in_matrix_primary_leg_anymore():
    text = _nightly_text()
    assert "if: success() && matrix.primary" not in text
    assert "Publish rolling nightly release" in text


def test_artifact_handoff_is_explicit_and_fail_closed():
    text = _nightly_text()
    assert "Upload nightly zip artifact" in text
    assert "actions/upload-artifact@v4" in text
    assert "name: nightly-zip" in text
    assert "if-no-files-found: error" in text

    assert "Download nightly zip artifact" in text
    assert "actions/download-artifact@v4" in text
    assert "Expected nightly zip artifact was not downloaded" in text


def test_release_notes_source_blender_min_from_metadata_helper():
    text = _nightly_text()
    assert "python tools/deploy.py meta --field blender-min" in text
    assert "BLENDER_MIN=3.2.0" not in text
    assert "BLENDER_MIN=%s" in text
