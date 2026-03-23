# tests/test_updater_helpers.py
#
# Unit tests for pure-Python helper functions in elastic_fit/updater.py.
#
# updater.py imports bpy at module level so it cannot be imported directly
# in a plain Python context.  The functions under test are extracted here
# verbatim (they have no bpy dependency) so the tests run in the standard
# pytest venv without Blender.
#
# Covered:
#   _parse_version        -- tag string → version tuple (or None)
#   _parse_blender_min    -- release notes body → (X, Y, Z) tuple (or None)
#   _parse_nightly_asset  -- asset list → (version_tuple, url, build_ts)
#   _installed_nightly_ts -- reads _nightly.txt timestamp field
#   _installed_channel    -- 'stable' vs 'nightly' based on marker file presence

import os
import re
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Extracted logic (verbatim from elastic_fit/updater.py)
# ---------------------------------------------------------------------------

def _parse_version(tag):
    tag = tag.lstrip('vV').strip()
    parts = tag.split('.')
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


_NIGHTLY_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)-nightly-(\d{8,12})\.zip$")


def _parse_nightly_asset(assets):
    for asset in assets:
        m = _NIGHTLY_RE.search(asset.get('name', ''))
        if m:
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return ver, asset['browser_download_url'], m.group(4)
    return None, None, ''


def _installed_nightly_ts(marker_path):
    """Test-friendly version: accepts marker_path instead of using the module constant."""
    try:
        with open(marker_path, 'r', encoding='utf-8') as fh:
            return fh.read().strip().split()[0]
    except Exception:
        return ''


def _installed_channel(marker_path):
    """Test-friendly version: accepts marker_path instead of using the module constant."""
    return 'nightly' if os.path.exists(marker_path) else 'stable'


def _parse_blender_min(body):
    if not body:
        return None
    m = re.search(r'BLENDER_MIN=(\d+)\.(\d+)\.(\d+)', body)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


# ---------------------------------------------------------------------------
# Tests: _parse_version
# ---------------------------------------------------------------------------

class TestParseVersion:

    def test_standard_v_prefix(self):
        assert _parse_version('v1.0.5') == (1, 0, 5)

    def test_uppercase_v_prefix(self):
        assert _parse_version('V2.3.1') == (2, 3, 1)

    def test_no_prefix(self):
        assert _parse_version('1.0.5') == (1, 0, 5)

    def test_multi_digit_parts(self):
        assert _parse_version('v10.20.300') == (10, 20, 300)

    def test_two_part_version(self):
        assert _parse_version('v1.0') == (1, 0)

    def test_four_part_version(self):
        assert _parse_version('v1.0.5.1') == (1, 0, 5, 1)

    def test_zero_version(self):
        assert _parse_version('v0.0.0') == (0, 0, 0)

    def test_leading_whitespace_stripped(self):
        # lstrip('vV') + strip() handles leading/trailing whitespace
        assert _parse_version('v1.0.5 ') == (1, 0, 5)

    def test_non_numeric_part_returns_none(self):
        assert _parse_version('v1.0.alpha') is None

    def test_empty_string_returns_none(self):
        assert _parse_version('') is None

    def test_only_prefix_returns_none(self):
        # 'v' stripped → '' → split('.') → [''] → int('') raises ValueError
        assert _parse_version('v') is None

    def test_garbage_string_returns_none(self):
        assert _parse_version('not-a-version') is None

    def test_version_comparison_ordering(self):
        """Parsed tuples support correct version ordering."""
        assert _parse_version('v1.0.5') > _parse_version('v1.0.4')
        assert _parse_version('v2.0.0') > _parse_version('v1.9.9')
        assert _parse_version('v1.0.5') == _parse_version('v1.0.5')


# ---------------------------------------------------------------------------
# Tests: _parse_blender_min
# ---------------------------------------------------------------------------

