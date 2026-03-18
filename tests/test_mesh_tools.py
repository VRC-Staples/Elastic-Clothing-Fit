# test_mesh_tools.py
# Regression tests for the mesh split and join tools (S02).
#
# REQUIRES: elastic_fit addon installed and enabled.
#           A VIEW_3D area must be open in Blender.
#
# Each STEP_* block creates its own test objects and cleans them up.
# Run each block via mcp__blender__execute_blender_code in order.

# ============================================================
# STEP 1: Properties exist with correct defaults
# ============================================================
STEP_1 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

p = bpy.context.scene.efit_props

print("\\n=== STEP 1: mesh tools properties exist with correct defaults ===")

_assert_true(hasattr(p, "mesh_split_mode"),      "mesh_split_mode property exists")
_assert_true(hasattr(p, "mesh_split_group"),     "mesh_split_group property exists")
_assert_true(hasattr(p, "mesh_join_merge"),      "mesh_join_merge property exists")
_assert_true(hasattr(p, "mesh_join_threshold"),  "mesh_join_threshold property exists")
_assert_equal(p.mesh_split_mode,     "LOOSE_PARTS", "mesh_split_mode default is LOOSE_PARTS")
_assert_equal(p.mesh_split_group,    "",            "mesh_split_group default is empty")
_assert_equal(p.mesh_join_merge,     False,         "mesh_join_merge default is False")

# threshold should be a small positive value
_assert_true(0.0 < p.mesh_join_threshold <= 0.01,
             f"mesh_join_threshold default is small positive ({p.mesh_join_threshold})")

print("\\n=== STEP 1 COMPLETE ===")
'''

# ============================================================
# STEP 2: Split by loose parts -- 2-island mesh produces 2 objects
# ============================================================
STEP_2 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 2: split by loose parts ===")

# Build a mesh with two completely disconnected triangles (two loose parts).
mesh_data = bpy.data.meshes.new("ECF_Split_LooseData")
mesh_data.from_pydata(
    # Verts: triangle A at z=0, triangle B at z=2
    [(0,0,0),(1,0,0),(0,1,0), (0,0,2),(1,0,2),(0,1,2)],
    [],
    [(0,1,2),(3,4,5)],
)
obj = bpy.data.objects.new("ECF_Split_LooseObj", mesh_data)
bpy.context.scene.collection.objects.link(obj)
for o in bpy.context.view_layer.objects:
    o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

count_before = len([o for o in bpy.context.scene.objects if o.type == "MESH"])

p = bpy.context.scene.efit_props
p.mesh_split_mode = "LOOSE_PARTS"

result = bpy.ops.efit.mesh_split()
_assert_equal(result, {"FINISHED"}, "efit.mesh_split returned FINISHED")

count_after = len([o for o in bpy.context.scene.objects if o.type == "MESH"])
_assert_equal(count_after, count_before + 1,
              f"scene has one more mesh object after split (before={count_before}, after={count_after})")

# Cleanup.
for o in list(bpy.context.scene.objects):
    if o.name.startswith("ECF_Split_Loose"):
        bpy.data.objects.remove(o, do_unlink=True)
if "ECF_Split_LooseData" in bpy.data.meshes:
    bpy.data.meshes.remove(bpy.data.meshes["ECF_Split_LooseData"])

print("\\n=== STEP 2 COMPLETE ===")
'''

# ============================================================
# STEP 3: Split by material -- 2-material mesh produces 2 objects
# ============================================================
STEP_3 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 3: split by material ===")

# Two faces sharing an edge -- assign different materials to each.
mesh_data = bpy.data.meshes.new("ECF_Split_MatData")
mesh_data.from_pydata(
    [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(2,0,0),(2,1,0)],
    [],
    [(0,1,2,3),(1,4,5,2)],
)
mat_a = bpy.data.materials.new("ECF_Split_MatA")
mat_b = bpy.data.materials.new("ECF_Split_MatB")
mesh_data.materials.append(mat_a)
mesh_data.materials.append(mat_b)
# Face 0 -> material 0, Face 1 -> material 1
for i, poly in enumerate(mesh_data.polygons):
    poly.material_index = i

