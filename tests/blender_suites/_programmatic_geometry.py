"""Shared programmatic geometry helpers for Blender functional suites."""

import bmesh
import bpy


def make_icosphere(name, radius=1.0, location=(0.0, 0.0, 0.0), subdivisions=2):
    """Create and link an icosphere object without using bpy.ops mesh operators."""
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_concave_body(name="ECF_Body"):
    """Create a concave body-like mesh by pinching the equator of an icosphere."""
    obj = make_icosphere(name=name)
    for vert in obj.data.vertices:
        if abs(vert.co.z) < 0.3:
            vert.co.x *= 0.4
            vert.co.y *= 0.4
    obj.data.update()
    return obj


def make_clothing_with_groups(
    name="ECF_Clothing",
    radius=1.1,
    group_names=("Group1", "Group2"),
):
    """Create clothing mesh and assign hemisphere vertex groups."""
    if len(group_names) < 2:
        raise ValueError("group_names must contain at least two group names")

    obj = make_icosphere(name=name, radius=radius)

    vertex_groups = [obj.vertex_groups.new(name=group_name) for group_name in group_names]
    upper_group = vertex_groups[0]
    lower_group = vertex_groups[1]

    upper_indices = [v.index for v in obj.data.vertices if v.co.z > 0]
    lower_indices = [v.index for v in obj.data.vertices if v.co.z <= 0]

    if upper_indices:
        upper_group.add(upper_indices, 1.0, "ADD")
    if lower_indices:
        lower_group.add(lower_indices, 1.0, "ADD")

    return obj


def clear_programmatic_objects(prefix="ECF_"):
    """Remove stale programmatic objects and matching data blocks."""
    for obj in [obj for obj in bpy.data.objects if obj.name.startswith(prefix)]:
        bpy.data.objects.remove(obj, do_unlink=True)

    for mesh in [mesh for mesh in bpy.data.meshes if mesh.name.startswith(prefix)]:
        bpy.data.meshes.remove(mesh, do_unlink=True)

    for armature in [arm for arm in bpy.data.armatures if arm.name.startswith(prefix)]:
        bpy.data.armatures.remove(armature, do_unlink=True)


def get_view3d_context():
    """Return (window, area, region) for the first available VIEW_3D region."""
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return window, area, region

    raise RuntimeError("No VIEW_3D area/region found")
