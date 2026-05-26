r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import compare_meshes
importlib.reload(compare_meshes)

compare_meshes.compare("meshA", "meshB")
"""

from __future__ import annotations

from typing import cast

import maya.api.OpenMaya as om


def compare(mesh_a: str, mesh_b: str, tolerance: float = 1e-6) -> None:
    """Print per-vertex distance stats between two meshes (object space)."""
    pts_a = _points(mesh_a)
    pts_b = _points(mesh_b)
    if len(pts_a) != len(pts_b):
        print(f"[MISMATCH] vert counts: {mesh_a}={len(pts_a)}, {mesh_b}={len(pts_b)}")
        return

    dists = [(pts_a[i] - pts_b[i]).length() for i in range(len(pts_a))]
    dmin = min(dists)
    dmax = max(dists)
    dmean = sum(dists) / len(dists)
    off = sum(1 for d in dists if d > tolerance)
    print(
        f"[COMPARE] '{mesh_a}' vs '{mesh_b}': "
        f"min={dmin:.10f} max={dmax:.10f} mean={dmean:.10f} "
        f"verts > {tolerance}: {off}/{len(dists)}"
    )


def _points(mesh: str) -> om.MPointArray:
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = cast("om.MDagPath", sel.getDagPath(0))
    if dag.apiType() == om.MFn.kTransform:
        dag.extendToShape()
    return cast("om.MPointArray", om.MFnMesh(dag).getPoints(om.MSpace.kObject))