obj = bpy.data.objects.new("ECF_Split_MatObj", mesh_data)
bpy.context.scene.collection.objects.link(obj)
for o in bpy.context.view_layer.objects:
    o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

count_before = len([o for o in bpy.context.scene.objects if o.type == "MESH"])

p = bpy.context.scene.efit_props
p.mesh_split_mode = "BY_MATERIAL"

result = bpy.ops.efit.mesh_split()
_assert_equal(result, {"FINISHED"}, "efit.mesh_split returned FINISHED")

count_after = len([o for o in bpy.context.scene.objects if o.type == "MESH"])
_assert_equal(count_after, count_before + 1,
              f"scene has one more mesh object after material split (before={count_before}, after={count_after})")

# Cleanup.
for o in list(bpy.context.scene.objects):
    if o.name.startswith("ECF_Split_Mat"):
        bpy.data.objects.remove(o, do_unlink=True)
for m in list(bpy.data.meshes):
    if m.name.startswith("ECF_Split_Mat"):
        bpy.data.meshes.remove(m)
for m in list(bpy.data.materials):
    if m.name.startswith("ECF_Split_Mat"):
        bpy.data.materials.remove(m)

print("\\n=== STEP 3 COMPLETE ===")
'''

# ============================================================
# STEP 4: Split by vertex group -- group verts separate into new object
# ============================================================
STEP_4 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 4: split by vertex group ===")

# Quad mesh: assign left two verts to a group, leave right two ungrouped.
mesh_data = bpy.data.meshes.new("ECF_Split_VGData")
mesh_data.from_pydata(
    [(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
    [],
    [(0,1,2,3)],
)
obj = bpy.data.objects.new("ECF_Split_VGObj", mesh_data)
bpy.context.scene.collection.objects.link(obj)
vg = obj.vertex_groups.new(name="ECF_TestGroup")
vg.add([0, 3], 1.0, "ADD")   # left two verts

for o in bpy.context.view_layer.objects:
    o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

count_before = len([o for o in bpy.context.scene.objects if o.type == "MESH"])

p = bpy.context.scene.efit_props
p.mesh_split_mode  = "BY_VERTEX_GROUP"
p.mesh_split_group = "ECF_TestGroup"

result = bpy.ops.efit.mesh_split()
_assert_equal(result, {"FINISHED"}, "efit.mesh_split returned FINISHED")

count_after = len([o for o in bpy.context.scene.objects if o.type == "MESH"])
_assert_equal(count_after, count_before + 1,
              f"scene has one more object after vertex group split (before={count_before}, after={count_after})")

# Poll should fail with empty group name.
p.mesh_split_group = ""
poll_result = bpy.ops.efit.mesh_split.poll()
_assert_equal(poll_result, False, "mesh_split poll returns False when group name is empty")

# Cleanup.
p.mesh_split_group = ""
p.mesh_split_mode  = "LOOSE_PARTS"
for o in list(bpy.context.scene.objects):
    if o.name.startswith("ECF_Split_VG"):
        bpy.data.objects.remove(o, do_unlink=True)
for m in list(bpy.data.meshes):
    if m.name.startswith("ECF_Split_VG"):
        bpy.data.meshes.remove(m)

print("\\n=== STEP 4 COMPLETE ===")
'''

# ============================================================
# STEP 5: Join -- 2 selected meshes produce 1 object
# ============================================================
STEP_5 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 5: join two meshes into one ===")

def _make_tri(name, offset_x):
    d = bpy.data.meshes.new(f"{name}Data")
    d.from_pydata(
        [(offset_x,0,0),(offset_x+1,0,0),(offset_x,1,0)], [], [(0,1,2)]
    )
    o = bpy.data.objects.new(name, d)
    bpy.context.scene.collection.objects.link(o)
    return o

