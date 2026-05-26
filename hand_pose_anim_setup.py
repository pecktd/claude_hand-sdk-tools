r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import hand_pose_anim_setup
importlib.reload(hand_pose_anim_setup)

hand_pose_anim_setup.HandPoseAnimBuilder(
    pose_ranges={
        "open2Pinky": (1010, 1030),
        "open2Fist": (1050, 1070),
        "open2Scissor": (1090, 1110),
        "open2Pistol": (1130, 1150),
        "fist2Scissor": (1180, 1200),
    },
).build()
"""

from __future__ import annotations

from typing import cast

import maya.cmds as mc


class HandPoseAnimBuilder:
    """Build pose-driven finger SDKs from an animated guide hierarchy.

    Differences from `hand_pose_setup.HandPoseBuilder`:
      - Pose source is a single animated joint hierarchy whose joints are
        prefixed `pose_` (e.g. `pose_lft_thumb_1_jnt`).  Different poses
        share the same joints and are distinguished by frame range.
      - Each pose attribute is built from a `(start_frame, end_frame)` tuple.
        The driver value at each integer frame is mapped linearly so that
        `start_frame -> 0` and `end_frame -> max_driver_value`.
      - SDK curves carry inbetweens — one key per integer frame in the
        range — instead of just the two endpoints.
      - No per-finger filtering: every `(part, level)` for which both a
        source joint and a ctrl_ofst exist is keyed.

    For every frame in a pose's range, joints are processed parent-to-child
    so that each child ctrl_ofst's local values are computed against its
    parent's already-posed world transform.  Once a pose's range is done,
    its ctrl_ofsts are reset to identity before moving to the next pose.

    During the build, auto-key is disabled and currentTime is restored on
    exit so the scene is left as it was found.
    """

    FINGER_PARTS: tuple[str, ...] = ("thumb", "index", "middle", "ring", "pinky")
    DEFAULT_DRIVER_MAX: float = 10.0
    POSE_JOINT_PREFIX: str = "pose_"
    SEPARATOR_ATTR: str = "__handPoseAnim__"

    def __init__(
        self,
        pose_ranges: dict[str, tuple[int, int]],
        sides: tuple[str, ...] = ("lft", "rgt"),
        max_driver_value: float = DEFAULT_DRIVER_MAX,
    ) -> None:
        self.pose_ranges: dict[str, tuple[int, int]] = dict(pose_ranges)
        self.sides: tuple[str, ...] = tuple(sides)
        self.max_driver_value: float = float(max_driver_value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        initial_time = mc.currentTime(query=True)
        auto_key_state = mc.autoKeyframe(query=True, state=True)
        mc.autoKeyframe(state=False)
        try:
            for side in self.sides:
                hand_ctrl = f"{side}_hand_ctrl"
                if mc.objExists(hand_ctrl):
                    self._add_separator(hand_ctrl, self.SEPARATOR_ATTR)

            for pose, frame_range in self.pose_ranges.items():
                start_frame, end_frame = int(frame_range[0]), int(frame_range[1])
                if start_frame >= end_frame:
                    mc.warning(
                        f"Skipping pose '{pose}': start ({start_frame}) " f">= end ({end_frame})."
                    )
                    continue
                for side in self.sides:
                    self.build_pose(pose, side, start_frame, end_frame)
        finally:
            mc.autoKeyframe(state=auto_key_state)
            mc.currentTime(initial_time, edit=True)

        print("\n[DONE] Pose-driven finger setup complete.")

    def build_pose(
        self,
        pose: str,
        side: str,
        start_frame: int,
        end_frame: int,
    ) -> None:
        hand_ctrl = f"{side}_hand_ctrl"
        if not mc.objExists(hand_ctrl):
            mc.warning(f"Missing: {hand_ctrl}")
            return

        pairs_by_level = self._discover_pairs(side)
        if not pairs_by_level:
            mc.warning(f"No pose joints found for side '{side}'.")
            return

        attr_name = self._pose_attr_name(pose)
        driver_plug = f"{hand_ctrl}.{attr_name}"

        self._add_pose_float_attr(hand_ctrl, attr_name)
        self._ensure_norm_mult(f"{side}_{attr_name}_outMult", driver_plug)

        print(
            f"\n[POSE] '{pose}' [{side}] frames {start_frame}->{end_frame} "
            f"-> {driver_plug}"
        )

        span = float(end_frame - start_frame)

        # Outer loop is level (parent-to-child).  We can't match a child
        # ofst correctly until its parent ofst is already SDK-driven and
        # evaluates to the posed value at the current driver — otherwise
        # the parent sits at rest while we match the child against frame-F
        # joints in world space, and child local t/r come out wrong.
        #
        # Per level we do two passes:
        #   1) sample — at every frame, set the driver to the proportional
        #      value so parent levels' (already-keyed) SDKs evaluate to
        #      their frame-F pose, then mc.xform-match each joint at this
        #      level (its ofst isn't driven yet, so xform writes through)
        #      and record (driver_value, ofst, local_t, local_r).
        #   2) write — turn the recorded samples into setDrivenKeyframe
        #      calls.  After this, the level's ofsts are SDK-driven; the
        #      next level's sample pass will see correctly posed parents.
        for level in sorted(pairs_by_level.keys()):
            samples = self._sample_level(
                driver_plug, pairs_by_level[level], start_frame, end_frame, span
            )
            self._write_sdk_keys(driver_plug, samples)
            print(
                f"  [SDK] level {level}: wrote {len(samples)} key(s) across "
                f"{len(pairs_by_level[level])} joint(s)"
            )

        # All levels are SDK-driven now.  Pulling driver back to 0 evaluates
        # every SDK at its start-frame key (the open/rest pose).
        mc.setAttr(driver_plug, 0)

    def _sample_level(
        self,
        driver_plug: str,
        pairs: list[tuple[str, str]],
        start_frame: int,
        end_frame: int,
        span: float,
    ) -> list[tuple[float, str, list[float], list[float]]]:
        samples: list[tuple[float, str, list[float], list[float]]] = []
        for frame in range(int(start_frame), int(end_frame) + 1):
            mc.currentTime(frame, edit=True)
            driver_value = (frame - start_frame) / span * self.max_driver_value
            mc.setAttr(driver_plug, driver_value)
            for src_jnt, ctrl_ofst in pairs:
                pose_t, pose_r = self._match_transform(src_jnt, ctrl_ofst)
                samples.append((driver_value, ctrl_ofst, pose_t, pose_r))
        return samples

    def _write_sdk_keys(
        self,
        driver_plug: str,
        samples: list[tuple[float, str, list[float], list[float]]],
    ) -> None:
        for driver_value, ctrl_ofst, pose_t, pose_r in samples:
            self._set_sdk_key(driver_plug, ctrl_ofst, driver_value, pose_t, pose_r)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_pairs(self, side: str) -> dict[int, list[tuple[str, str]]]:
        """Return `{level: [(source_joint, ctrl_ofst), ...]}` for one side.

        Source joints follow `pose_{side}_{part}_{level}_jnt`; matched ctrl
        offsets follow `{side}_{part}_{level}_ctrl_ofst`.  A pair is only
        included when both nodes exist.  Levels are discovered by scanning
        outward until no finger has a joint at that level.
        """
        pairs: dict[int, list[tuple[str, str]]] = {}
        level = 1
        while True:
            found_any_source = False
            for part in self.FINGER_PARTS:
                src = f"{self.POSE_JOINT_PREFIX}{side}_{part}_{level}_jnt"
                if not mc.objExists(src):
                    continue
                found_any_source = True
                ctrl_ofst = f"{side}_{part}_{level}_ctrl_ofst"
                if not mc.objExists(ctrl_ofst):
                    mc.warning(f"  Missing ctrl_ofst for {src}: {ctrl_ofst}")
                    continue
                pairs.setdefault(level, []).append((src, ctrl_ofst))
            if not found_any_source:
                break
            level += 1
        return pairs

    # ------------------------------------------------------------------
    # Attribute helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pose_attr_name(pose: str) -> str:
        return f"pose{pose[:1].upper()}{pose[1:]}"

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

    def _add_pose_float_attr(self, ctrl: str, attr_name: str) -> None:
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
            print(f"  [+] Added attr: {ctrl}.{attr_name}")
        else:
            print(f"  [~] Attr exists: {ctrl}.{attr_name}")

    def _ensure_norm_mult(self, mult_node: str, source_plug: str) -> None:
        """Create a `multDoubleLinear` that scales `source_plug` by
        `1 / max_driver_value`, producing a 0..1 normalized signal.

        Any prior incoming connection on `.input1` that doesn't match
        `source_plug` is broken first so reruns rewire correctly.
        """
        if not mc.objExists(mult_node):
            mc.createNode("multDoubleLinear", name=mult_node)
            print(f"  [+] Created norm-mult: {mult_node}")
        mc.setAttr(f"{mult_node}.input2", 1.0 / self.max_driver_value)

        input1_plug = f"{mult_node}.input1"
        existing = mc.listConnections(input1_plug, source=True, destination=False, plugs=True) or []
        for src in existing:
            if src != source_plug:
                mc.disconnectAttr(src, input1_plug)
                print(f"  [-] Disconnected stale source: {src} -X-> {input1_plug}")
        if not mc.isConnected(source_plug, input1_plug):
            mc.connectAttr(source_plug, input1_plug, force=True)
            print(f"  [+] Connected: {source_plug} -> {input1_plug}")

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

    @staticmethod
    def _set_sdk_key(
        driver_attr: str,
        ctrl_ofst: str,
        driver_value: float,
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
        for attr, value in attrs:
            mc.setDrivenKeyframe(
                ctrl_ofst,
                attribute=attr,
                currentDriver=driver_attr,
                driverValue=driver_value,
                value=value,
            )
