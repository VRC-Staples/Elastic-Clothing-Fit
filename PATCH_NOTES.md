# Patch Notes

## v1.0.4

### In-panel update checker

The add-on now checks for updates automatically when loaded. A status indicator appears at the bottom of the panel showing whether you are up to date or if a newer version is available. If an update is found, you can download it and install it without leaving Blender. Blender restarts automatically and applies the update on the next launch.

- Update check runs in the background on load, no manual action needed
- Download progress is shown live in the panel as a percentage
- Installation is handled by a one-shot startup script that runs on the next Blender launch and removes itself when done
- When a download is ready, the panel shows options to save the current file before restarting and reopen it automatically after the update installs
- A developer testing mode is available under **Edit > Preferences > Add-ons** for testing the update pipeline with a local zip file

### Exclusive Vertex Group Fit mode

A new fit mode that limits fitting to only the vertex groups you specify, leaving all other vertices untouched. Useful for clothing where only part of the mesh needs to conform to the body, such as a waistband or collar.

- Switch from **Full Mesh Fit** to **Exclusive Vertex Group Fit** using the toggle at the top of the panel
- Add vertex groups to the **Groups to Fit** list under Advanced Settings
- Each group has its own **Influence** slider (0-1000%), allowing offset to be tuned per group the same way Offset Fine Tuning works in Full Mesh Fit mode
- Vertices outside the listed groups are frozen in place and do not follow nearby fitted areas
- Fit mode resets to Full Mesh Fit after Apply or Cancel

### Precision stepping for numeric fields

Arrow increments for the following fields have been reduced to 0.01 for finer control:

- Fit Amount
- Gradient Threshold
- Min Smooth Blend
- Max Smooth Blend

### Sidebar tab renamed

The sidebar tab now reads **.Staples. ECF** instead of the full add-on name.

### Code reorganized into a package

The add-on has been split from a single file into a proper Blender package with one focused module per area of responsibility. This has no effect on how the add-on works, but makes the code much easier to read and maintain.

- `state.py` - shared globals, constants, and utility functions
- `preview.py` - live preview engine and property update callbacks
- `properties.py` - all user-facing settings
- `operators.py` - all operators (fit, apply, cancel, remove, etc.)
- `panels.py` - the sidebar panel

### Bug fixes

- **Remove Fit after Apply.** Remove Fit now correctly restores the mesh to its pre-fit state after a fit has been applied. Previously, applying a fit discarded the stored original positions, leaving Remove Fit with nothing to restore.
- **Exclusive Vertex Group Fit with no groups.** The **Fit Clothing** button now greys out when Exclusive Vertex Group Fit mode is active and no valid groups are configured in the Groups to Fit list. Hovering the button shows a message explaining what to add. Previously the fit would run silently and move no vertices.
- **Exclusive Vertex Group Fit influence not applied on first fit.** Group influence sliders in Exclusive Vertex Group Fit mode now take effect immediately when fitting. Previously the adjustments were only applied after moving a slider to trigger a preview refresh; fitting and applying without touching any slider produced a result with all influence values treated as 100%.
- **Auto-update restart on Windows.** The new Blender instance spawned during an update now correctly survives the current process exiting on Windows. Previously, the child process could be terminated when the parent quit because it inherited the parent job object. Process detachment flags are now applied on Windows so the new instance starts independently. No change on macOS or Linux.

### Additional UX improvements

- The three repeated "not available in preview mode" labels in Advanced Settings have been replaced with a single note shown once at the top of the section when a preview is active.
- The **Replace Previous** checkbox and **Reset Defaults** button are now on the same row at the bottom of Advanced Settings, reducing visual clutter.
- The **Offset Fine Tuning** list now shows column headers ("Vertex Group" and "Influence") when entries are present.
- Vertex group dropdowns (**Preserve Group** and **Offset Fine Tuning** group selector) now list groups in reverse creation order, so the most recently added group appears at the top.
- Default values for **Fit Amount** and **Offset** have been adjusted to 0.67 and 0.005 respectively, based on typical use.

---

## v1.0.3

### Follow Neighbors limit increased to 64

The **Follow Neighbors** slider under Advanced Settings now goes up to 64 (previously capped at 32).

Follow Neighbors controls how many nearby fitted vertices each preserved vertex samples when calculating where to move. Raising the cap is useful for large preserve groups or coarser clothing meshes where 32 neighbors was not enough to produce a smooth blend at the boundary.

### Preserve Group no longer affected by Offset Fine Tuning

Offset Fine Tuning adjustments now only move the fitted vertices they are assigned to. Previously, nearby preserved vertices would pick up these adjustments indirectly through the follow step, causing the preserve group to shift when it should not. Preserved vertices now always follow the base shrinkwrap displacement only, regardless of any offset fine-tuning applied to nearby fitted regions.

### UX improvements

- All property tooltips have been rewritten in plain language. Descriptions now explain what a setting does and when to change it, rather than describing the underlying algorithm.
- Buttons now grey out automatically when they cannot run. For example, **Fit Clothing** is disabled while a preview is active, and **Remove Fit** is disabled when no clothing is selected. This replaces error popups with visual feedback.
- The **Advanced Settings** section was renamed from "Show Advanced Adjustments" for clarity.
- Status messages in the Info bar are now cleaner and easier to read.

---

## v1.0.1

### Preserve Group + Offset Fine Tuning interaction

Preserved vertices that are near fitted vertices affected by an **Offset Fine Tuning** group now follow the offset-adjusted positions of those vertices, rather than only following the base shrinkwrap displacement.

Previously, offset fine-tuning was applied to fitted vertices *after* the preserve-follow step ran. This meant preserved vertices would follow the fitted mesh as if no offset adjustment had been made, then the offset would be applied to fitted vertices separately, creating a subtle mismatch at the boundary between preserved and fitted regions.

Now offset fine-tuning is applied to fitted vertices *before* the follow step. When the follow step reads the current positions of nearby fitted vertices to work out how far to pull each preserved vertex, those positions already include the offset contribution. The preserved vertices themselves are never directly pushed by the offset; the adjustment reaches them indirectly through the follow mechanism, the same way the base shrinkwrap displacement does.

**Note:** This behavior was revised in v1.0.3. Preserved vertices no longer follow offset-adjusted positions, as this caused unintended movement when the preserve group and offset fine-tuning group did not share vertices.

---

## v1.0.0

Initial release.

- Proxy-based fitting with automatic subdivision
- Live preview mode with real-time slider updates
- UV preservation
- Preserve group with nearest-neighbor displacement follow
- Adaptive displacement smoothing
- Corrective smooth and Laplacian smooth as live preview modifiers
- Per-vertex-group offset fine-tuning (0-1000%)
- Symmetrize post-fit option
- Clear Blockers operator for shape keys and unapplied modifiers
- Reset Defaults operator
