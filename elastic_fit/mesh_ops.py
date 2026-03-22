# mesh_ops.py
# Mesh utility operators for Elastic Clothing Fit.
# Provides mesh splitting (by loose parts, material, or vertex group)
# and mesh joining (with optional merge-by-distance).

import bpy
from bpy.types import Operator


def _get_view3d_context(context):
    """Return (window, area, region) for the first available VIEW_3D area."""
    win = context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region:
                return win, area, region
    return None, None, None


def _merge_by_distance(threshold):
    """Merge coincident vertices within threshold using bmesh directly.

    Uses bmesh.ops.remove_doubles which works reliably across Blender versions
    without requiring an operator context or Edit mode.
    """
    import bmesh as _bmesh
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        return
    bm = _bmesh.from_edit_mesh(obj.data)
    _bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=threshold)
    _bmesh.update_edit_mesh(obj.data)


class EFIT_OT_mesh_split(Operator):
    bl_idname  = "efit.mesh_split"
    bl_label   = "Split Mesh"
    bl_description = (
        "Split the active mesh into separate objects. "
        "Loose Parts: one object per disconnected piece. "
        "By Material: one object per material. "
        "By Vertex Group: one object for the group, one for everything else."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        p = context.scene.efit_props
        if p.mesh_split_mode == 'BY_VERTEX_GROUP' and not p.mesh_split_group.strip():
            cls.poll_message_set("Enter a vertex group name in the Split field.")
            return False
        return True

    def execute(self, context):
        p   = context.scene.efit_props
        obj = context.active_object

        win, area, region = _get_view3d_context(context)
        if area is None:
            self.report({'ERROR'}, "Split requires an open 3D Viewport.")
            return {'CANCELLED'}

        mode = p.mesh_split_mode

        if mode == 'BY_VERTEX_GROUP':
            group_name = p.mesh_split_group.strip()
            vg = obj.vertex_groups.get(group_name)
            if vg is None:
                self.report({'ERROR'}, f"Vertex group {group_name!r} not found on {obj.name!r}.")
                return {'CANCELLED'}

            # Set the active vertex group then select it in Edit mode.
            obj.vertex_groups.active_index = vg.index
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=obj):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.vertex_group_select()
                result = bpy.ops.mesh.separate(type='SELECTED')
                bpy.ops.object.mode_set(mode='OBJECT')

        elif mode == 'BY_MATERIAL':
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=obj):
                bpy.ops.object.mode_set(mode='EDIT')
                result = bpy.ops.mesh.separate(type='MATERIAL')
                bpy.ops.object.mode_set(mode='OBJECT')

        else:  # LOOSE_PARTS
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=obj):
                bpy.ops.object.mode_set(mode='EDIT')
                result = bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')

        if 'FINISHED' in result:
            self.report({'INFO'}, "Mesh split.")
        else:
            self.report({'WARNING'}, "Split produced no result (mesh may already be a single piece).")
        return {'FINISHED'}


class EFIT_OT_mesh_join(Operator):
    bl_idname  = "efit.mesh_join"
    bl_label   = "Join Meshes"
    bl_description = (
        "Combine all selected mesh objects into the active one. "
        "Optionally merges overlapping vertices within the set distance."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if len(selected_meshes) < 2:
            cls.poll_message_set("Select at least two mesh objects to join.")
            return False
        return True

    def execute(self, context):
        p   = context.scene.efit_props
        obj = context.active_object

        win, area, region = _get_view3d_context(context)
        if area is None:
            self.report({'ERROR'}, "Join requires an open 3D Viewport.")
            return {'CANCELLED'}

        with bpy.context.temp_override(window=win, area=area, region=region, active_object=obj):
            result = bpy.ops.object.join()

        if 'FINISHED' not in result:
            self.report({'ERROR'}, "Join failed.")
            return {'CANCELLED'}

        if p.mesh_join_merge:
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=obj):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                _merge_by_distance(p.mesh_join_threshold)
                bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, "Meshes joined.")
        return {'FINISHED'}
