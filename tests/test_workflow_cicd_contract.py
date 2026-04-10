import pathlib
import re


_WORKFLOWS_DIR = pathlib.Path(__file__).parent.parent / ".github" / "workflows"
_NIGHTLY = _WORKFLOWS_DIR / "nightly.yml"
_RELEASE = _WORKFLOWS_DIR / "release.yml"
_CI = _WORKFLOWS_DIR / "ci.yml"


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Nightly workflow contract
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stable release workflow contract
# ---------------------------------------------------------------------------

def test_release_triggers_on_ci_completion_on_main():
    text = _text(_RELEASE)
    assert "workflow_run:" in text
    assert 'workflows: ["CI"]' in text
    assert "types: [completed]" in text
    assert "branches: [main]" in text


def test_release_triggers_on_workflow_dispatch_with_hotfix_input():
    text = _text(_RELEASE)
    assert "workflow_dispatch:" in text
    assert "hotfix:" in text


def test_release_skips_when_ci_failed():
    text = _text(_RELEASE)
    assert "workflow_run.conclusion == 'success'" in text


def test_release_reads_version_from_bl_info():
    text = _text(_RELEASE)
    assert "python tools/deploy.py meta --field version" in text


def test_release_compares_version_to_latest_release():
    text = _text(_RELEASE)
    assert "releases/latest" in text
    assert "should_release" in text


def test_release_sources_blender_min_from_metadata():
    text = _text(_RELEASE)
    assert "python tools/deploy.py meta --field blender-min" in text
    assert "BLENDER_MIN" in text


def test_release_creates_tag_automatically():
    text = _text(_RELEASE)
    assert "create_tag" in text
    assert "git/refs" in text


def test_release_has_duplicate_tag_guard():
    text = _text(_RELEASE)
    assert "Guard against duplicate tag" in text
    assert "already exists" in text


def test_release_never_runs_blender():
    text = _text(_RELEASE)
    assert "xvfb" not in text
    assert "blender-cache" not in text
    assert "Download Blender" not in text


def test_release_build_uses_skip_test():
    text = _text(_RELEASE)
    assert "--skip-test" in text


def test_release_never_publishes_nightly():
    text = _text(_RELEASE)
    assert "publish-nightly" not in text
    assert "--nightly" not in text


# ---------------------------------------------------------------------------
# CI workflow contract
# ---------------------------------------------------------------------------

def test_ci_triggers_on_push_to_main_and_prs():
    text = _text(_CI)
    assert "push:" in text
    assert "- main" in text
    assert "pull_request:" in text


def test_ci_does_not_fire_on_dev_push():
    text = _text(_CI)
    assert "branches-ignore:" not in text


def test_ci_runs_full_blender_matrix():
    text = _text(_CI)
    assert 'blender_version: "3.6.23"' in text
    assert 'blender_version: "4.2.19"' in text
    assert 'blender_version: "5.1.0"' in text
    assert "xvfb" in text
    assert "run_all.py" in text
    assert "--programmatic" in text
    assert "--expected-suites 7" in text
    assert "--min-checks 240" in text


def test_ci_baseline_steps():
    text = _text(_CI)
    assert "actions/setup-python@v5" in text
    assert "ruff check elastic_fit/ tests/ tools/" in text
    assert "pytest tests/" in text
    assert "python tests/verify_updater.py" in text


def test_ci_never_publishes_a_release():
    text = _text(_CI)
    assert "gh release" not in text
    assert "publish-release" not in text
    assert "publish-nightly" not in text
