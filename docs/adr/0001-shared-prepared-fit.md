# Share the prepared fit calculation

Initial fitting and live preview use `PreparedFit` in `elastic_fit/deformation.py` for the same calculations and operation order.
Each prepared fit owns its vertex mapping and derived caches, so one preview cannot borrow another preview's topology.
Blender callers retain mesh access and lifecycle effects instead of making initial fitting invoke preview callbacks or expose incomplete global state.
Initial fitting retains its float32 mesh boundaries before group offsets and preserve-follow.
Live preview retains its existing float64 intermediate calculations.
Only eligible preserved vertices are follow targets. Vertices outside exclusive groups stay fixed.
Initial fitting leaves the proximity cache key unset, so the first preview reads current group membership.
