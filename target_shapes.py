r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import target_shapes
importlib.reload(target_shapes)

# add brand-new targets
target_shapes.run()

# or refresh deltas on already-wired targets after sculpting the geos
# (requires all pose weights to be 0 so the base mesh is neutral)
# target_shapes.update()
"""

from __future__ import annotations

import maya.cmds as mc

TARGETS_GROUP: str = "targets_group"

# side prefix -> (geo prefix, hand ctrl transform)
SIDE_MAP: dict[str, tuple[str, str]] = {
    "lft_": ("L", "lft_hand_ctrl"),
    "rgt_": ("R", "rgt_hand_ctrl"),
}

GEO_TEMPLATE: str = "{geo_prefix}_arm_001_GEO"
BLEND_SUFFIX: str = "_blendShape"
NAME_SUFFIX: str = "_shape"


def run(targets_group: str = TARGETS_GROUP) -> None:
    """Wire every `<side>_..._shape` geo under `targets_group` to the matching
    side's blend shape and hand ctrl shape.

    Example: `lft_fist_wrist_shape`
      -> alias `fistWrist`
      -> add as target on `L_arm_001_GEO_blendShape`
      -> connect `lft_hand_ctrlShape.fistWrist` -> `L_arm_001_GEO_blendShape.fistWrist`
    """
    if not mc.objExists(targets_group):
        mc.warning(f"Group '{targets_group}' not found.")
        return

    children = mc.listRelatives(targets_group, children=True, fullPath=False) or []
    if not children:
        mc.warning(f"No children under '{targets_group}'.")
        return

    added = 0
    for geo in children:
        side = _side_prefix(geo)
        if side is None:
            continue
        if not geo.endswith(NAME_SUFFIX):
            mc.warning(f"'{geo}' does not end with '{NAME_SUFFIX}'; skipping.")
            continue

        geo_prefix, ctrl = SIDE_MAP[side]
        base_geo = GEO_TEMPLATE.format(geo_prefix=geo_prefix)
        blend = f"{base_geo}{BLEND_SUFFIX}"

        if not mc.objExists(base_geo):
            mc.warning(f"Base geo '{base_geo}' not found; skipping '{geo}'.")
            continue
        if not mc.objExists(blend):
            mc.warning(f"Blend shape '{blend}' not found; skipping '{geo}'.")
            continue

        ctrl_shape = _shape(ctrl)
        if not ctrl_shape:
            mc.warning(f"No shape under '{ctrl}'; skipping '{geo}'.")
            continue

        middle = geo[len(side) : -len(NAME_SUFFIX)]
        if not middle:
            mc.warning(f"Empty middle token from '{geo}'; skipping.")
            continue
        alias = _camel(middle)

        if _add_target(blend, base_geo, geo, alias):
            _connect(ctrl_shape, blend, alias)
            added += 1

    print(f"\n[DONE] Added/wired {added} target(s).")


def update(targets_group: str = TARGETS_GROUP) -> None:
    """Refresh blend shape target deltas in place from edited target geos.

    Run after sculpting the `<side>_..._shape` geos under `targets_group`.
    Keeps the existing alias / index / ctrl-shape connection and only
    rewrites the per-vertex deltas at full weight (item index 6000).

    Requires every weight on the affected blend shape to be 0 so the base
    mesh is in its neutral state — otherwise the captured base positions are
    partially deformed and the resulting deltas would be wrong. Geos on a
    blend that fails this check are skipped with a warning.
    """
    if not mc.objExists(targets_group):
        mc.warning(f"Group '{targets_group}' not found.")
        return

    children = mc.listRelatives(targets_group, children=True, fullPath=False) or []
    if not children:
        mc.warning(f"No children under '{targets_group}'.")
        return

    updated = 0
    for geo in children:
        side = _side_prefix(geo)
        if side is None:
            continue
        if not geo.endswith(NAME_SUFFIX):
            mc.warning(f"'{geo}' does not end with '{NAME_SUFFIX}'; skipping.")
            continue

        geo_prefix, _ = SIDE_MAP[side]
        base_geo = GEO_TEMPLATE.format(geo_prefix=geo_prefix)
        blend = f"{base_geo}{BLEND_SUFFIX}"

        if not mc.objExists(base_geo):
            mc.warning(f"Base geo '{base_geo}' not found; skipping '{geo}'.")
            continue
        if not mc.objExists(blend):
            mc.warning(f"Blend shape '{blend}' not found; skipping '{geo}'.")
            continue

        if not _weights_neutral(blend):
            mc.warning(
                f"'{blend}' has non-zero weights; set all poses to 0 before "
                f"update. Skipping '{geo}'."
            )
            continue

        middle = geo[len(side) : -len(NAME_SUFFIX)]
        if not middle:
            mc.warning(f"Empty middle token from '{geo}'; skipping.")
            continue
        alias = _camel(middle)

        idx = _alias_index(blend, alias)
        if idx is None:
            mc.warning(f"Alias '{alias}' not found on '{blend}'; skipping '{geo}'.")
            continue

        if _refresh_deltas(blend, base_geo, geo, idx):
            print(f"  ~{blend}.{alias}  (deltas refreshed from {geo})")
            updated += 1

    print(f"\n[DONE] Refreshed {updated} target(s).")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _side_prefix(name: str) -> str | None:
    for prefix in SIDE_MAP:
        if name.startswith(prefix):
            return prefix
    return None


def _shape(node: str) -> str | None:
    if mc.objectType(node, isAType="shape"):
        return node
    shapes = mc.listRelatives(node, shapes=True, noIntermediate=True) or []
    return shapes[0] if shapes else None


def _camel(snake: str) -> str:
    """fist_wrist -> fistWrist (first word lowercase, rest capitalised)."""
    parts = [p for p in snake.split("_") if p]
    if not parts:
        return ""
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _next_index(blend: str) -> int:
    indices = mc.getAttr(f"{blend}.weight", multiIndices=True) or []
    return (max(indices) + 1) if indices else 0


def _add_target(blend: str, base_geo: str, target_geo: str, alias: str) -> bool:
    if mc.attributeQuery(alias, node=blend, exists=True):
        mc.warning(f"'{blend}.{alias}' already exists; skipping.")
        return False
    index = _next_index(blend)
    mc.blendShape(
        blend,
        edit=True,
        target=(base_geo, index, target_geo, 1.0),
    )
    mc.aliasAttr(alias, f"{blend}.weight[{index}]")
    print(f"  +{blend}.{alias}  ({target_geo} @ index {index})")
    return True


def _connect(ctrl_shape: str, blend: str, alias: str) -> None:
    src = f"{ctrl_shape}.{alias}"
    dst = f"{blend}.{alias}"
    if not mc.attributeQuery(alias, node=ctrl_shape, exists=True):
        mc.warning(f"'{src}' does not exist; skipping connect.")
        return
    existing = mc.listConnections(dst, source=True, plugs=True) or []
    if src in existing:
        print(f"  [~] already connected: {src} -> {dst}")
        return
    mc.connectAttr(src, dst, force=True)
    print(f"  -> {src} -> {dst}")


def _weights_neutral(blend: str, eps: float = 1e-6) -> bool:
    indices = mc.getAttr(f"{blend}.weight", multiIndices=True) or []
    for i in indices:
        if abs(mc.getAttr(f"{blend}.weight[{i}]")) > eps:
            return False
    return True


def _alias_index(blend: str, alias: str) -> int | None:
    indices = mc.getAttr(f"{blend}.weight", multiIndices=True) or []
    for i in indices:
        if mc.aliasAttr(f"{blend}.weight[{i}]", query=True) == alias:
            return i
    return None


def _refresh_deltas(blend: str, base_geo: str, target_geo: str, index: int) -> bool:
    """Recompute per-vertex deltas (target - base) and write them to the
    blend shape's inputTargetItem[6000] for the given weight index.
    """
    base_shape = _shape(base_geo)
    target_shape = _shape(target_geo)
    if not base_shape or not target_shape:
        mc.warning(f"Missing shape on '{base_geo}' or '{target_geo}'; skipping.")
        return False

    n_base = mc.polyEvaluate(base_shape, vertex=True)
    n_target = mc.polyEvaluate(target_shape, vertex=True)
    if n_base != n_target:
        mc.warning(
            f"Vertex count mismatch: '{base_shape}'={n_base}, "
            f"'{target_shape}'={n_target}; skipping."
        )
        return False

    base_pts = mc.xform(f"{base_shape}.vtx[*]", q=True, t=True, os=True)
    target_pts = mc.xform(f"{target_shape}.vtx[*]", q=True, t=True, os=True)

    points: list[tuple[float, float, float, float]] = []
    components: list[str] = []
    eps = 1e-6
    for i in range(n_base):
        dx = target_pts[i * 3] - base_pts[i * 3]
        dy = target_pts[i * 3 + 1] - base_pts[i * 3 + 1]
        dz = target_pts[i * 3 + 2] - base_pts[i * 3 + 2]
        if abs(dx) > eps or abs(dy) > eps or abs(dz) > eps:
            points.append((dx, dy, dz, 1.0))
            components.append(f"vtx[{i}]")

    item = f"{blend}.inputTarget[0].inputTargetGroup[{index}].inputTargetItem[6000]"
    n_points = len(points)
    if n_points:
        mc.setAttr(f"{item}.inputPointsTarget", n_points, *points, type="pointArray")
        mc.setAttr(
            f"{item}.inputComponentsTarget",
            n_points,
            *components,
            type="componentList",
        )
    else:
        mc.setAttr(f"{item}.inputPointsTarget", 0, type="pointArray")
        mc.setAttr(f"{item}.inputComponentsTarget", 0, type="componentList")
    return True
