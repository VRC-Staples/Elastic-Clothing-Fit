# tests/test_deploy_tool.py
import pathlib
import sys
import textwrap

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "tools"))
import deploy


class TestParseZipVersion:
    def test_standard_filename(self):
        assert deploy._parse_zip_version("ElasticClothingFit-v1.0.5.zip") == (1, 0, 5)

    def test_no_version_returns_zeros(self):
        assert deploy._parse_zip_version("noversion.zip") == (0, 0, 0)

    def test_multi_digit(self):
        assert deploy._parse_zip_version("ElasticClothingFit-v10.20.300.zip") == (10, 20, 300)

    def test_version_in_path(self):
        assert deploy._parse_zip_version(r"C:\builds\ElasticClothingFit-v2.1.0.zip") == (2, 1, 0)


class TestParseResults:
    def test_pass_and_fail(self):
        stdout = "  [PASS] addon installed\n  [FAIL] scene property missing\n  [PASS] cleanup ok"
        r = deploy._parse_results(stdout)
        assert len(r["passed"]) == 2
        assert len(r["failed"]) == 1

    def test_empty_output(self):
        r = deploy._parse_results("")
        assert r == {"passed": [], "failed": []}

    def test_only_passes(self):
        r = deploy._parse_results("[PASS] step 1\n[PASS] step 2")
        assert len(r["passed"]) == 2
        assert len(r["failed"]) == 0

    def test_fail_line_content_preserved(self):
        r = deploy._parse_results("  [FAIL] efit_props not found")
        assert "efit_props not found" in r["failed"][0]


class TestReadVersion:
    def test_reads_version(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text(
            textwrap.dedent('''
                bl_info = {
                    "name": "Test Addon",
                    "version": (1, 2, 3),
                }
            '''),
            encoding="utf-8",
        )
        assert deploy._read_version(init_py) == "1.2.3"

    def test_missing_version_raises(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text("# no bl_info here", encoding="utf-8")
        with pytest.raises(ValueError, match=r"bl_info\['version'\]"):
            deploy._read_version(init_py)

    def test_version_with_spaces(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text('"version"  :  ( 2 , 0 , 1 ),', encoding="utf-8")
        assert deploy._read_version(init_py) == "2.0.1"


class TestReadBlenderMin:
    def test_reads_blender_min(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text(
            textwrap.dedent('''
                bl_info = {
                    "blender": (3, 6, 23),
                }
            '''),
            encoding="utf-8",
        )
        assert deploy._read_blender_min(init_py) == "3.6.23"

    def test_missing_blender_tuple_raises(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text('bl_info = {"version": (1, 0, 0)}', encoding="utf-8")
        with pytest.raises(ValueError, match=r"bl_info\['blender'\]"):
            deploy._read_blender_min(init_py)

    def test_negative_tuple_value_raises(self, tmp_path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text('bl_info = {"blender": (3, -2, 0)}', encoding="utf-8")
        with pytest.raises(ValueError, match="non-negative integers"):
            deploy._read_blender_min(init_py)
