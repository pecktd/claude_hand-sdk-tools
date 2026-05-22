r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import zone_corrective
importlib.reload(zone_corrective)

zone_corrective.ZoneCorrectiveBuilder(
    pose="fist",
    weighted_geo="blendWeights_2_ma:L_arm_001_GEO_blendWeights",
    influence_joint="blendWeights_2_ma:lft_zone_1_guide",
    orig_shape="L_arm_001_GEO_orig",
    target_shape="L_arm_001_GEO_testFist_target",
).build()
"""

from __future__ import annotations

from typing import cast

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as mc


class ZoneCorrectiveBuilder:
    """Bake a target-shape delta into a new mesh, masked by a joint's skin weight.

    The skinCluster on `weighted_geo` is treated as a painted mask: each vertex's
    weight for `influence_joint` (0..1) scales that vertex's (target - orig)
    delta when applied to a duplicate of `orig_shape`:

        new_pos[v] = orig_pos[v] + (target_pos[v] - orig_pos[v]) * weight[v]

    All three meshes (weighted_geo, orig_shape, target_shape) must share
    topology — vertex counts must match.

    Example:
        ZoneCorrectiveBuilder(
            pose="fist",
            weighted_geo="blendWeights_2_ma:L_arm_001_GEO_blendWeights",
            influence_joint="blendWeights_2_ma:lft_zone_1_guide",
            orig_shape="L_arm_001_GEO_orig",
            target_shape="L_arm_001_GEO_testFist_target",
        ).build()
    """

    SPACE: int = om.MSpace.kObject
    TARGETS_GROUP: str = "targets_group"

    def __init__(
        self,
        pose: str,
        weighted_geo: str,
        influence_joint: str,
        orig_shape: str,
        target_shape: str,
        name: str | None = None,
    ) -> None:
        self.pose: str = pose
        self.weighted_geo: str = weighted_geo
        self.influence_joint: str = influence_joint
        self.orig_shape: str = orig_shape
        self.target_shape: str = target_shape
        self.name: str | None = name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> str:
        """Build the zone corrective mesh and return its transform name."""
        self._validate_nodes()

        orig_pts = self._mesh_points(self.orig_shape)
        target_pts = self._mesh_points(self.target_shape)
        self._require_same_count("orig", len(orig_pts), "target", len(target_pts))

        skin_cluster = self._find_skin_cluster(self.weighted_geo)
        weights = self._influence_weights(skin_cluster, self.weighted_geo, self.influence_joint)
        self._require_same_count("weighted_geo", len(weights), "orig", len(orig_pts))

        out_name = self.name or self._default_name(self.pose, self.influence_joint)
        new_mesh = cast("list[str]", mc.duplicate(self.orig_shape, name=out_name))[0]
        print(f"  [+] Duplicated '{self.orig_shape}' -> '{new_mesh}'")

        self._apply_weighted_deltas(new_mesh, orig_pts, target_pts, weights)
        new_mesh = self._parent_to_targets_group(new_mesh)
        print(
            f"[ZONE] '{new_mesh}' "
            f"<- target='{self.target_shape}' "
            f"masked by '{self.influence_joint}' on '{self.weighted_geo}'"
        )
        return new_mesh

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_nodes(self) -> None:
        for node in (
            self.weighted_geo,
            self.influence_joint,
            self.orig_shape,
            self.target_shape,
        ):
            if not mc.objExists(node):
                raise RuntimeError(f"Node not found: {node}")

    @staticmethod
    def _require_same_count(a_name: str, a_count: int, b_name: str, b_count: int) -> None:
        if a_count != b_count:
            raise RuntimeError(f"Vertex count mismatch: {a_name}={a_count}, {b_name}={b_count}.")

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------

    @staticmethod
    def _short_name(node: str) -> str:
        return node.split("|")[-1].split(":")[-1]

    @classmethod
    def _default_name(cls, pose: str, influence_joint: str) -> str:
        base = cls._short_name(influence_joint)
        if base.endswith("_guide"):
            base = base[: -len("_guide")]
        side, _, rest = base.partition("_")
        if rest:
            return f"{side}_{pose}_{rest}_shape"
        return f"{pose}_{base}_shape"

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    @classmethod
    def _parent_to_targets_group(cls, mesh: str) -> str:
        if not mc.objExists(cls.TARGETS_GROUP):
            mc.group(empty=True, name=cls.TARGETS_GROUP)
        parented = cast("list[str]", mc.parent(mesh, cls.TARGETS_GROUP))
        return parented[0]

    # ------------------------------------------------------------------
    # Mesh access
    # ------------------------------------------------------------------

    @staticmethod
    def _shape_dag(name: str) -> om.MDagPath:
        sel = om.MSelectionList()
        sel.add(name)
        dag = cast("om.MDagPath", sel.getDagPath(0))
        if dag.apiType() == om.MFn.kTransform:
            dag.extendToShape()
        return dag

    def _mesh_points(self, mesh: str) -> om.MPointArray:
        return cast(
            "om.MPointArray",
            om.MFnMesh(self._shape_dag(mesh)).getPoints(self.SPACE),
        )

    # ------------------------------------------------------------------
    # Skin weights
    # ------------------------------------------------------------------

    @staticmethod
    def _find_skin_cluster(geo: str) -> str:
        history = mc.listHistory(geo, pruneDagObjects=True) or []
        clusters = mc.ls(history, type="skinCluster") or []
        if not clusters:
            raise RuntimeError(f"No skinCluster found on '{geo}'.")
        return clusters[0]

    def _influence_weights(self, skin_cluster: str, geo: str, joint: str) -> list[float]:
        sc_sel = om.MSelectionList()
        sc_sel.add(skin_cluster)
        sc_fn = oma.MFnSkinCluster(sc_sel.getDependNode(0))

        influences = cast("list[om.MDagPath]", sc_fn.influenceObjects())
        index = self._find_influence_index(influences, joint)
        if index < 0:
            names = [influences[i].partialPathName() for i in range(len(influences))]
            raise RuntimeError(
                f"'{joint}' is not an influence of '{skin_cluster}'. " f"Influences: {names}"
            )

        geo_dag = self._shape_dag(geo)
        vert_count = cast("int", om.MFnMesh(geo_dag).numVertices)
        comp_fn = om.MFnSingleIndexedComponent()
        comp = comp_fn.create(om.MFn.kMeshVertComponent)
        comp_fn.setCompleteData(vert_count)

        all_weights, num_infl = cast("tuple[list[float], int]", sc_fn.getWeights(geo_dag, comp))
        return [all_weights[v * num_infl + index] for v in range(vert_count)]

    @staticmethod
    def _find_influence_index(influences: list[om.MDagPath], joint: str) -> int:
        sel = om.MSelectionList()
        sel.add(joint)
        target_full = cast("om.MDagPath", sel.getDagPath(0)).fullPathName()
        for i in range(len(influences)):
            if influences[i].fullPathName() == target_full:
                return i
        return -1

    # ------------------------------------------------------------------
    # Apply deltas
    # ------------------------------------------------------------------

    def _apply_weighted_deltas(
        self,
        mesh: str,
        orig_pts: om.MPointArray,
        target_pts: om.MPointArray,
        weights: list[float],
    ) -> None:
        fn = om.MFnMesh(self._shape_dag(mesh))
        new_pts = om.MPointArray()
        for i in range(len(orig_pts)):
            w = weights[i]
            op = orig_pts[i]
            tp = target_pts[i]
            new_pts.append(
                om.MPoint(
                    op.x + (tp.x - op.x) * w,
                    op.y + (tp.y - op.y) * w,
                    op.z + (tp.z - op.z) * w,
                )
            )
        fn.setPoints(new_pts, self.SPACE)
        fn.updateSurface()


if __name__ == "__main__":
    ZoneCorrectiveBuilder(
        pose="fist",
        weighted_geo="blendWeights_2_ma:L_arm_001_GEO_blendWeights",
        influence_joint="blendWeights_2_ma:lft_zone_1_guide",
        orig_shape="L_arm_001_GEO_orig",
        target_shape="L_arm_001_GEO_testFist_target",
    ).build()
