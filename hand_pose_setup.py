from __future__ import annotations

from typing import cast

import maya.cmds as mc


class HandPoseBuilder:
    """Build pose-driven finger SDKs split into per-level sub-poses.

    For each pose discovered under `pose_root`, this creates one float attribute
    per joint level on the hand ctrl (e.g. poseFist1, poseFist2, poseFist3) so
    each knuckle level can be dialed independently. Level N's SDK is built with
    levels 1..N-1 already posed, so the world-space match for child joints is
    correct. After all levels are keyed, drivers reset to 0.

    `finger_parts` controls which joints receive SDK keys. Three forms:

      - None: every finger, every level, for every discovered pose.

      - flat tuple/list of finger names (e.g. ("index", "middle")): only
        those fingers get SDK; other finger chains are still match-posed for
        hierarchy correctness then zeroed in cleanup.

      - dict {pose_name: [entries]}: builds *only* the listed poses. Each
        entry is "finger" (all levels) or "finger_N" (specific level only).
        Example:
            {"fist": ["thumb", "index_2", "middle_2"]}
        Joints matched but not selected (e.g. middle_1 in the example above)
        are still posed during the build so child joints land correctly in
        world space, then zeroed back to identity in the cleanup pass.
    """

    FINGER_PARTS: tuple[str, ...] = ("thumb", "index", "middle", "ring", "pinky")
    SEPARATOR_ATTR: str = "__pose__"
    DEFAULT_DRIVER_MAX: int = 10

    def __init__(
        self,
        pose_root: str = "hand_pose_grp",
        sides: tuple[str, ...] = ("lft", "rgt"),
        finger_parts: (
            dict[str, list[str] | tuple[str, ...]]
            | list[str]
            | tuple[str, ...]
            | None
        ) = None,
        max_driver_value: float = DEFAULT_DRIVER_MAX,
    ) -> None:
        self.pose_root: str = pose_root
        self.sides: tuple[str, ...] = tuple(sides)
        self.max_driver_value: float = max_driver_value
        (
            self._pose_filter,
            self._joint_filter,
            self._global_joint_filter,
        ) = self._normalize_finger_parts(finger_parts)
        self._separator_added: set[str] = set()

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
        if self._pose_filter is not None and pose not in self._pose_filter:
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

        print(f"\n[POSE] '{pose}' [{side}] -> {hand_ctrl}")

        if hand_ctrl not in self._separator_added:
            self._add_separator(hand_ctrl)
            self._separator_added.add(hand_ctrl)

        levels = self._group_by_level(joints)
        built_drivers: list[str] = []
        match_only_ofsts: set[str] = set()

        for level in sorted(levels.keys()):
            attr_name = self._sub_pose_attr_name(pose, level)
            driver_attr = f"{hand_ctrl}.{attr_name}"
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
                        self._add_sub_pose_attr(hand_ctrl, attr_name)
                        level_has_sdk = True
                    self._set_sdk(driver_attr, ctrl_ofst, pose_t, pose_r)
                    print(
                        f"    [SDK] L{level} {driver_attr} -> {ctrl_ofst}  "
                        f"t={[round(v, 3) for v in pose_t]}  "
                        f"r={[round(v, 3) for v in pose_r]}"
                    )
                else:
                    match_only_ofsts.add(ctrl_ofst)
                    print(f"    [match-only] L{level} {ctrl_ofst}")

            if level_has_sdk:
                mc.setAttr(driver_attr, self.max_driver_value)
                built_drivers.append(driver_attr)

        # Cleanup: drivers back to 0 (SDK pulls keyed ofsts to identity),
        # then explicitly zero match-only ofsts (no SDK to reset them).
        for driver_attr in built_drivers:
            mc.setAttr(driver_attr, 0)

        for ctrl_ofst in match_only_ofsts:
            self._zero_offset(ctrl_ofst)

    # ------------------------------------------------------------------
    # Filter normalization
    # ------------------------------------------------------------------

    def _normalize_finger_parts(
        self,
        fp: (
            dict[str, list[str] | tuple[str, ...]]
            | list[str]
            | tuple[str, ...]
            | None
        ),
    ) -> tuple[
        set[str] | None,
        dict[str, frozenset[tuple[str, int | None]]],
        frozenset[tuple[str, int | None]] | None,
    ]:
        """Return (pose_filter, joint_filter, global_joint_filter).

        pose_filter: set[str] or None.  None = build all discovered poses.
        joint_filter: dict[pose, frozenset[(finger, level_or_None)]].
                      Explicit per-pose subset.
        global_joint_filter: frozenset[(finger, level_or_None)] or None.
                             Used for any pose not in joint_filter.  None =
                             no filter (all fingers, all levels).
        """
        if fp is None:
            return None, {}, None
        if isinstance(fp, dict):
            pose_filter: set[str] = set(fp.keys())
            joint_filter: dict[str, frozenset[tuple[str, int | None]]] = {
                p: self._parse_entries(v) for p, v in fp.items()
            }
            # Empty global filter: any pose not in the dict matches nothing.
            # In practice pose_filter excludes those poses entirely.
            return pose_filter, joint_filter, frozenset()
        return None, {}, self._parse_entries(fp)

    @staticmethod
    def _parse_entries(
        entries: list[str] | tuple[str, ...],
    ) -> frozenset[tuple[str, int | None]]:
        out: set[tuple[str, int | None]] = set()
        for e in entries:
            s = str(e)
            head, _, tail = s.rpartition("_")
            if head and tail.isdigit():
                out.add((head, int(tail)))
            else:
                out.add((s, None))
        return frozenset(out)

    def _filter_for_pose(
        self, pose: str
    ) -> frozenset[tuple[str, int | None]] | None:
        if pose in self._joint_filter:
            return self._joint_filter[pose]
        return self._global_joint_filter

    def _is_selected(self, pose: str, finger: str, level: int) -> bool:
        flt = self._filter_for_pose(pose)
        if flt is None:
            return True
        return (finger, None) in flt or (finger, level) in flt

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

    def _add_separator(self, ctrl: str) -> None:
        if not mc.attributeQuery(self.SEPARATOR_ATTR, node=ctrl, exists=True):
            mc.addAttr(
                ctrl, longName=self.SEPARATOR_ATTR, attributeType="long",
                defaultValue=0, keyable=True,
            )
            mc.setAttr(f"{ctrl}.{self.SEPARATOR_ATTR}", lock=True)
            print(f"  [+] Added separator: {ctrl}.{self.SEPARATOR_ATTR}")
        else:
            print(f"  [~] Separator exists: {ctrl}.{self.SEPARATOR_ATTR}")

    def _add_sub_pose_attr(self, ctrl: str, attr_name: str) -> None:
        if not mc.attributeQuery(attr_name, node=ctrl, exists=True):
            mc.addAttr(
                ctrl, longName=attr_name, attributeType="float",
                minValue=0, maxValue=self.max_driver_value, defaultValue=0,
                keyable=True,
            )
            print(f"  [+] Added attr: {ctrl}.{attr_name}")
        else:
            print(f"  [~] Attr exists: {ctrl}.{attr_name}")

    @staticmethod
    def _sub_pose_attr_name(pose: str, level: int) -> str:
        # Uppercase only the first letter; preserve any camelCase in the token.
        return f"pose{pose[:1].upper()}{pose[1:]}{level}"

    # ------------------------------------------------------------------
    # Transform + SDK
    # ------------------------------------------------------------------

    @staticmethod
    def _match_transform(
        source: str, target: str
    ) -> tuple[list[float], list[float]]:
        ws_t = mc.xform(source, q=True, ws=True, t=True)
        ws_r = mc.xform(source, q=True, ws=True, ro=True)
        mc.xform(target, ws=True, t=ws_t)
        mc.xform(target, ws=True, ro=ws_r)
        result_t = cast("list[float]", mc.xform(target, q=True, t=True))
        result_r = cast("list[float]", mc.xform(target, q=True, ro=True))
        return list(result_t), list(result_r)

    @staticmethod
    def _zero_offset(ctrl_ofst: str) -> None:
        for attr in ("translateX", "translateY", "translateZ",
                     "rotateX", "rotateY", "rotateZ"):
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
            ("rotateX",    pose_r[0]),
            ("rotateY",    pose_r[1]),
            ("rotateZ",    pose_r[2]),
        )
        for attr, posed_value in attrs:
            mc.setDrivenKeyframe(
                ctrl_ofst, attribute=attr,
                currentDriver=driver_attr,
                driverValue=0, value=0.0,
            )
            mc.setDrivenKeyframe(
                ctrl_ofst, attribute=attr,
                currentDriver=driver_attr,
                driverValue=self.max_driver_value, value=posed_value,
            )


if __name__ == "__main__":
    HandPoseBuilder().build()

HandPoseBuilder().build()
