r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import zone_corrective
importlib.reload(zone_corrective)

zone_corrective.ZoneCorrectiveBuilder(
    pose="fist",
    skin_cluster="blendWeights_2_ma:L_arm_001_GEO_zoneWeight_skinCluster",
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
    """Bake target-shape deltas into per-influence meshes, masked by each
    influence's skinCluster weight.

    The skinCluster on the geometry it drives is treated as a partition of
    the target delta: every influence gets one corrective shape where each
    vertex's (target - orig) delta is scaled by that influence's weight at
    that vertex:

        new_pos[v] = orig_pos[v] + (target_pos[v] - orig_pos[v]) * weight[v]

    Influences are processed parent-before-child by DAG depth, so the
    resulting shapes are emitted in hierarchy order.  Every influence must
    carry at least one non-zero painted weight or the build aborts before
    any shape is created.

    All three meshes (the skinCluster's geometry, orig_shape, target_shape)
    must share topology — vertex counts must match.

    Example:
        ZoneCorrectiveBuilder(
            pose="fist",
            skin_cluster="blendWeights_2_ma:L_arm_001_GEO_zoneWeight_skinCluster",
            orig_shape="L_arm_001_GEO_orig",
            target_shape="L_arm_001_GEO_testFist_target",
        ).build()
    """

    SPACE: int = om.MSpace.kObject
    TARGETS_GROUP: str = "targets_group"

    def __init__(
        self,
        pose: str,
        skin_cluster: str,
        orig_shape: str,
        target_shape: str,
    ) -> None:
        self.pose: str = pose
        self.skin_cluster: str = skin_cluster
        self.orig_shape: str = orig_shape
        self.target_shape: str = target_shape

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> list[str]:
        """Build one corrective per influence and return their names in
        parent-before-child hierarchy order.
        """
        self._validate_nodes()

        geo = self._skin_cluster_geo(self.skin_cluster)

        orig_pts = self._mesh_points(self.orig_shape)
        target_pts = self._mesh_points(self.target_shape)
        self._require_same_count("orig", len(orig_pts), "target", len(target_pts))

        sc_sel = om.MSelectionList()
        sc_sel.add(self.skin_cluster)
        sc_fn = oma.MFnSkinCluster(sc_sel.getDependNode(0))
        influences = cast("list[om.MDagPath]", sc_fn.influenceObjects())

        geo_dag = self._shape_dag(geo)
        vert_count = cast("int", om.MFnMesh(geo_dag).numVertices)
        self._require_same_count("geo", vert_count, "orig", len(orig_pts))

        comp_fn = om.MFnSingleIndexedComponent()
        comp = comp_fn.create(om.MFn.kMeshVertComponent)
        comp_fn.setCompleteData(vert_count)
        all_weights, num_infl = cast(
            "tuple[list[float], int]", sc_fn.getWeights(geo_dag, comp)
        )

        self._require_no_zero_influences(influences, all_weights, num_infl, vert_count)

        sorted_idxs = sorted(
            range(num_infl),
            key=lambda i: (
                influences[i].fullPathName().count("|"),
                influences[i].fullPathName(),
            ),
        )

        built: list[str] = []
        for idx in sorted_idxs:
            infl_name = influences[idx].partialPathName()
            weights = [all_weights[v * num_infl + idx] for v in range(vert_count)]

            out_name = self._default_name(self.pose, infl_name)
            new_mesh = cast("list[str]", mc.duplicate(self.orig_shape, name=out_name))[0]
            print(f"  [+] Duplicated '{self.orig_shape}' -> '{new_mesh}'")

            self._apply_weighted_deltas(new_mesh, orig_pts, target_pts, weights)
            new_mesh = self._parent_to_targets_group(new_mesh)
            print(
                f"[ZONE] '{new_mesh}' "
                f"<- target='{self.target_shape}' "
                f"masked by '{infl_name}' on '{geo}'"
            )
            built.append(new_mesh)
        return built

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_nodes(self) -> None:
        for node in (self.skin_cluster, self.orig_shape, self.target_shape):
            if not mc.objExists(node):
                raise RuntimeError(f"Node not found: {node}")

    @staticmethod
    def _require_same_count(a_name: str, a_count: int, b_name: str, b_count: int) -> None:
        if a_count != b_count:
            raise RuntimeError(f"Vertex count mismatch: {a_name}={a_count}, {b_name}={b_count}.")

    @staticmethod
    def _require_no_zero_influences(
        influences: list[om.MDagPath],
        all_weights: list[float],
        num_infl: int,
        vert_count: int,
    ) -> None:
        zero_infls: list[str] = []
        for idx in range(num_infl):
            if not any(all_weights[v * num_infl + idx] > 0.0 for v in range(vert_count)):
                zero_infls.append(influences[idx].partialPathName())
        if zero_infls:
            raise RuntimeError(
                f"Influences with no painted weights: {zero_infls}"
            )

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
    # Skin cluster
    # ------------------------------------------------------------------

    @staticmethod
    def _skin_cluster_geo(skin_cluster: str) -> str:
        geos = cast(
            "list[str] | None",
            mc.skinCluster(skin_cluster, query=True, geometry=True),
        )
        if not geos:
            raise RuntimeError(f"SkinCluster '{skin_cluster}' has no geometry.")
        return geos[0]

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
