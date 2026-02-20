# VRC Elastic Clothing Fit

A Blender add-on that fits clothing meshes onto body meshes using a high-poly proxy for smooth deformation, with full UV preservation and live preview.

**Compatible with Blender 3.0+** (3.x, 4.x, 5.x)

See [PATCH_NOTES.md](PATCH_NOTES.md) for version history and change details.

## Features

- **Proxy-based fitting** — Subdivides a temporary proxy mesh for smooth shrinkwrap results, then transfers displacements back to the original clothing topology
- **Live preview** — Adjust sliders and see changes in real-time before committing; mesh selectors lock during preview to prevent accidental changes
- **UV preservation** — Original UVs are saved and restored after fitting
- **Preserve group** — Exclude vertex groups from fitting (e.g. waistbands, collars) with smooth follow blending
- **Adaptive displacement smoothing** — Automatically smooths sharp displacement jumps in concave areas while leaving smooth regions untouched
- **Live smooth preview** — Corrective smooth and Laplacian smooth are applied as live viewport modifiers during preview so you see the final result before applying
- **Post-fit options** — Optional corrective smooth, symmetrize, and Laplacian smooth passes applied on finalize
- **Offset fine-tuning** — Per-vertex-group offset influence overrides (0–200%) for precise local control of the body gap
- **Advanced adjustments** — Fine-tune smoothing passes, gradient thresholds, blend ranges, and follow parameters
- **Undo support** — Remove Fit restores the original mesh at any time
- **Reset defaults** — One-click reset of all sliders to default values

## Installation

1. Download `ElasticClothingFit.zip` from the [Releases](../../releases) page
2. In Blender, go to **Edit > Preferences > Add-ons**
3. Click **Install** and select the downloaded `.zip` file
4. Enable **Elastic Clothing Fit** in the add-on list

The panel appears in **View3D > Sidebar (N) > .Staples. Elastic Fit**.

## Usage

### Fitting Clothing

1. Select the **Body** and **Clothing** meshes in the panel
2. Adjust **Fit Amount**, **Offset**, and other settings as needed
3. Click **Fit Clothing** — the fit runs and enters **preview mode**
4. In preview mode, adjust any slider to see live updates:
   - **Fit Amount** — How far clothing moves toward the body (0 = none, 1 = full snap)
   - **Offset** — Gap between fitted surface and body
   - **Elastic Strength / Iterations** — Corrective smooth visible live in the viewport
   - **Laplacian Smooth** — Toggle and tune Laplacian smoothing visible live in the viewport
   - **Displacement Smoothing** — Controls for adaptive crease smoothing (under Advanced)
   - **Offset Fine Tuning** — Per-vertex-group offset multipliers (under Advanced)
5. Click **Apply** to finalize (bakes smoothing, runs symmetrize if enabled) or **Cancel** to revert

> **Note:** Proxy Resolution, Preserve UVs, and Symmetrize cannot be changed during preview — they are grayed out with an indicator. Cancel and re-fit to change them.

### Preserve Group

To keep parts of the clothing in place (e.g. a waistband):

1. Create a vertex group on the clothing mesh with weight on the vertices to preserve
2. Select that group in the **Preserve Group** dropdown
3. Preserved vertices will follow the fitted mesh smoothly based on **Follow Strength**

Preserved vertices are not fitted directly — they follow the displacement of nearby fitted vertices using a weighted KDTree average. This means they also pick up any **Offset Fine Tuning** adjustments applied to those fitted neighbors: if the fitted region around a preserved area is pushed outward by an offset group, the preserved vertices will follow that push naturally. Preserved vertices themselves are never directly affected by offset fine-tuning.

### Post-Fit Options

These options can be set before fitting or adjusted during preview, and are finalized when you click **Apply**:

- **Shape Preservation** — Corrective smooth to maintain the original silhouette. Strength and iteration count can be adjusted live during preview.
- **Laplacian Smooth** — Additional smoothing pass to reduce noise. Can be toggled on/off and tuned live during preview.
- **Symmetrize** — Mirror one side to the other along a chosen axis. Must be configured before fitting; this option is not available during preview and is applied on finalize only.

### Offset Fine Tuning

Available under **Advanced Adjustments**, this lets you override the body gap for specific areas of the mesh:

1. Expand **Advanced Adjustments** and scroll to **Offset Fine Tuning**
2. Click **Add Group** to add an entry
3. Select a vertex group from the clothing mesh
4. Set the **Influence** slider (0–1000%):
   - **100%** — No change from the base offset (neutral)
   - **0%** — Those vertices are pulled flush to the body surface
   - **200%** — Those vertices are pushed twice as far as the base offset
   - Values above 200% push vertices progressively further out, up to 10× the base offset at 1000%
5. Add as many groups as needed; click **−** on an entry to remove it

Changes to influence sliders update live during preview. Changing which vertex group is selected also updates live and recomputes the per-vertex weights immediately.

**Interaction with Preserve Group:** Offset fine-tuning is applied to fitted vertices before the preserve-follow step runs. This means preserved vertices that are near an offset-tuned region will follow the offset-adjusted positions of their fitted neighbors, keeping the boundary between preserved and fitted areas consistent.

## Slider Reference

| Slider | Default | Description |
|--------|---------|-------------|
| Fit Amount | 0.65 | Blend factor toward the body surface |
| Offset | 0.001 | Gap between clothing and body |
| Proxy Resolution | 300,000 | Target triangle count for the proxy mesh |
| Preserve UVs | On | Restore original UV coordinates after fitting |
| Elastic Strength | 0.75 | Corrective smooth factor |
| Elastic Iterations | 10 | Corrective smooth passes |
| Follow Strength | 1.0 | How closely preserved vertices track the fit |
| Laplacian Factor | 0.25 | Strength of Laplacian smoothing |
| Laplacian Iterations | 1 | Number of Laplacian smooth passes |

### Advanced Adjustments

| Slider | Default | Description |
|--------|---------|-------------|
| Smooth Passes | 15 | Adaptive displacement smoothing iterations |
| Gradient Threshold | 2.0 | Multiplier for median gradient (lower = more aggressive) |
| Min Smooth Blend | 0.05 | Smoothing blend for low-gradient areas |
| Max Smooth Blend | 0.80 | Smoothing blend for high-gradient (creased) areas |
| Follow Neighbors | 8 | Nearest fitted vertices used for preserve follow |
| Influence (per group) | 100% | Per-vertex-group offset multiplier (0–1000%) |

## Preview Mode Reference

When a fit is active, the panel enters **Preview Mode**. The following controls are live (changes apply immediately to the viewport):

| Control | Live in Preview |
|---------|----------------|
| Fit Amount | Yes |
| Offset | Yes |
| Elastic Strength | Yes |
| Elastic Iterations | Yes |
| Laplacian Smooth (toggle + sliders) | Yes |
| Displacement Smoothing (Advanced) | Yes |
| Follow Strength / Neighbors | Yes |
| Offset Fine Tuning groups | Yes |
| Proxy Resolution | No — re-fit required |
| Preserve UVs | No — re-fit required |
| Symmetrize | No — applied on finalize only |

## Requirements

- Blender 3.0 or newer
- Clothing mesh should have no shape keys or unapplied modifiers (use **Clear Blockers** if needed)

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html). See [LICENSE](LICENSE) for details.
