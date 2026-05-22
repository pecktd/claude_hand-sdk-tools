r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import add_target_shapes
importlib.reload(add_target_shapes)

add_target_shapes.run()
"""
from __future__ import annotations

import maya.cmds as mc


TARGETS_GROUP: str = "targets"

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
