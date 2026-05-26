r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import hand_pose_mirror
importlib.reload(hand_pose_mirror)

hand_pose_mirror.HandPoseMirror(
    source_root="pose_rgt_hand_jnt",
).build()
"""
from __future__ import annotations

import maya.cmds as mc


class HandPoseMirror:
    """Mirror an animated joint hierarchy by baking a per-frame geometric
    mirror onto a freshly created target hierarchy.

    Why a bake and not just `mc.mirrorJoint(mirrorBehavior=True)` + curve
    copy: the user's rigs orient joints with Y down the bone (not Maya's
    default X), and behavior-mirror's axis-flip math doesn't reliably
    produce symmetric motion when curves are copied verbatim onto a
    non-standard orient.  Baking the world transform per frame sidesteps
    every joint-orientation assumption.

    Workflow:
      1. Snapshot every animCurve on translate*/rotate* of the source
         hierarchy.
      2. Disconnect those curves and force source rotates to 0 so the
         source is at its rest pose.  This matters because `mirrorJoint`
         reads each joint's current world transform — a mid-animation
         pose would bake the wrong rest into the mirrored jointOrients.
      3. `mc.mirrorJoint(mirrorYZ=True, mirrorBehavior=False)` creates
         the target hierarchy with orientation-mirrored jointOrients (a
         "real-mirror" rest pose).  Behavior-mirror is not used because
         no curves are copied — every frame is baked instead.
      4. Reconnect the source's curves so it animates again.
      5. Walk every integer frame between the source's earliest and
         latest keyframes.  At each frame, for each (source, target)
         joint pair in parent-to-child order, read the source's world
         matrix, mirror it across YZ, apply to the target via
         `xform -ws -m`, and keyframe the target's translate + rotate.

    Mirroring a world matrix W across the YZ plane is `M * W * M` where
    `M = diag(-1, 1, 1, 1)`.  In component form this negates every entry
    where exactly one of (row==0, col==0) holds — so we don't need any
    matrix library to do it.

    The scene is left clean: curves reconnected, current time restored,
    auto-key state restored.
    """

    ROTATE_ATTRS: tuple[str, ...] = ("rotateX", "rotateY", "rotateZ")
    TRANSLATE_ATTRS: tuple[str, ...] = ("translateX", "translateY", "translateZ")
    ANIM_ATTRS: tuple[str, ...] = TRANSLATE_ATTRS + ROTATE_ATTRS

    def __init__(
        self,
        source_root: str,
        source_token: str = "rgt",
        mirror_token: str = "lft",
        delete_existing_mirror: bool = True,
    ) -> None:
        self.source_root: str = source_root
        self.source_token: str = source_token
        self.mirror_token: str = mirror_token
        self.delete_existing_mirror: bool = delete_existing_mirror

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        if not mc.objExists(self.source_root):
            mc.warning(f"Source root not found: {self.source_root}")
            return

        source_short = self.source_root.split("|")[-1]
        target_root_name = self._mirror_name(source_short)
        if target_root_name == source_short:
            mc.warning(
                f"Source name doesn't contain '_{self.source_token}_': "
                f"{self.source_root}"
            )
            return

        if mc.objExists(target_root_name):
            if not self.delete_existing_mirror:
                mc.warning(
                    f"Mirror target exists; refusing to overwrite: "
                    f"{target_root_name}"
                )
                return
            print(f"  [-] Deleting existing: {target_root_name}")
            mc.delete(target_root_name)

        source_joints = self._collect_joints(self.source_root)
        src_curves = self._snapshot_anim_curves(source_joints)
        if not src_curves:
            mc.warning(
                "Source hierarchy has no anim curves on translate/rotate; "
                "nothing to mirror."
            )
            return

        anim_range = self._anim_range(src_curves)
        if anim_range is None:
            mc.warning("Could not determine animation range; nothing to bake.")
            return
        start_frame, end_frame = anim_range
        print(f"  [ ] Source key range: frames {start_frame} -> {end_frame}")

        initial_time = mc.currentTime(query=True)
        auto_key_state = mc.autoKeyframe(query=True, state=True)
        mc.autoKeyframe(state=False)

        self._disconnect_curves(src_curves)
        saved_rotates = self._zero_source_rotates(source_joints)

        try:
            target_root = self._create_target_hierarchy()
        finally:
            self._reconnect_curves(src_curves)
            self._restore_rotates(saved_rotates, src_curves)

        try:
            target_joints = self._collect_joints(target_root)
            if len(source_joints) != len(target_joints):
                mc.warning(
                    f"Joint count mismatch: {len(source_joints)} src vs "
                    f"{len(target_joints)} tgt — pairing may be off."
                )
            pairs = list(zip(source_joints, target_joints))
            self._bake_animation(pairs, start_frame, end_frame)
        finally:
            mc.autoKeyframe(state=auto_key_state)
            mc.currentTime(initial_time, edit=True)

        print(
            f"\n[DONE] {self.source_root} -> {target_root}; "
            f"baked frames {start_frame}-{end_frame}."
        )

    # ------------------------------------------------------------------
    # Target hierarchy
    # ------------------------------------------------------------------

    def _create_target_hierarchy(self) -> str:
        result = mc.mirrorJoint(
            self.source_root,
            mirrorYZ=True,
            mirrorBehavior=False,
            searchReplace=(
                f"_{self.source_token}_",
                f"_{self.mirror_token}_",
            ),
        )
        source_short = self.source_root.split("|")[-1]
        target_root = self._mirror_name(source_short)
        print(
            f"  [+] Created mirrored hierarchy: {target_root} "
            f"({len(result or [])} node(s))"
        )
        return target_root

    # ------------------------------------------------------------------
    # Bake
    # ------------------------------------------------------------------

    def _bake_animation(
        self,
        pairs: list[tuple[str, str]],
        start_frame: int,
        end_frame: int,
    ) -> None:
        for frame in range(int(start_frame), int(end_frame) + 1):
            mc.currentTime(frame, edit=True)
            for src, tgt in pairs:
                if not (mc.objExists(src) and mc.objExists(tgt)):
                    continue
                src_m = mc.xform(
                    src, query=True, worldSpace=True, matrix=True
                )
                tgt_m = self._mirror_world_matrix_yz(src_m)
                mc.xform(tgt, worldSpace=True, matrix=tgt_m)
                mc.setKeyframe(tgt, attribute="translate")
                mc.setKeyframe(tgt, attribute="rotate")
            print(f"    [frame {frame}] baked {len(pairs)} joint pair(s)")

    @staticmethod
    def _mirror_world_matrix_yz(m: list[float]) -> list[float]:
        """Mirror a 4x4 world matrix across the YZ plane.

        `M * W * M` with `M = diag(-1, 1, 1, 1)` reduces to: negate every
        entry where exactly one of (row==0, col==0) holds.
        """
        result = list(m)
        for r in range(4):
            for c in range(4):
                if (r == 0) != (c == 0):
                    result[r * 4 + c] = -result[r * 4 + c]
        return result

    # ------------------------------------------------------------------
    # Curve snapshot / disconnect / reconnect
    # ------------------------------------------------------------------

    def _snapshot_anim_curves(
        self, joints: list[str]
    ) -> dict[tuple[str, str], str]:
        snapshot: dict[tuple[str, str], str] = {}
        for joint in joints:
            for attr in self.ANIM_ATTRS:
                plug = f"{joint}.{attr}"
                curves = (
                    mc.listConnections(
                        plug,
                        source=True,
                        destination=False,
                        type="animCurve",
                    )
                    or []
                )
                if curves:
                    snapshot[(joint, attr)] = curves[0]
        return snapshot

    def _disconnect_curves(
        self, src_curves: dict[tuple[str, str], str]
    ) -> None:
        for (joint, attr), curve in src_curves.items():
            plug = f"{joint}.{attr}"
            output = f"{curve}.output"
            if mc.isConnected(output, plug):
                try:
                    mc.disconnectAttr(output, plug)
                except Exception as e:
                    mc.warning(f"  Could not disconnect {output} -> {plug}: {e}")

    def _reconnect_curves(
        self, src_curves: dict[tuple[str, str], str]
    ) -> None:
        for (joint, attr), curve in src_curves.items():
            plug = f"{joint}.{attr}"
            output = f"{curve}.output"
            if not mc.isConnected(output, plug):
                try:
                    mc.connectAttr(output, plug, force=True)
                except Exception as e:
                    mc.warning(f"  Could not reconnect {output} -> {plug}: {e}")

    def _zero_source_rotates(
        self, joints: list[str]
    ) -> dict[tuple[str, str], float]:
        saved: dict[tuple[str, str], float] = {}
        for joint in joints:
            for attr in self.ROTATE_ATTRS:
                plug = f"{joint}.{attr}"
                try:
                    saved[(joint, attr)] = mc.getAttr(plug)
                    mc.setAttr(plug, 0)
                except Exception as e:
                    mc.warning(f"  Could not zero {plug}: {e}")
        return saved

    @staticmethod
    def _restore_rotates(
        saved_rotates: dict[tuple[str, str], float],
        src_curves: dict[tuple[str, str], str],
    ) -> None:
        for (joint, attr), value in saved_rotates.items():
            # Curve-driven attrs are restored by reconnect; leave them alone.
            if (joint, attr) in src_curves:
                continue
            try:
                mc.setAttr(f"{joint}.{attr}", value)
            except Exception as e:
                mc.warning(f"  Could not restore {joint}.{attr}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mirror_name(self, src_name: str) -> str:
        return src_name.replace(
            f"_{self.source_token}_", f"_{self.mirror_token}_"
        )

    @staticmethod
    def _collect_joints(root: str) -> list[str]:
        """Return root + descendant joints in parent-to-child DFS order."""
        out: list[str] = []

        def walk(node: str) -> None:
            out.append(node)
            for child in (
                mc.listRelatives(node, children=True, type="joint") or []
            ):
                walk(child)

        walk(root)
        return out

    @staticmethod
    def _anim_range(
        src_curves: dict[tuple[str, str], str],
    ) -> tuple[int, int] | None:
        min_time: float | None = None
        max_time: float | None = None
        for curve in src_curves.values():
            times = mc.keyframe(curve, query=True, timeChange=True) or []
            if not times:
                continue
            cmin = min(times)
            cmax = max(times)
            if min_time is None or cmin < min_time:
                min_time = cmin
            if max_time is None or cmax > max_time:
                max_time = cmax
        if min_time is None or max_time is None:
            return None
        return int(round(min_time)), int(round(max_time))
