# Elastic Clothing Fit

[![Nightly Dev Build](https://github.com/VRC-Staples/Elastic-Clothing-Fit/actions/workflows/nightly.yml/badge.svg?branch=dev)](https://github.com/VRC-Staples/Elastic-Clothing-Fit/actions/workflows/nightly.yml)
[![Latest Release](https://img.shields.io/github/v/release/VRC-Staples/Elastic-Clothing-Fit?label=release)](https://github.com/VRC-Staples/Elastic-Clothing-Fit/releases/latest)
[![Blender](https://img.shields.io/badge/Blender-3.2%2B-orange?logo=blender&logoColor=white)](https://www.blender.org/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-blue)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/WyDmWdThXM)

Fit any clothing mesh to any body in a few clicks, with fine-tuning options when you need them.

**Compatible with Blender 3.2+** (3.x, 4.x, 5.x)

A **video tutorial** is available on the [Jinxxy product page](https://jinxxy.com/Staples3D/uvtcA).

See [PATCH_NOTES.md](PATCH_NOTES.md) for version history and change details.

For developer documentation, see the [Wiki](../../wiki).

## Features

- **Simple workflow.** Select your body and clothing, click Fit. All fine-tuning options are tucked away in a collapsed Advanced Settings section.
- **Two fit modes.** Full Mesh Fit fits the entire clothing mesh. Exclusive Vertex Group Fit (EVGF) fits only the vertex groups you specify, leaving the rest of the mesh untouched.
- **Live preview.** Adjust sliders and see changes in real-time before committing. Mesh selectors lock during preview to prevent accidental changes.
- **UV preservation.** Original UVs are saved and restored after fitting so your texture work stays intact.
- **Preserve Group.** Exclude vertex groups from fitting (e.g. waistbands, collars) with smooth blending at the border.
- **Proximity Falloff.** Scale the fit effect by how close each clothing vertex is to the body. Vertices far from the body receive less (or no) displacement. Supports per-vertex-group overrides with independent Mode, Start, End, and Curve settings per group.
- **Crease smoothing.** Automatically softens sharp pinches in tight areas (like between legs) while leaving smooth regions untouched.
- **Live smooth preview.** Shape correction and extra smoothing are applied as live modifiers during preview so you see the final result before applying.
- **Post-fit options.** Optional shape correction and extra smoothing applied on finalize.
- **Offset fine-tuning.** Per-vertex-group offset overrides (0-1000%) for precise local control of the body gap.
- **Hull Fit.** Optional convex-hull proxy of the body fills concave regions (crotch, inner thigh, armpits) so clothing conforms to the body center instead of being pulled toward individual limbs.
- **Advanced controls.** Smoothing passes, crease sensitivity, blend ranges, proximity falloff, and follow parameters under Advanced Settings. Preserve-follow is accelerated with a pykdtree-backed KDTree when available, and automatically falls back to Blender's KDTree on platforms where pykdtree is not installed.
- **Undo support.** Remove Fit restores the original clothing at any time, including after a fit has been applied.
- **Reset Defaults.** One-click reset of all sliders to default values.
- **Auto update checker.** Checks for new releases on load and lets you download and install updates without leaving Blender. Offers to save your file and reopen it automatically after the update installs.
- **Mesh and armature tools.** Utilities for splitting meshes (by loose parts, material, or vertex group), joining meshes, displaying armature settings, and merging armature hierarchies.

## Installation

1. Download `ElasticClothingFit.zip` from the [Releases](../../releases) page
2. In Blender, go to **Edit > Preferences > Add-ons**
3. Click **Install** and select the downloaded `.zip` file
4. Enable **Elastic Clothing Fit** in the add-on list

The panel appears in **View3D > Sidebar (N) > .Staples. ECF**.

## Usage

### Panel layout

The panel has three tabs in the sidebar:

- **Fit** - Fitting workflow (default). Includes a toggle for Exclusive Vertex Group mode.
- **Tools** - Mesh and armature utilities
- **Update** - Update checker

Tab switching is disabled while a preview is active.

### Fitting Clothing

1. Select the **Body** and **Clothing** meshes in the panel
2. Click **Fit Clothing**. The fit runs and enters **Preview Mode**
3. In Preview Mode, open **Advanced Settings** to adjust sliders and see live updates:
   - **Fit Amount.** How far clothing moves toward the body (0 = none, 1 = full snap)
   - **Offset.** Gap between fitted clothing and body surface
   - **Elastic Strength / Iterations.** Shape correction visible live in the viewport
   - **Laplacian Smooth.** Toggle and tune extra smoothing visible live in the viewport
   - **Displacement Smoothing.** Controls for crease softening (under Advanced Settings)
   - **Proximity Falloff.** Scale the fit by body distance (under Shape Preservation, a top-level section)
   - **Offset Fine Tuning.** Per-vertex-group offset multipliers (under Advanced Settings)
4. Click **Apply** to finalize (bakes smoothing) or **Cancel** to revert

> **Note:** Proxy Resolution, Preserve UVs, and Hull Fit cannot be changed during Preview Mode. They are greyed out until you cancel and re-fit.

### Fit Mode

The **Fit** tab supports two modes, toggled with the **Exclusive Vertex Group Mode** button:

- **Full Mesh Fit** (default) - the entire clothing mesh is fitted to the body. Use the Preserve Group to lock specific areas such as waistbands or collars.
- **Exclusive Vertex Group Fit** - only the vertex groups you list are fitted. Everything else on the mesh stays exactly where it is, with no follow blending needed.

The mode resets to Full Mesh Fit after Apply or Cancel.

#### Using Exclusive Vertex Group Fit

EVGF is useful when you want to fit specific panels or regions of a garment without touching the rest of the mesh at all.

1. Click the **Exclusive Vertex Group Mode** toggle in the Fit tab
2. Click **Add Group** in the **Groups to Fit** list
3. Select a vertex group from the clothing mesh
4. Set the **Influence** slider for that group (0-1000%):
   - **100%** - neutral, uses the base offset
   - **0%** - pulls those vertices flush to the body
   - **200%** - doubles the gap from the body
5. Add as many groups as needed; only vertices in those groups will be moved

Vertices outside the listed groups are completely frozen and are never touched by the fit.

### Preserve Group

To keep parts of the clothing in place (e.g. a waistband):

1. Create a vertex group on the clothing with weight on the vertices to preserve
2. Select that group in the **Preserve Group** dropdown
3. Preserved vertices will follow the fitted mesh smoothly based on **Follow Strength**

Preserved vertices are not fitted directly. Instead, they follow the movement of nearby fitted vertices with weighted blending, so the border between preserved and fitted areas stays smooth. Preserved vertices are never directly affected by Offset Fine Tuning — they follow the base shrinkwrap displacement only.

### Proximity Falloff

Proximity Falloff scales the fit effect based on how far each clothing vertex is from the body surface. Vertices close to the body receive the full displacement. Vertices already far away receive less (or none at all). This is useful for loose garments where only the parts near the body need to conform.

1. Expand **Shape Preservation** (a top-level collapsible section)
2. Enable **Use Proximity Falloff**
3. Set **Start** and **End** distances (in meters). Vertices closer than Start get full effect. Vertices beyond End get no effect. Vertices in between are ramped through the selected curve.
4. Choose a **Curve** shape: Linear, Smooth, Sharp, or Root
5. Choose a **Mode**:
   - **Pre-Fit** - distances are measured before the fit runs (based on the original clothing position)
   - **Post Shrinkwrap** - distances are measured after the shrinkwrap step (based on where vertices end up)

All four controls update live during preview.

#### Tune Per Group

Enable **Tune Per Group** to assign each vertex group its own independent proximity settings:

1. Enable **Use Proximity Falloff**, then enable **Tune Per Group**
2. Click **Add Group** and select a vertex group from the clothing mesh
3. Set the **Mode**, **Start**, **End**, and **Curve** for that group independently
4. Add as many groups as needed — each group's falloff ramps independently
5. Vertices not in any listed group continue to receive full proximity weight (weight 1.0)

This is useful when different parts of a garment need different falloff behaviour — tight panels near the body can use a narrow band while loose fabric higher up uses a wide band or no falloff at all.

### Post-Fit Options

These options can be set before fitting or adjusted during preview, and are finalized when you click **Apply**:

- **Shape Preservation.** Keeps the clothing closer to its original silhouette after fitting. Strength and iteration count can be adjusted live during preview.
- **Laplacian Smooth.** An extra smoothing pass to clean up small surface irregularities. Can be toggled on/off and tuned live during preview.

### Tools Tab

The **Tools** tab provides mesh and armature utilities independent of the fitting workflow:

- **Armature Display** — select one or more armatures and toggle their display settings (e.g. show as wireframe, show names)
- **Merge Armatures** — select a source and target armature to merge the source's bone hierarchy into the target
- **Mesh Split** — separate a mesh object into multiple objects by loose parts, material, or vertex group
- **Mesh Join** — join multiple mesh objects into a single object, with optional merge-by-distance

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

**Interaction with Preserve Group.** Offset fine-tuning only affects the fitted vertices it is assigned to. Preserved vertices always follow the base fit displacement and are never moved by offset fine-tuning, even if the two groups are near each other.

## Slider Reference

| Slider | Default | Description |
|--------|---------|-------------|
| Fit Amount | 0.67 | How far clothing moves toward the body |
| Offset | 0.005 | Gap between clothing and body |
| Proxy Resolution | 300,000 | Resolution of the internal fitting mesh |
| Preserve UVs | On | Keep UVs unchanged after fitting |
| Hull Fit | Off | Build a convex-hull proxy to fill concave body regions |
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

### Proximity Falloff (under Shape Preservation)

| Control | Default | Description |
|---------|---------|-------------|
| Use Proximity Falloff | Off | Enable falloff scaling by body distance |
| Mode | Post Shrinkwrap | Whether distances are measured before or after the shrinkwrap step |
| Start | 0.0 m | Distance below which vertices receive full effect |
| End | 0.05 m | Distance above which vertices receive no effect |
| Curve | Smooth | Falloff curve shape: Linear, Smooth, Sharp, or Root |
| Tune Per Group | Off | Override Mode/Start/End/Curve independently per vertex group |

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
| Proximity Falloff (toggle + Start/End/Curve sliders) | Yes — Mode requires re-fit |
| Proxy Resolution | No (re-fit required) |
| Preserve UVs | No (re-fit required) |
| Hull Fit | No (re-fit required) |

## Requirements

- Blender 3.2 or newer
- Clothing mesh should have no shape keys or unapplied modifiers (use **Clear Blockers** if needed)

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html). See [LICENSE](LICENSE) for details.

See [TERMS.md](TERMS.md) for full terms of use, including the no-warranty disclaimer, redistribution rules, and auto-updater network notice.
