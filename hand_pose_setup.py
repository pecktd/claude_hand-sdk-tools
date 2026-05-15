r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import hand_pose_setup
importlib.reload(hand_pose_setup)

hand_pose_setup.HandPoseBuilder(
    finger_parts={
        "fist": {
            "1": ["thumb_1", "index_1", "middle_1", "ring_1", "pinky_1"],
            "2": ["thumb_2", "index_2", "middle_2", "ring_2", "pinky_2"],
            "3": ["thumb_3", "index_3", "middle_3", "ring_3", "pinky_3"],
        },
        "pistol": None,
    },
).build()
"""
from __future__ import annotations

from typing import cast

import maya.cmds as mc


class HandPoseBuilder:
    """Build pose-driven finger SDKs split into per-level sub-poses.

    For each pose discovered under `pose_root`, this creates a locked
    separator attr (e.g. `__poseFist__`) followed by two kinds of float
    attributes on the hand ctrl:

      - one "whole" attr per pose (e.g. poseFist) that drives every selected
        level at once,
      - one "part" attr per level (e.g. poseFist1, poseFist2, poseFist3) that
        drives only that level.

    A `plusMinusAverage` node per (pose, side, level) sums `whole + part`,
    and the SDK from that sum's `output1D` drives the finger offsets.  Sums
    above the SDK's keyed max clamp at the posed value (animCurve constant
    post-infinity), so dialing whole=10 + partN=10 simply means "full pose".

    Level N's SDK is built with levels 1..N-1 already posed (via the part
    attr at max), so the world-space match for child joints is correct.
    After all levels are keyed, part attrs reset to 0 and the whole stays
    at 0.

    `finger_parts` selects which joints receive SDK keys.  It is a dict
    keyed by pose name; each value is either a nested dict grouped by
    sub-pose level (per-level mode) or `None` (whole-only mode):

        {
            "fist": {
                "1": ["thumb_1", "index_1", "middle_1"],
                "2": ["thumb_2", "index_2"],
            },
            "pistol": None,
        }

    Only poses listed in the outer dict are built.

    Per-level mode: only the listed levels get SDK keys, summed with the
    whole attr through a `plusMinusAverage` per level.  The level string
    matches the sub-pose attr suffix (e.g. "1" -> `poseFist1`).  Inner
    entries are finger names; a trailing "_N" suffix is tolerated but
    ignored — the outer level key is authoritative.

    Whole-only mode (`None`): only the separator and whole attr are added;
    every joint in the pose is SDK-driven directly from the whole attr,
    with no per-level part attrs or sum nodes.

    Joints that are matched but not selected for SDK are still posed during
    the build so child joints land correctly in world space, then zeroed
    back to identity in the cleanup pass.
    """

    FINGER_PARTS: tuple[str, ...] = ("thumb", "index", "middle", "ring", "pinky")
    DEFAULT_DRIVER_MAX: int = 10

    def __init__(
        self,
        finger_parts: dict[str, dict[str, list[str] | tuple[str, ...]] | None],
        pose_root: str = "hand_pose_grp",
        sides: tuple[str, ...] = ("lft", "rgt"),
        max_driver_value: float = DEFAULT_DRIVER_MAX,
    ) -> None:
        self.pose_root: str = pose_root
        self.sides: tuple[str, ...] = tuple(sides)
        self.max_driver_value: float = max_driver_value
        self._pose_filter: set[str] = set(finger_parts.keys())
        self._joint_filter: dict[str, frozenset[tuple[str, int]] | None] = {
            pose: None if value is None else self._parse_nested_entries(value)
            for pose, value in finger_parts.items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        if not mc.objExists(self.pose_root):
            mc.warning(f"'{self.pose_root}' not found.")
            return

        pose_sides = self._discover_pose_sides()
        if not pose_sides:
            mc.warning(f"No finger pose joints found under '{self.pose_root}'.")
            return

        for (pose, side), joints in pose_sides.items():
            self.build_pose(pose, side, joints)

        print("\n[DONE] Pose-driven finger setup complete.")

    def build_pose(
        self,
        pose: str,
        side: str,
        joints: list[str] | None = None,
    ) -> None:
        if pose not in self._pose_filter:
            return

        hand_ctrl = f"{side}_hand_ctrl"
        if not mc.objExists(hand_ctrl):
            mc.warning(f"Missing: {hand_ctrl}")
            return

        if joints is None:
            joints = self._joints_for_pose_side(pose, side)
            if not joints:
                mc.warning(f"No finger joints found for pose='{pose}' side='{side}'.")
                return

        levels = self._group_by_level(joints)
        if self._joint_filter[pose] is None:
            self._build_pose_whole_only(pose, side, hand_ctrl, levels)
        else:
            self._build_pose_per_level(pose, side, hand_ctrl, levels)

    def _build_pose_per_level(
        self,
        pose: str,
        side: str,
        hand_ctrl: str,
        levels: dict[int, list[str]],
    ) -> None:
        print(f"\n[POSE] '{pose}' [{side}] -> {hand_ctrl}")

        built_part_attrs: list[str] = []
        match_only_ofsts: set[str] = set()

        pose_separator_attr = self._pose_separator_attr_name(pose)
        whole_attr_name = self._whole_pose_attr_name(pose)
        whole_attr_plug = f"{hand_ctrl}.{whole_attr_name}"
        pose_attrs_added = False

        for level in sorted(levels.keys()):
            part_attr_name = self._sub_pose_attr_name(pose, level)
            part_attr_plug = f"{hand_ctrl}.{part_attr_name}"
            sum_node = self._sum_node_name(side, pose, level)
            sdk_driver_attr = f"{sum_node}.output1D"
            level_has_sdk = False

            for jnt in levels[level]:
                tokens = jnt.split("_")
                part = tokens[2]
                ctrl_ofst = f"{side}_{part}_{level}_ctrl_ofst"

                if not mc.objExists(ctrl_ofst):
                    mc.warning(f"  Missing ctrl_ofst: {ctrl_ofst}")
                    continue

                # Match every joint in the pose — the hierarchy must be in
                # world-space pose before child levels are processed.
                pose_t, pose_r = self._match_transform(jnt, ctrl_ofst)

                if self._is_selected(pose, part, level):
                    if not level_has_sdk:
                        if not pose_attrs_added:
                            self._add_separator(hand_ctrl, pose_separator_attr)
                            self._add_pose_float_attr(hand_ctrl, whole_attr_name, "whole")
                            pose_attrs_added = True
                        self._add_pose_float_attr(hand_ctrl, part_attr_name, "part")
                        self._ensure_sum_node(sum_node, whole_attr_plug, part_attr_plug)
                        self._ensure_norm_mult(f"{side}_{part_attr_name}_outMult", sdk_driver_attr)
                        level_has_sdk = True
                    self._set_sdk(sdk_driver_attr, ctrl_ofst, pose_t, pose_r)
                    print(
                        f"    [SDK] L{level} {sdk_driver_attr} -> {ctrl_ofst}  "
                        f"t={[round(v, 3) for v in pose_t]}  "
                        f"r={[round(v, 3) for v in pose_r]}"
                    )
                else:
                    match_only_ofsts.add(ctrl_ofst)
                    print(f"    [match-only] L{level} {ctrl_ofst}")

            if level_has_sdk:
                # Pose this level via its part attr so the next level's child
                # joints land correctly in world space.  Whole stays at 0.
                mc.setAttr(part_attr_plug, self.max_driver_value)
                built_part_attrs.append(part_attr_plug)

        # Cleanup: part attrs back to 0 (sum -> 0, SDK pulls keyed ofsts to
        # identity), then explicitly zero match-only ofsts.
        for part_attr_plug in built_part_attrs:
            mc.setAttr(part_attr_plug, 0)

        for ctrl_ofst in match_only_ofsts:
            self._zero_offset(ctrl_ofst)

    def _build_pose_whole_only(
        self,
        pose: str,
        side: str,
        hand_ctrl: str,
        levels: dict[int, list[str]],
    ) -> None:
        print(f"\n[POSE] '{pose}' [{side}] -> {hand_ctrl}  (whole-only)")

        separator_attr = self._pose_separator_attr_name(pose)
        whole_attr_name = self._whole_pose_attr_name(pose)
        whole_attr_plug = f"{hand_ctrl}.{whole_attr_name}"

        self._add_separator(hand_ctrl, separator_attr)
        self._add_pose_float_attr(hand_ctrl, whole_attr_name, "whole")
        self._ensure_norm_mult(f"{side}_{whole_attr_name}_outMult", whole_attr_plug)
        # Pre-set whole to max so each newly keyed joint snaps to its posed
        # value as its SDK is added, letting child levels match correctly
        # in world space.  No SDK exists yet, so this is a no-op until the
        # first key is set.
        mc.setAttr(whole_attr_plug, self.max_driver_value)

        for level in sorted(levels.keys()):
            for jnt in levels[level]:
                tokens = jnt.split("_")
                part = tokens[2]
                ctrl_ofst = f"{side}_{part}_{level}_ctrl_ofst"

                if not mc.objExists(ctrl_ofst):
                    mc.warning(f"  Missing ctrl_ofst: {ctrl_ofst}")
                    continue

                pose_t, pose_r = self._match_transform(jnt, ctrl_ofst)
                self._set_sdk(whole_attr_plug, ctrl_ofst, pose_t, pose_r)
                print(
                    f"    [SDK] L{level} {whole_attr_plug} -> {ctrl_ofst}  "
                    f"t={[round(v, 3) for v in pose_t]}  "
                    f"r={[round(v, 3) for v in pose_r]}"
                )

        mc.setAttr(whole_attr_plug, 0)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_nested_entries(
        sub_poses: dict[str, list[str] | tuple[str, ...]],
    ) -> frozenset[tuple[str, int]]:
        """Parse {"1": [...], "2": [...]} into (finger, level) pairs.

        The outer key is the level (str of int) and is authoritative; any
        trailing "_N" suffix on entries is stripped.
        """
        out: set[tuple[str, int]] = set()
        for level_key, entries in sub_poses.items():
            level = int(level_key)
            for e in entries:
                s = str(e)
                head, _, tail = s.rpartition("_")
                finger = head if head and tail.isdigit() else s
                out.add((finger, level))
        return frozenset(out)

    def _is_selected(self, pose: str, finger: str, level: int) -> bool:
        return (finger, level) in self._joint_filter[pose]

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_pose_sides(self) -> dict[tuple[str, str], list[str]]:
        all_joints: list[str] = (
            mc.listRelatives(self.pose_root, allDescendents=True, type="joint") or []
        )
        pose_sides: dict[tuple[str, str], list[str]] = {}
        for jnt in all_joints:
            short = jnt.split("|")[-1]
            tokens = short.split("_")
            if len(tokens) < 4:
                continue
            pose, side, part = tokens[0], tokens[1], tokens[2]
            if side not in self.sides:
                continue
            if part not in self.FINGER_PARTS:
                continue
            try:
                int(tokens[3])
            except ValueError:
                continue
            pose_sides.setdefault((pose, side), []).append(short)
        return pose_sides

    def _joints_for_pose_side(self, pose: str, side: str) -> list[str]:
        return self._discover_pose_sides().get((pose, side), [])

    @staticmethod
    def _group_by_level(joints: list[str]) -> dict[int, list[str]]:
        levels: dict[int, list[str]] = {}
        for jnt in joints:
            tokens = jnt.split("_")
            try:
                level = int(tokens[3])
            except (IndexError, ValueError):
                continue
            levels.setdefault(level, []).append(jnt)
        return levels

    # ------------------------------------------------------------------
    # Attribute helpers
    # ------------------------------------------------------------------

    def _add_separator(self, ctrl: str, attr_name: str) -> None:
        if not mc.attributeQuery(attr_name, node=ctrl, exists=True):
            mc.addAttr(
                ctrl,
                longName=attr_name,
                attributeType="long",
                defaultValue=0,
                keyable=True,
            )
            mc.setAttr(f"{ctrl}.{attr_name}", lock=True)
            print(f"  [+] Added separator: {ctrl}.{attr_name}")
        else:
            print(f"  [~] Separator exists: {ctrl}.{attr_name}")

    def _add_pose_float_attr(self, ctrl: str, attr_name: str, label: str = "attr") -> None:
        if not mc.attributeQuery(attr_name, node=ctrl, exists=True):
            mc.addAttr(
                ctrl,
                longName=attr_name,
                attributeType="float",
                minValue=0,
                maxValue=self.max_driver_value,
                defaultValue=0,
                keyable=True,
            )
            print(f"  [+] Added {label}: {ctrl}.{attr_name}")
        else:
            print(f"  [~] {label.capitalize()} exists: {ctrl}.{attr_name}")

    def _ensure_norm_mult(self, mult_node: str, source_plug: str) -> None:
        """Create a `multDoubleLinear` that scales `source_plug` by
        `1 / max_driver_value`, producing a 0..1 normalized signal.  The
        node's `.output` is left unconnected — downstream rigs wire it as
        needed.

        Any prior incoming connection on `.input1` that doesn't match
        `source_plug` is explicitly broken first, so reruns over a scene
        built by an older script version are correctly rewired.
        """
        if not mc.objExists(mult_node):
            mc.createNode("multDoubleLinear", name=mult_node)
            print(f"  [+] Created norm-mult: {mult_node}")
        mc.setAttr(f"{mult_node}.input2", 1.0 / self.max_driver_value)

        input1_plug = f"{mult_node}.input1"
        existing = mc.listConnections(
            input1_plug, source=True, destination=False, plugs=True
        ) or []
        for src in existing:
            if src != source_plug:
                mc.disconnectAttr(src, input1_plug)
                print(f"  [-] Disconnected stale source: {src} -X-> {input1_plug}")
        if not mc.isConnected(source_plug, input1_plug):
            mc.connectAttr(source_plug, input1_plug, force=True)
            print(f"  [+] Connected: {source_plug} -> {input1_plug}")

    @staticmethod
    def _whole_pose_attr_name(pose: str) -> str:
        # Uppercase only the first letter; preserve any camelCase in the token.
        return f"pose{pose[:1].upper()}{pose[1:]}"

    @staticmethod
    def _pose_separator_attr_name(pose: str) -> str:
        return f"__pose{pose[:1].upper()}{pose[1:]}__"

    @staticmethod
    def _sub_pose_attr_name(pose: str, level: int) -> str:
        return f"{HandPoseBuilder._whole_pose_attr_name(pose)}{level}"

    @staticmethod
    def _sum_node_name(side: str, pose: str, level: int) -> str:
        return f"{side}_{pose}_{level}_poseSum"

    def _ensure_sum_node(self, sum_node: str, whole_plug: str, part_plug: str) -> None:
        if not mc.objExists(sum_node):
            mc.createNode("plusMinusAverage", name=sum_node)
            mc.setAttr(f"{sum_node}.operation", 1)  # 1 == sum
            print(f"  [+] Created sum node: {sum_node}")
        self._connect_input(whole_plug, f"{sum_node}.input1D[0]")
        self._connect_input(part_plug, f"{sum_node}.input1D[1]")

    @staticmethod
    def _connect_input(src: str, dst: str) -> None:
        if not mc.isConnected(src, dst):
            mc.connectAttr(src, dst, force=True)

    # ------------------------------------------------------------------
    # Transform + SDK
    # ------------------------------------------------------------------

    @staticmethod
    def _match_transform(source: str, target: str) -> tuple[list[float], list[float]]:
        ws_t = mc.xform(source, q=True, ws=True, t=True)
        ws_r = mc.xform(source, q=True, ws=True, ro=True)
        mc.xform(target, ws=True, t=ws_t)
        mc.xform(target, ws=True, ro=ws_r)
        result_t = cast("list[float]", mc.xform(target, q=True, t=True))
        result_r = cast("list[float]", mc.xform(target, q=True, ro=True))
        return list(result_t), list(result_r)

    @staticmethod
    def _zero_offset(ctrl_ofst: str) -> None:
        for attr in (
            "translateX",
            "translateY",
            "translateZ",
            "rotateX",
            "rotateY",
            "rotateZ",
        ):
            plug = f"{ctrl_ofst}.{attr}"
            try:
                mc.setAttr(plug, 0.0)
            except Exception as e:
                mc.warning(f"  Could not zero {plug}: {e}")

    def _set_sdk(
        self,
        driver_attr: str,
        ctrl_ofst: str,
        pose_t: list[float],
        pose_r: list[float],
    ) -> None:
        attrs: tuple[tuple[str, float], ...] = (
            ("translateX", pose_t[0]),
            ("translateY", pose_t[1]),
            ("translateZ", pose_t[2]),
            ("rotateX", pose_r[0]),
            ("rotateY", pose_r[1]),
            ("rotateZ", pose_r[2]),
        )
        for attr, posed_value in attrs:
            mc.setDrivenKeyframe(
                ctrl_ofst,
                attribute=attr,
                currentDriver=driver_attr,
                driverValue=0,
                value=0.0,
            )
            mc.setDrivenKeyframe(
                ctrl_ofst,
                attribute=attr,
                currentDriver=driver_attr,
                driverValue=self.max_driver_value,
                value=posed_value,
            )
