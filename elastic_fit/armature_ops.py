# armature_ops.py
# Armature utility operators for Elastic Clothing Fit.
# Provides display-mode batch setting and source-into-target armature merging.

import bpy
from bpy.types import Operator


def _align_armature(source, target):
    """Translate source armature to align root bones with target.

    Finds the root bone (no parent) of each armature and translates
    the source so root bones overlap -- like pressing G to grab and move.
    Also translates unparented meshes that use this armature via modifier.

    Returns (success: bool, message: str).
    """
    src_bones = source.data.bones
    tgt_bones = target.data.bones

    # Find root bones (bones with no parent).
    src_roots = [b for b in src_bones if b.parent is None]
    tgt_roots = [b for b in tgt_bones if b.parent is None]

    if not src_roots or not tgt_roots:
        return False, "Could not find root bones"

    # World-space root bone head positions.
    src_root_pos = source.matrix_world @ src_roots[0].head_local
    tgt_root_pos = target.matrix_world @ tgt_roots[0].head_local

    delta = tgt_root_pos - src_root_pos

    # Translate the armature object (parented children follow automatically).
    source.location = source.location + delta
    bpy.context.view_layer.update()

    # Translate unparented meshes that reference this armature via modifier.
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.parent == source:
            continue
        if any(m.type == 'ARMATURE' and m.object == source for m in obj.modifiers):
            obj.location = obj.location + delta
    bpy.context.view_layer.update()

    return True, ""


class EFIT_OT_armature_display(Operator):
    bl_idname      = "efit.armature_display"
    bl_label       = "Apply Display Settings"
    bl_description = "Apply the display type and In Front settings to the selected armature"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        p   = context.scene.efit_props
        obj = context.active_object
        obj.data.display_type = p.armature_display_type
        obj.show_in_front     = p.armature_show_in_front
        self.report({'INFO'}, f"Updated {obj.name}")
        return {'FINISHED'}


class EFIT_OT_merge_armatures(Operator):
    bl_idname = "efit.merge_armatures"
    bl_label  = "Merge Armatures"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p     = context.scene.efit_props
        base  = p.merge_source_armature
        donor = p.merge_target_armature
        return (
            base is not None
            and donor is not None
            and base != donor
            and base.type == 'ARMATURE'
            and donor.type == 'ARMATURE'
            and context.mode == 'OBJECT'
        )

    def execute(self, context):
        p     = context.scene.efit_props
        donor = p.merge_target_armature   # "To Merge" -- gets aligned and removed
        base  = p.merge_source_armature   # "Base" -- stays

        if p.merge_align_first:
            # Skip alignment when there are fewer than 2 shared bone names --
            # not enough correspondence to compute a meaningful alignment.
            base_bone_names  = {b.name.lower() for b in base.data.bones}
            donor_bone_names = {b.name.lower() for b in donor.data.bones}
            shared_count = len(base_bone_names & donor_bone_names)
            if shared_count < 2:
                self.report({'WARNING'}, f"Align skipped: fewer than 2 shared bones ({shared_count})")
            else:
                ok, msg = _align_armature(donor, base)
                if not ok:
                    self.report({'WARNING'}, f"Align skipped: {msg}")

        if p.merge_bones:
            # bpy.ops.object.join() does not commit reliably when called from within
            # another operator's execute. Implement the merge manually instead:
            # read donor edit_bones (including roll), write to base, then remove donor.
            win  = context.window_manager.windows[0]
            area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
            if area is None:
                self.report({'ERROR'}, "Merge requires an open 3D Viewport")
                return {'CANCELLED'}
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)

            # Pass 1: read all bone data from donor edit_bones (roll only exists there).
            # active_object= must be passed directly to temp_override so that
            # mode_set.poll() can resolve it inside the overridden context.
            for obj in context.view_layer.objects:
                obj.select_set(False)
            donor.select_set(True)
            context.view_layer.objects.active = donor
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor):
                bpy.ops.object.mode_set(mode='EDIT')
            bone_data = {
                eb.name: {
                    'head':        eb.head.copy(),
                    'tail':        eb.tail.copy(),
                    'roll':        eb.roll,
                    'parent':      eb.parent.name if eb.parent else None,
                    'use_connect': eb.use_connect,
                }
                for eb in donor.data.edit_bones
            }
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor):
                bpy.ops.object.mode_set(mode='OBJECT')

            # Pass 2: write bones into base edit_bones.
            donor_to_base = base.matrix_world.inverted() @ donor.matrix_world
            for obj in context.view_layer.objects:
                obj.select_set(False)
            base.select_set(True)
            context.view_layer.objects.active = base
            with bpy.context.temp_override(window=win, area=area, region=region, active_object=base):
                bpy.ops.object.mode_set(mode='EDIT')

            base_edit  = base.data.edit_bones
            base_lower = {eb.name.lower(): eb.name for eb in base_edit}
            bone_map   = {}
            for name, bd in bone_data.items():
                base_name = base_lower.get(name.lower())
                if base_name is not None:
                    bone_map[name] = base_edit[base_name]
                    continue
                eb             = base_edit.new(name)
                eb.head        = donor_to_base @ bd['head']
                eb.tail        = donor_to_base @ bd['tail']
                eb.roll        = bd['roll']
                bone_map[name] = eb
            for name, bd in bone_data.items():
                if bd['parent'] and bd['parent'] in bone_map:
                    eb = bone_map[name]
                    if eb.parent is None:
                        eb.parent      = bone_map[bd['parent']]
                        eb.use_connect = bd['use_connect']

            with bpy.context.temp_override(window=win, area=area, region=region, active_object=base):
                bpy.ops.object.mode_set(mode='OBJECT')

            # Reparent donor's child meshes to base, then remove donor.
            for obj in list(bpy.data.objects):
                if obj.parent == donor and obj.type == 'MESH':
                    mat = obj.matrix_world.copy()
                    obj.parent = base
                    obj.matrix_world = mat
                    for mod in obj.modifiers:
                        if mod.type == 'ARMATURE' and mod.object == donor:
                            mod.object = base

            bpy.data.objects.remove(donor, do_unlink=True)
            self.report({'INFO'}, "Armatures merged")
        else:
            for obj in list(bpy.data.objects):
                if obj.parent == donor and obj.type == 'MESH':
                    mat = obj.matrix_world.copy()
                    obj.parent = base
                    obj.matrix_world = mat
                    for mod in obj.modifiers:
                        if mod.type == 'ARMATURE' and mod.object == donor:
                            mod.object = base
            self.report({'INFO'}, "Child meshes reparented to base armature")

        return {'FINISHED'}