obj_a = _make_tri("ECF_Join_A", 0.0)
obj_b = _make_tri("ECF_Join_B", 3.0)

for o in bpy.context.view_layer.objects:
    o.select_set(False)
obj_a.select_set(True)
obj_b.select_set(True)
bpy.context.view_layer.objects.active = obj_a

count_before = len([o for o in bpy.context.scene.objects if o.type == "MESH"])

p = bpy.context.scene.efit_props
p.mesh_join_merge = False

result = bpy.ops.efit.mesh_join()
_assert_equal(result, {"FINISHED"}, "efit.mesh_join returned FINISHED")

count_after = len([o for o in bpy.context.scene.objects if o.type == "MESH"])
_assert_equal(count_after, count_before - 1,
              f"scene has one fewer mesh object after join (before={count_before}, after={count_after})")

# The joined object should have verts from both original meshes.
active = bpy.context.view_layer.objects.active
_assert_true(active is not None and active.type == "MESH",
             "active object is a mesh after join")
_assert_equal(len(active.data.vertices), 6,
              "joined mesh has 6 vertices (3 from each original triangle)")

# Cleanup.
for o in list(bpy.context.scene.objects):
    if o.name.startswith("ECF_Join_"):
        bpy.data.objects.remove(o, do_unlink=True)
for m in list(bpy.data.meshes):
    if m.name.startswith("ECF_Join_"):
        bpy.data.meshes.remove(m)

print("\\n=== STEP 5 COMPLETE ===")
'''

# ============================================================
# STEP 6: Join with merge-by-distance -- coincident vertices collapsed
# ============================================================
STEP_6 = '''
import bpy

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 6: join with merge-by-distance collapses coincident vertices ===")

# Two triangles sharing an edge (4 unique vertices when merged, 6 before).
mesh_a_data = bpy.data.meshes.new("ECF_Merge_AData")
mesh_a_data.from_pydata([(0,0,0),(1,0,0),(0,1,0)], [], [(0,1,2)])
mesh_b_data = bpy.data.meshes.new("ECF_Merge_BData")
# Shares exactly the edge (0,0,0)-(1,0,0) with mesh_a
mesh_b_data.from_pydata([(0,0,0),(1,0,0),(0,-1,0)], [], [(0,1,2)])

obj_a = bpy.data.objects.new("ECF_Merge_A", mesh_a_data)
obj_b = bpy.data.objects.new("ECF_Merge_B", mesh_b_data)
bpy.context.scene.collection.objects.link(obj_a)
bpy.context.scene.collection.objects.link(obj_b)

for o in bpy.context.view_layer.objects:
    o.select_set(False)
obj_a.select_set(True)
obj_b.select_set(True)
bpy.context.view_layer.objects.active = obj_a

p = bpy.context.scene.efit_props
p.mesh_join_merge     = True
p.mesh_join_threshold = 0.001

result = bpy.ops.efit.mesh_join()
_assert_equal(result, {"FINISHED"}, "efit.mesh_join with merge returned FINISHED")

joined = bpy.context.view_layer.objects.active
vert_count = len(joined.data.vertices)
# Without merge: 6 verts. With merge of the 2 shared verts: 4 verts.
_assert_equal(vert_count, 4,
              f"merge-by-distance collapsed 2 coincident vertices (expected 4, got {vert_count})")

# Cleanup.
p.mesh_join_merge = False
for o in list(bpy.context.scene.objects):
    if o.name.startswith("ECF_Merge_"):
        bpy.data.objects.remove(o, do_unlink=True)
for m in list(bpy.data.meshes):
    if m.name.startswith("ECF_Merge_"):
        bpy.data.meshes.remove(m)

print("\\n=== STEP 6 COMPLETE ===")
print("\\n=== ALL MESH TOOLS TESTS COMPLETE ===")
'''
