r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import copy_proxy_weights
importlib.reload(copy_proxy_weights)

copy_proxy_weights.run()
"""
from __future__ import annotations

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as mc


TARGET = "skin_proxy"
PROXY_GROUP = "zone_geo_grp"


def run(
    target: str = TARGET,
    proxy_group: str = PROXY_GROUP,
) -> None:
    """Bind the `skin_proxy` mesh from proxy-geo coverage.

      1. Discover proxy meshes under `proxy_group` (default `zone_geo_grp`)
         prefixed `lft_` or `rgt_`.  Each proxy `<name>_guideGeo` is driven
         by joint `<name>_guide`.
      2. Bind `target` with every matched joint as an influence.  Any
         pre-existing skinCluster on the target is unbound first to start
         clean.
      3. For each proxy, walk its vertices, find the closest vertex on the
         target in world space, and set that target vert's weight to 1.0 on
         the proxy's matching joint.  The skinCluster normalises all other
         influences to 0 for those verts.
    """
    if not mc.objExists(proxy_group):
        mc.warning(f"Proxy group '{proxy_group}' not found.")
        return
    if not mc.objExists(target):
        mc.warning(f"Target '{target}' missing.")
        return

    proxies = _discover_proxies(proxy_group)
    if not proxies:
        mc.warning(
            f"No 'lft_*' / 'rgt_*' proxy meshes under '{proxy_group}'."
        )
        return

    _build(proxies, target)

    print("\n[DONE] Proxy weights copied.")


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------

def _discover_proxies(proxy_group: str) -> list[str]:
    descendants = (
        mc.listRelatives(
            proxy_group,
            allDescendents=True,
            type="transform",
            fullPath=True,
        )
        or []
    )
    proxies: list[str] = []
    for t in descendants:
        short = t.split("|")[-1]
        if not (short.startswith("lft_") or short.startswith("rgt_")):
            continue
        if not mc.listRelatives(t, shapes=True, type="mesh", noIntermediate=True):
            continue
        proxies.append(t)
    return proxies


# ----------------------------------------------------------------------
# Bind + paint
# ----------------------------------------------------------------------

def _build(proxies: list[str], target: str) -> None:
    proxy_joint: dict[str, str] = {}
    joints: list[str] = []
    for proxy in proxies:
        joint = _joint_name(_short(proxy))
        if not mc.objExists(joint):
            mc.warning(f"Joint '{joint}' missing; skipping proxy '{proxy}'.")
            continue
        proxy_joint[proxy] = joint
        if joint not in joints:
            joints.append(joint)

    if not joints:
        mc.warning("No joints resolved; aborting bind.")
        return

    skin = _bind(target, joints)
    print(f"bound {target} with {len(joints)} influences -> {skin}")

    tgt_dag = _dag(target)
    tgt_fn = om.MFnMesh(tgt_dag)
    tgt_points = tgt_fn.getPoints(om.MSpace.kWorld)

    vert_to_joint: dict[int, str] = {}
    for proxy, joint in proxy_joint.items():
        idxs = _closest_vertex_indices(proxy, tgt_fn, tgt_points)
        if not idxs:
            mc.warning(f"{proxy}: no vertices.")
            continue
        unique = set(idxs)
        for v in unique:
            vert_to_joint[v] = joint
        print(f"  {_short(proxy)}: {len(unique)} vert(s) -> {joint}=1.0")

    if vert_to_joint:
        _apply_weights(skin, target, vert_to_joint)


def _bind(target: str, joints: list[str]) -> str:
    existing = _skin_cluster(target)
    if existing:
        mc.warning(f"Unbinding existing '{existing}' on '{target}'.")
        mc.skinCluster(existing, edit=True, unbind=True)

    mc.select(joints + [target], replace=True)
    skin = mc.skinCluster(
        toSelectedBones=True,
        bindMethod=0,
        skinMethod=0,
        normalizeWeights=1,
        maximumInfluences=1,
        obeyMaxInfluences=True,
        dropoffRate=4.0,
        removeUnusedInfluence=False,
    )[0]
    return skin


def _apply_weights(skin: str, target: str, vert_to_joint: dict[int, str]) -> None:
    """Bulk weight write via OpenMayaAnim — far faster than per-proxy skinPercent."""
    sel = om.MSelectionList()
    sel.add(skin)
    skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))

    shape_dag = _dag(target)
    shape_dag.extendToShape()

    infl_paths = skin_fn.influenceObjects()
    name_to_col: dict[str, int] = {}
    infl_indices = om.MIntArray()
    for col, path in enumerate(infl_paths):
        infl_indices.append(skin_fn.indexForInfluenceObject(path))
        name_to_col[path.partialPathName()] = col
        name_to_col[path.fullPathName()] = col
    n_infl = len(infl_paths)

    verts = sorted(vert_to_joint.keys())
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.addElements(verts)

    flat = [0.0] * (len(verts) * n_infl)
    for row, v in enumerate(verts):
        col = name_to_col[vert_to_joint[v]]
        flat[row * n_infl + col] = 1.0
    weights = om.MDoubleArray(flat)

    skin_fn.setWeights(shape_dag, comp, infl_indices, weights, False)
    print(f"  wrote {len(verts)} vert weight(s) in one call")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _short(name: str) -> str:
    return name.split("|")[-1]


def _joint_name(proxy_short: str) -> str:
    """Proxy `..._guideGeo` is driven by joint `..._guide`."""
    return proxy_short[:-3] if proxy_short.endswith("Geo") else proxy_short


def _skin_cluster(mesh: str) -> str | None:
    history = mc.listHistory(mesh) or []
    skins = mc.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def _closest_vertex_indices(
    source_mesh: str,
    tgt_fn: om.MFnMesh,
    tgt_points: om.MPointArray,
) -> list[int]:
    src_fn = om.MFnMesh(_dag(source_mesh))
    src_points = src_fn.getPoints(om.MSpace.kWorld)
    get_face_verts = tgt_fn.getPolygonVertices
    get_closest = tgt_fn.getClosestPoint
    world = om.MSpace.kWorld
    result: list[int] = []
    for point in src_points:
        _, face_id = get_closest(point, world)
        verts = get_face_verts(face_id)
        best_idx = verts[0]
        dx = tgt_points[best_idx].x - point.x
        dy = tgt_points[best_idx].y - point.y
        dz = tgt_points[best_idx].z - point.z
        best_sq = dx * dx + dy * dy + dz * dz
        for v in verts[1:]:
            dx = tgt_points[v].x - point.x
            dy = tgt_points[v].y - point.y
            dz = tgt_points[v].z - point.z
            d_sq = dx * dx + dy * dy + dz * dz
            if d_sq < best_sq:
                best_sq = d_sq
                best_idx = v
        result.append(best_idx)
    return result


def _dag(name: str) -> om.MDagPath:
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDagPath(0)
