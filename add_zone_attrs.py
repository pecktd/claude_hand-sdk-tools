r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import add_zone_attrs
importlib.reload(add_zone_attrs)

add_zone_attrs.ZoneAttributeBuilder(
    prefix="mega",
    node="lft_hand_ctrl",
).run()
"""
from __future__ import annotations

import maya.cmds as mc


class ZoneAttributeBuilder:
    """Add per-zone float attributes to a node's shape.

    Each zone name in `ATTRIBUTES` is snake_case; the attr added on the
    shape is `<prefix><CamelCaseZone>` (e.g. prefix=`mega` and zone
    `thenar_pad` -> `megaThenarPad`).  Attrs are float 0..1, default 0,
    keyable.
    """

    ATTRIBUTES: tuple[str, ...] = (
        "wrist",
        "upper_hand",
        "upper_thumb_1",
        "thumb_2",
        "thumb_3",
        "thumb_4",
        "thumb_5",
        "lower_thumb_1",
        "upper_index_2",
        "lower_index_2",
        "index_3",
        "index_4",
        "index_5",
        "index_6",
        "index_7",
        "upper_middle_2",
        "lower_middle_2",
        "middle_3",
        "middle_4",
        "middle_5",
        "middle_6",
        "middle_7",
        "upper_ring_2",
        "lower_ring_2",
        "ring_3",
        "ring_4",
        "ring_5",
        "ring_6",
        "ring_7",
        "upper_pinky_2",
        "lower_pinky_2",
        "pinky_3",
        "pinky_4",
        "pinky_5",
        "pinky_6",
        "pinky_7",
        "lower_hand",
    )

    def __init__(
        self,
        prefix: str,
        node: str,
        attributes: tuple[str, ...] = ATTRIBUTES,
    ) -> None:
        self.prefix: str = prefix
        self.node: str = node
        self.attributes: tuple[str, ...] = tuple(attributes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        if not mc.objExists(self.node):
            mc.warning(f"Node '{self.node}' not found.")
            return

        shape = self._shape(self.node)
        if not shape:
            mc.warning(f"No shape under '{self.node}'.")
            return

        self._add_separator(shape, f"__{self.prefix}Pose__")

        added = 0
        for zone in self.attributes:
            attr = f"{self.prefix}{self._camel(zone)}"
            if self._add(shape, attr):
                added += 1

        print(f"\n[DONE] Added {added}/{len(self.attributes)} attr(s) to '{shape}'.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _shape(node: str) -> str | None:
        if mc.objectType(node, isAType="shape"):
            return node
        shapes = mc.listRelatives(node, shapes=True, noIntermediate=True) or []
        return shapes[0] if shapes else None

    @staticmethod
    def _camel(snake: str) -> str:
        return "".join(part.capitalize() for part in snake.split("_"))

    @staticmethod
    def _add_separator(shape: str, attr: str) -> bool:
        if mc.attributeQuery(attr, node=shape, exists=True):
            mc.warning(f"'{shape}.{attr}' already exists; skipping.")
            return False
        mc.addAttr(
            shape,
            longName=attr,
            attributeType="long",
            defaultValue=0,
            keyable=True,
        )
        mc.setAttr(f"{shape}.{attr}", lock=True)
        print(f"  +{shape}.{attr} (separator)")
        return True

    @staticmethod
    def _add(shape: str, attr: str) -> bool:
        if mc.attributeQuery(attr, node=shape, exists=True):
            mc.warning(f"'{shape}.{attr}' already exists; skipping.")
            return False
        mc.addAttr(
            shape,
            longName=attr,
            attributeType="float",
            min=0.0,
            max=1.0,
            defaultValue=0.0,
            keyable=True,
        )
        print(f"  +{shape}.{attr}")
        return True
