# Release Checklist

Follow this checklist for every stable release before publishing to GitHub.

---

## Pre-release

- [ ] All tests pass on the current branch (`python tests/run_all.py`)
- [ ] `elastic_fit/__init__.py` `bl_info["version"]` is updated
- [ ] `elastic_fit/__init__.py` `bl_info["blender"]` reflects the true minimum Blender version
  - Re-verify minimum whenever a new bpy API is introduced (see [KNOWLEDGE.md](../.gsd/KNOWLEDGE.md))
  - Current minimum: **3.2.0** (required by `bpy.context.temp_override`)
- [ ] `README.md` "Compatible with Blender X.Y+" badge and Requirements section match `bl_info["blender"]`
- [ ] `CHANGELOG.md` (if maintained) has an entry for this version

## Build

- [ ] Run `tools/deploy.py --blender <path> build` locally and confirm zip is produced
- [ ] Note the SHA-256 printed by `deploy.py` — you will need it for the release notes

## GitHub Release

- [ ] Tag the commit: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] The `Stable Release` workflow triggers automatically on the tag push
  - It runs the full test suite, computes SHA-256, and creates a draft release
  - SHA-256 and `BLENDER_MIN=X.Y.Z` are embedded automatically
- [ ] Review the draft release notes; add a human-written summary of changes above the auto-generated section
- [ ] Publish the release

## BLENDER_MIN enforcement (critical)

The `BLENDER_MIN=X.Y.Z` token in the release notes body drives the updater's version-blocking
logic. The stable release workflow writes it automatically from `bl_info["blender"]`. **Do not
delete or alter this line in the release notes.**

If publishing a release manually (bypassing the workflow), you must include the token yourself:

```
BLENDER_MIN=X.Y.Z
```

Replace `X.Y.Z` with the value from `bl_info["blender"]` in `elastic_fit/__init__.py`.
Without this token, users on old Blender versions will be offered — and able to download —
an incompatible update with no warning.

## SHA-256 verification

The updater verifies downloaded zips against `SHA256: <hex>` in the release notes when present.
The stable release workflow embeds this automatically. For manual releases, include:

```
SHA256: <hex from deploy.py output>
```

---

## Post-release

- [ ] Confirm the GitHub release is visible and the zip is downloadable
- [ ] Install the zip in Blender and run a smoke test (fit one mesh to another)
- [ ] Verify the Update tab in Blender shows the new version and the Download button is active
