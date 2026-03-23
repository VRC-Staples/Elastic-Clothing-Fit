#!/usr/bin/env python3
"""
fetch_wheels.py — download pykdtree wheels for all supported platforms.

Run this when bumping the pykdtree version, then commit the updated .whl files.

Usage:
    python tools/fetch_wheels.py [--version X.Y.Z]

The downloaded wheels land in elastic_fit/wheels/ and are committed to git so
the release zip always includes them.  No internet access is needed at build
time or at user install time — the addon installs the matching wheel silently
on first launch.

Supported platforms (Blender 3.2 – 5.x range):
    Python 3.10 (Blender 3.2-3.6) and 3.11 (Blender 4.0+)
    Windows x86_64 (win_amd64)
    macOS Intel (macosx_13_0_x86_64)
    macOS Apple Silicon (macosx_14_0_arm64)
    Linux x86_64 (manylinux2014_x86_64)
"""
import argparse
import json
import pathlib
import urllib.request

_ROOT = pathlib.Path(__file__).parent.parent
_WHEELS_DIR = _ROOT / "elastic_fit" / "wheels"

# Platform tag substrings to match against wheel filenames.
_PLATFORM_TAGS = [
    "win_amd64",
    "macosx_13_0_x86_64",
    "macosx_14_0_arm64",
    "manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64",
]

# CPython ABI tags to include.
_PY_TAGS = ["cp310", "cp311"]


def _fetch_pypi_meta(package: str, version: str | None) -> tuple[str, list[dict]]:
    """Return (resolved_version, list_of_file_info_dicts) from PyPI."""
    if version:
        url = f"https://pypi.org/pypi/{package}/{version}/json"
    else:
        url = f"https://pypi.org/pypi/{package}/json"
    print(f"Querying PyPI: {url}")
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())
    resolved = data["info"]["version"]
    return resolved, data["urls"]


def _matches(filename: str) -> bool:
    """Return True if the wheel filename matches our target py + platform tags."""
    return (
        any(pt in filename for pt in _PY_TAGS)
        and any(pl in filename for pl in _PLATFORM_TAGS)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--version", default=None, help="pykdtree version to fetch (default: latest)")
    args = parser.parse_args()

    _WHEELS_DIR.mkdir(parents=True, exist_ok=True)

    version, urls = _fetch_pypi_meta("pykdtree", args.version)
    print(f"pykdtree version: {version}")
    print()

    # Remove any previously downloaded wheels for a different version.
    for old in _WHEELS_DIR.glob("pykdtree-*.whl"):
        if not old.name.startswith(f"pykdtree-{version}-"):
            print(f"  removing stale: {old.name}")
            old.unlink()

    fetched = 0
    for file_info in urls:
        fn = file_info["filename"]
        if not _matches(fn):
            continue
        dest = _WHEELS_DIR / fn
        if dest.exists():
            print(f"  already have {fn}")
            fetched += 1
            continue
        size_kb = file_info["size"] // 1024
        print(f"  downloading {fn} ({size_kb}KB)…", flush=True)
        with urllib.request.urlopen(file_info["url"], timeout=60) as r:
            dest.write_bytes(r.read())
        print(f"  done: {fn}")
        fetched += 1

    print()
    print(f"Fetched {fetched} wheels → {_WHEELS_DIR.relative_to(_ROOT)}")
    print("Commit the updated .whl files before building a release.")


if __name__ == "__main__":
    main()
