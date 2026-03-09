# Patch Notes

## v1.0.5

### 3-tab panel layout

The sidebar panel has been reorganized into three tabs:

- **Full** - Full Mesh Fit workflow (the default)
- **Exclusive** - Exclusive Vertex Group Fit workflow
- **Update** - Update checker (previously at the bottom of every tab)

Tab switching is disabled while a preview is active. Switching between Full and Exclusive tabs automatically syncs the internal fit mode. Both tabs reset to Full after Apply or Cancel.

### Advanced Settings consolidated

All settings are now under a single **Advanced Settings** collapse toggle. Previously, Fit Settings was pinned above a separate Advanced box. Now everything is one level deep under the toggle, making the panel easier to scan.

### Section consolidation

- **Proximity Falloff controls** moved inline into the **Shape Preservation** section. Enabling the toggle expands the mode, start, end, and curve controls directly beneath it. The separate Proximity Falloff section has been removed.
- **Post-Laplacian controls** moved inline into the **Displacement Smoothing** section. Enabling the toggle expands the factor and iteration sliders directly beneath it. These controls were previously in the Post-Fit section.

### Proximity Falloff

A new system that scales the fit effect based on how close each clothing vertex is to the body surface. Vertices close to the body receive the full displacement; vertices already far away receive less (or none at all). Useful for loose garments where only parts of the mesh need to conform.

- Enable with the **Use Proximity Falloff** toggle in the **Shape Preservation** section
- **Mode** - `Pre-Fit` measures distances before fitting (based on how the clothing sits before the fit runs); `Post-Fit` uses the post-fit result
- **Start** / **End** - distance range in meters over which the falloff ramps from full effect to none
- **Curve** - shape of the falloff ramp: Linear, Smooth, Sharp, or Root
- All four sliders update live during preview

### UI polish

- **Onboarding hint.** When neither body nor clothing mesh is selected, the mesh picker area shows a short hint: "Pick your avatar body, then the clothing item to fit." The hint disappears as soon as the user starts selecting.
- **Duplicate mesh alert.** If the same mesh is selected for both body and clothing, a red alert box appears immediately in the mesh picker section. The Fit button stays greyed out until different objects are selected.
- **Remove Fit conditional state.** The Remove Fit button is now greyed out when no fit data is stored for the current clothing mesh. Previously it was always enabled even when there was nothing to remove.

### Performance improvements

The fitting pipeline and live preview have been overhauled to eliminate unnecessary work on every slider drag.

- **Bulk vertex I/O.** Vertex positions and UV coordinates are now read and written using Blender's `foreach_get` / `foreach_set` APIs, which perform the full buffer copy in a single C-level call. Previously each vertex was read or written through the Python-to-C bridge individually.
- **Median calculation.** The adaptive smoothing passes compute the median gradient using Python's `statistics.median()` (O(n) quickselect) instead of sorting the full array each pass (O(n log n)). The improvement is most noticeable at high smooth pass counts on large meshes.
- **Neighbor average accumulation.** Inside each smoothing pass, the per-vertex neighbor average is now computed as three plain float additions instead of allocating a `mathutils.Vector` object per vertex. This eliminates several hundred thousand object allocations per fit at Final quality.
- **Edge adjacency build.** The edge adjacency table is now built using a numpy bulk read + boolean mask, skipping the Python loop over all edges for the fitness check.
- **Vertex group queries.** All vertex group weight lookups that previously used `vg.weight(vi)` with `try/except RuntimeError` (Blender's only API for checking group membership) have been replaced with iteration over `v.groups`. The previous pattern constructed a Python exception object for every vertex not in a group; the new pattern has no exception overhead.
- **Body vertex buffer.** The body mesh vertex list passed to `BVHTree.FromPolygons` no longer creates a full `.copy()` of every vertex position. The BVH reads the positions directly.
- **Conditional position snapshot.** The per-fitted-vertex position snapshot taken before offset fine-tuning is now skipped entirely when there are no offset groups and no preserve group. This avoids a full mesh traversal on the common case.
- **Panel blocker detection cached.** `_has_blockers` (which checks for shape keys and incompatible modifiers) is now cached between frames in `state.py`. Blender calls the panel's `draw()` method up to 60 times per second; without the cache this ran a full modifier iteration on every frame. The cache key is `(object_name, modifier_count, shape_key_count)` and clears automatically on any change.

---

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