class TestParseBlenderMin:

    def test_standard_format(self):
        body = 'Some notes\nBLENDER_MIN=3.2.0\nMore notes'
        assert _parse_blender_min(body) == (3, 2, 0)

    def test_at_end_of_body(self):
        body = 'Release notes\n\nBLENDER_MIN=4.2.0'
        assert _parse_blender_min(body) == (4, 2, 0)

    def test_at_start_of_body(self):
        body = 'BLENDER_MIN=5.1.0\n\nSome details'
        assert _parse_blender_min(body) == (5, 1, 0)

    def test_multi_digit_version(self):
        body = 'BLENDER_MIN=10.20.300'
        assert _parse_blender_min(body) == (10, 20, 300)

    def test_none_body_returns_none(self):
        assert _parse_blender_min(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_blender_min('') is None

    def test_no_marker_in_body_returns_none(self):
        body = 'Installation instructions\nSHA256: abc123...'
        assert _parse_blender_min(body) is None

    def test_malformed_marker_missing_patch_returns_none(self):
        body = 'BLENDER_MIN=3.2'  # only two parts — pattern requires X.Y.Z
        assert _parse_blender_min(body) is None

    def test_non_numeric_part_returns_none(self):
        body = 'BLENDER_MIN=3.x.0'
        assert _parse_blender_min(body) is None

    def test_marker_embedded_in_longer_text(self):
        """Marker is found anywhere in the body text."""
        body = (
            '## v1.0.6\n\n'
            '### Installation\n'
            '1. Download the zip\n\n'
            'SHA256: abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n\n'
            'BLENDER_MIN=4.1.0'
        )
        assert _parse_blender_min(body) == (4, 1, 0)

    def test_returns_first_occurrence(self):
        """When multiple markers exist, the first is returned (re.search behaviour)."""
        body = 'BLENDER_MIN=3.2.0\nBLENDER_MIN=4.0.0'
        assert _parse_blender_min(body) == (3, 2, 0)


# ---------------------------------------------------------------------------
# Tests: _parse_nightly_asset
# ---------------------------------------------------------------------------

class TestParseNightlyAsset:

    def _asset(self, name, url='https://github.com/example/releases/download/nightly/' ):
        return {'name': name, 'browser_download_url': url + name}

    def test_standard_nightly_filename(self):
        assets = [self._asset('ElasticClothingFit-v1.0.5-nightly-202403211430.zip')]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver == (1, 0, 5)
        assert '202403211430' in url
        assert ts == '202403211430'

    def test_8_digit_timestamp(self):
        """Build timestamp may be 8–12 digits (YYYYMMDD minimum)."""
        assets = [self._asset('ElasticClothingFit-v2.1.0-nightly-20240321.zip')]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver == (2, 1, 0)
        assert ts == '20240321'

    def test_12_digit_timestamp(self):
        assets = [self._asset('ElasticClothingFit-v1.0.6-nightly-202403211559.zip')]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ts == '202403211559'

    def test_empty_asset_list_returns_none_tuple(self):
        ver, url, ts = _parse_nightly_asset([])
        assert ver is None
        assert url is None
        assert ts == ''

    def test_no_matching_asset_returns_none_tuple(self):
        assets = [
            {'name': 'README.md', 'browser_download_url': 'https://example.com/README.md'},
            {'name': 'source.tar.gz', 'browser_download_url': 'https://example.com/source.tar.gz'},
        ]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver is None
        assert url is None
        assert ts == ''

    def test_stable_zip_not_matched(self):
        """A non-nightly zip does not match the nightly pattern."""
        assets = [self._asset('ElasticClothingFit-v1.0.5.zip')]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver is None

    def test_first_matching_asset_returned(self):
        """When multiple nightly assets exist, the first match wins."""
        assets = [
            self._asset('ElasticClothingFit-v1.0.5-nightly-202403211200.zip'),
            self._asset('ElasticClothingFit-v1.0.6-nightly-202403221200.zip'),
        ]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver == (1, 0, 5)
        assert ts == '202403211200'

    def test_asset_with_missing_name_key_skipped(self):
        """Assets without a 'name' key are safely skipped."""
        assets = [
            {'browser_download_url': 'https://example.com/broken'},
            self._asset('ElasticClothingFit-v1.0.5-nightly-202403211200.zip'),
        ]
        ver, url, ts = _parse_nightly_asset(assets)
        assert ver == (1, 0, 5)

    def test_url_is_browser_download_url(self):
        """Returned URL is taken from browser_download_url, not name."""
        expected_url = 'https://objects.githubusercontent.com/example/nightly.zip'
        assets = [{
            'name': 'ElasticClothingFit-v1.0.5-nightly-202403211200.zip',
            'browser_download_url': expected_url,
        }]
        ver, url, ts = _parse_nightly_asset(assets)
        assert url == expected_url


# ---------------------------------------------------------------------------
# Tests: _installed_nightly_ts  (filesystem-touching, uses tmp_path)
# ---------------------------------------------------------------------------

class TestInstalledNightlyTs:

    def test_returns_timestamp_from_file(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('202403211430 abc1234\n', encoding='utf-8')
        assert _installed_nightly_ts(str(marker)) == '202403211430'

    def test_returns_only_first_token(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('20240321 abc1234 extra', encoding='utf-8')
        assert _installed_nightly_ts(str(marker)) == '20240321'

    def test_missing_file_returns_empty_string(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        assert _installed_nightly_ts(str(marker)) == ''

    def test_empty_file_returns_empty_string(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('', encoding='utf-8')
        assert _installed_nightly_ts(str(marker)) == ''

    def test_whitespace_only_file_returns_empty_string(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('   \n', encoding='utf-8')
        assert _installed_nightly_ts(str(marker)) == ''

    def test_file_with_leading_newline(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('\n202403211430 abc1234\n', encoding='utf-8')
        # strip() removes leading newline; split()[0] gives first token
        assert _installed_nightly_ts(str(marker)) == '202403211430'


# ---------------------------------------------------------------------------
# Tests: _installed_channel  (filesystem-touching, uses tmp_path)
# ---------------------------------------------------------------------------

class TestInstalledChannel:

    def test_stable_when_marker_absent(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        assert _installed_channel(str(marker)) == 'stable'

    def test_nightly_when_marker_present(self, tmp_path):
        marker = tmp_path / '_nightly.txt'
        marker.write_text('202403211430 abc1234', encoding='utf-8')
        assert _installed_channel(str(marker)) == 'nightly'

    def test_nightly_when_marker_is_empty_file(self, tmp_path):
        """An empty marker file still counts — existence is what matters."""
        marker = tmp_path / '_nightly.txt'
        marker.write_text('', encoding='utf-8')
        assert _installed_channel(str(marker)) == 'nightly'
