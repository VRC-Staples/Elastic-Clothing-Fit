# Elastic Clothing Fit

Fit any clothing mesh to any body in a few clicks, with fine-tuning options when you need them.

**Compatible with Blender 3.0+** (3.x, 4.x, 5.x)

A **video tutorial** is available on the [Jinxxy product page](https://jinxxy.com/Staples3D/uvtcA).

See [PATCH_NOTES.md](PATCH_NOTES.md) for version history and change details.

## Features

- **Simple workflow.** Select your body and clothing, click Fit. All fine-tuning options are tucked away in a collapsed Advanced Settings section.
- **Live preview.** Adjust sliders and see changes in real-time before committing. Mesh selectors lock during preview to prevent accidental changes.
- **UV preservation.** Original UVs are saved and restored after fitting so your texture work stays intact.
- **Preserve Group.** Exclude vertex groups from fitting (e.g. waistbands, collars) with smooth blending at the border.
- **Crease smoothing.** Automatically softens sharp pinches in tight areas (like between legs) while leaving smooth regions untouched.
- **Live smooth preview.** Shape correction and extra smoothing are applied as live modifiers during preview so you see the final result before applying.
- **Post-fit options.** Optional shape correction, symmetrize, and extra smoothing applied on finalize.
- **Offset fine-tuning.** Per-vertex-group offset overrides (0-1000%) for precise local control of the body gap.
- **Advanced controls.** Smoothing passes, crease sensitivity, blend ranges, and follow parameters under Advanced Settings.
- **Undo support.** Remove Fit restores the original clothing at any time.
- **Reset Defaults.** One-click reset of all sliders to default values.

## Installation

1. Download `ElasticClothingFit.zip` from the [Releases](../../releases) page
2. In Blender, go to **Edit > Preferences > Add-ons**
3. Click **Install** and select the downloaded `.zip` file
4. Enable **Elastic Clothing Fit** in the add-on list

The panel appears in **View3D > Sidebar (N) > .Staples. Elastic Fit**.

## Usage

### Fitting Clothing

1. Select the **Body** and **Clothing** meshes in the panel
2. Click **Fit Clothing**. The fit runs and enters **Preview Mode**
3. In Preview Mode, open **Advanced Settings** to adjust sliders and see live updates:
   - **Fit Amount.** How far clothing moves toward the body (0 = none, 1 = full snap)
   - **Offset.** Gap between fitted clothing and body surface
   - **Elastic Strength / Iterations.** Shape correction visible live in the viewport
   - **Laplacian Smooth.** Toggle and tune extra smoothing visible live in the viewport
   - **Displacement Smoothing.** Controls for crease softening (under Advanced Settings)
   - **Offset Fine Tuning.** Per-vertex-group offset multipliers (under Advanced Settings)
4. Click **Apply** to finalize (bakes smoothing, runs symmetrize if enabled) or **Cancel** to revert

> **Note:** Proxy Resolution, Preserve UVs, and Symmetrize cannot be changed during Preview Mode. They are greyed out until you cancel and re-fit.

### Preserve Group

To keep parts of the clothing in place (e.g. a waistband):

1. Create a vertex group on the clothing with weight on the vertices to preserve
2. Select that group in the **Preserve Group** dropdown
3. Preserved vertices will follow the fitted mesh smoothly based on **Follow Strength**

Preserved vertices are not fitted directly. Instead, they follow the movement of nearby fitted vertices with weighted blending, so the border between preserved and fitted areas stays smooth. If a fitted area is pushed outward by Offset Fine Tuning, nearby preserved vertices will follow that push naturally. Preserved vertices themselves are never directly affected by Offset Fine Tuning.

### Post-Fit Options

These options can be set before fitting or adjusted during preview, and are finalized when you click **Apply**:

- **Shape Preservation.** Keeps the clothing closer to its original silhouette after fitting. Strength and iteration count can be adjusted live during preview.
- **Laplacian Smooth.** An extra smoothing pass to clean up small surface irregularities. Can be toggled on/off and tuned live during preview.
- **Symmetrize.** Mirrors one side to the other along a chosen axis. Must be configured before fitting. Not available during preview; applied on finalize only.

### Offset Fine Tuning

Available under **Advanced Settings**, this lets you override the body gap for specific areas of the clothing:

1. Expand **Advanced Settings** and scroll to **Offset Fine Tuning**
2. Click **Add Group** to add an entry
3. Select a vertex group from the clothing mesh
4. Set the **Influence** slider (0-1000%):
   - **100%** - No change from the base offset (neutral)
   - **0%** - Those vertices are pulled flush to the body surface
   - **200%** - Those vertices are pushed twice as far as the base offset
   - Values above 200% push vertices progressively further out, up to 10x the base offset at 1000%
5. Add as many groups as needed; click the minus button on an entry to remove it

Influence sliders update live during preview. Changing which vertex group is selected also updates live and recomputes per-vertex weights immediately.

**Interaction with Preserve Group.** Offset fine-tuning is applied to fitted vertices before the preserve-follow step runs. This means preserved vertices near an offset-tuned region will follow the offset-adjusted positions of their fitted neighbors, keeping the boundary consistent.

## Slider Reference

| Slider | Default | Description |
|--------|---------|-------------|
| Fit Amount | 0.65 | How far clothing moves toward the body |
| Offset | 0.001 | Gap between clothing and body |
| Proxy Resolution | 300,000 | Resolution of the internal fitting mesh |
| Preserve UVs | On | Keep UVs unchanged after fitting |
| Elastic Strength | 0.75 | Shape correction strength |
| Elastic Iterations | 10 | How many shape correction passes to apply |
| Follow Strength | 1.0 | How closely preserved vertices follow the fitted mesh |
| Laplacian Factor | 0.25 | Extra smoothing strength |
| Laplacian Iterations | 1 | How many extra smoothing passes to apply |

### Advanced Settings

| Slider | Default | Description |
|--------|---------|-------------|
| Smooth Passes | 15 | Passes to smooth sharp pinches in tight areas |
| Gradient Threshold | 2.0 | How sharp a crease must be before extra smoothing kicks in |
| Min Smooth Blend | 0.05 | Smoothing strength in flat areas |
| Max Smooth Blend | 0.80 | Smoothing strength at crease areas |
| Follow Neighbors | 8 | How many fitted vertices preserved verts sample when following (max 64) |
| Influence (per group) | 100% | Per-vertex-group offset multiplier (0-1000%) |

## Preview Mode Reference

When a fit is active, the panel enters **Preview Mode**. The following controls update live:

| Control | Live in Preview |
|---------|----------------|
| Fit Amount | Yes |
| Offset | Yes |
| Elastic Strength | Yes |
| Elastic Iterations | Yes |
| Laplacian Smooth (toggle + sliders) | Yes |
| Displacement Smoothing (Advanced Settings) | Yes |
| Follow Strength / Neighbors | Yes |
| Offset Fine Tuning groups | Yes |
| Proxy Resolution | No (re-fit required) |
| Preserve UVs | No (re-fit required) |
| Symmetrize | No (applied on finalize only) |

## Requirements

- Blender 3.0 or newer
- Clothing mesh should have no shape keys or unapplied modifiers (use **Clear Blockers** if needed)

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html). See [LICENSE](LICENSE) for details.
