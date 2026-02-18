# VRC Elastic Clothing Fit

A Blender add-on that fits clothing meshes onto body meshes using a high-poly proxy for smooth deformation, with full UV preservation and live preview.

**Compatible with Blender 3.0+** (3.x, 4.x, 5.x)

## Features

- **Proxy-based fitting** — Subdivides a temporary proxy mesh for smooth shrinkwrap results, then transfers displacements back to the original clothing topology
- **Live preview** — Adjust sliders and see changes in real-time before committing
- **UV preservation** — Original UVs are saved and restored after fitting
- **Preserve group** — Exclude vertex groups from fitting (e.g. waistbands, collars) with smooth follow blending
- **Adaptive displacement smoothing** — Automatically smooths sharp displacement jumps in concave areas while leaving smooth regions untouched
- **Post-fit options** — Optional corrective smooth, symmetrize, and laplacian smooth passes
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
   - **Displacement Smoothing** — Controls for adaptive crease smoothing (under Advanced)
5. Click **Apply** to finalize (runs post-processing steps) or **Cancel** to revert

### Preserve Group

To keep parts of the clothing in place (e.g. a waistband):

1. Create a vertex group on the clothing mesh with weight on the vertices to preserve
2. Select that group in the **Preserve Group** dropdown
3. Preserved vertices will follow the fitted mesh smoothly based on **Follow Strength**

### Post-Fit Options

These are applied when you click **Apply** after previewing:

- **Shape Preservation** — Corrective smooth to maintain the original silhouette
- **Symmetrize** — Mirror one side to the other along a chosen axis
- **Laplacian Smooth** — Additional smoothing pass to reduce noise

## Slider Reference

| Slider | Default | Description |
|--------|---------|-------------|
| Fit Amount | 0.65 | Blend factor toward the body surface |
| Offset | 0.001 | Gap between clothing and body |
| Proxy Resolution | 300,000 | Target triangle count for the proxy mesh |
| Elastic Strength | 0.75 | Corrective smooth factor |
| Elastic Iterations | 10 | Corrective smooth passes |
| Follow Strength | 1.0 | How closely preserved vertices track the fit |

### Advanced Adjustments

| Slider | Default | Description |
|--------|---------|-------------|
| Smooth Passes | 15 | Adaptive displacement smoothing iterations |
| Gradient Threshold | 2.0 | Multiplier for median gradient (lower = more aggressive) |
| Min Smooth Blend | 0.05 | Smoothing blend for low-gradient areas |
| Max Smooth Blend | 0.80 | Smoothing blend for high-gradient (creased) areas |
| Follow Neighbors | 8 | Nearest fitted vertices used for preserve follow |

## Requirements

- Blender 3.0 or newer
- Clothing mesh should have no shape keys or unapplied modifiers (use **Clear Blockers** if needed)

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html). See [LICENSE](LICENSE) for details.
