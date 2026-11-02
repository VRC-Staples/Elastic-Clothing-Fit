import pathlib


_WORKFLOWS_DIR = pathlib.Path(__file__).parent.parent / ".github" / "workflows"
_RELEASE = _WORKFLOWS_DIR / "release.yml"
_CI = _WORKFLOWS_DIR / "ci.yml"


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_ci_triggers_on_push_to_main_and_prs():
    text = _text(_CI)
    assert "push:" in text
    assert "- main" in text
    assert "pull_request:" in text


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
