r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import apply_delta
importlib.reload(apply_delta)

apply_delta.run(
    base_a="base_a_geo",
    base_b="base_b_geo",
    target="target_geo",
)
"""
from __future__ import annotations

import maya.api.OpenMaya as om
import maya.cmds as mc


SPACE: int = om.MSpace.kObject


def run(base_a: str, base_b: str, target: str) -> None:
    """Apply the per-vertex delta `(base_b - base_a)` onto `target` in place.

    All three meshes must share topology (matching vertex counts).
    Positions are read and written in object space:

        target_new[v] = target[v] + (base_b[v] - base_a[v])
    """
    for name in (base_a, base_b, target):
        if not mc.objExists(name):
            mc.warning(f"Mesh '{name}' missing.")
            return

    a_pts = _mesh_points(base_a)
    b_pts = _mesh_points(base_b)
    t_pts = _mesh_points(target)

    if not (len(a_pts) == len(b_pts) == len(t_pts)):
        mc.warning(
            "Vertex count mismatch: "
            f"{base_a}={len(a_pts)}, {base_b}={len(b_pts)}, {target}={len(t_pts)}"
        )
        return

    out = om.MPointArray()
    out.setLength(len(t_pts))
    for i in range(len(t_pts)):
        a, b, t = a_pts[i], b_pts[i], t_pts[i]
        out[i] = om.MPoint(
            t.x + (b.x - a.x),
            t.y + (b.y - a.y),
            t.z + (b.z - a.z),
        )

    _set_mesh_points(target, out)
    print(f"[DONE] Applied delta ({base_b} - {base_a}) to {target} on {len(t_pts)} vert(s).")


def _mesh_points(name: str) -> om.MPointArray:
    dag = _dag(name)
    dag.extendToShape()
    return om.MFnMesh(dag).getPoints(SPACE)


def _set_mesh_points(name: str, points: om.MPointArray) -> None:
    dag = _dag(name)
    dag.extendToShape()
    om.MFnMesh(dag).setPoints(points, SPACE)


def _dag(name: str) -> om.MDagPath:
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDagPath(0)
