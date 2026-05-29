r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import transfer_arm_weights
importlib.reload(transfer_arm_weights)

transfer_arm_weights.run()
"""
from __future__ import annotations

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as mc


def _arm_mapping(side: str) -> list[tuple[str, str]]:
    """Pair the 5 up-arm + 5 forearm rib joints onto arm_1..arm_10 in order."""
    sources = [f"{side}_ik_up_arm_rib_{i}_jnt" for i in range(1, 6)]
    sources += [f"{side}_ik_forearm_rib_{i}_jnt" for i in range(1, 6)]
    targets = [f"{side}_arm_{i}_jnt" for i in range(1, 11)]
    return list(zip(sources, targets))


JOBS: list[tuple[str, list[tuple[str, str]]]] = [
    ("L_arm_001_GEO_skinCluster", _arm_mapping("lft")),
    ("R_arm_001_GEO_skinCluster", _arm_mapping("rgt")),
]


def run(
    jobs: list[tuple[str, list[tuple[str, str]]]] = JOBS,
    remove_sources: bool = True,
) -> None:
    """Move skin weights from source joints onto paired target joints.

    For each (skinCluster, mapping) job:
      1. Validate every source and target joint exists; raise if any is missing.
      2. Any target joint not already an influence is bound (added with weight 0).
      3. Per vertex, each source joint's weight is added to its paired target
         and the source weight zeroed.  Per-vertex totals are preserved, so no
         renormalisation is needed.
      4. With `remove_sources` (default True), the now-empty source influences
         are removed from the skinCluster — i.e. a true "move".
    """
    for skin, mapping in jobs:
        _transfer(skin, mapping, remove_sources)

    print("\n[DONE] Arm skin weights transferred.")


# ----------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------

def _transfer(
    skin: str,
    mapping: list[tuple[str, str]],
    remove_sources: bool,
) -> None:
    if not mc.objExists(skin):
        raise RuntimeError(f"skinCluster '{skin}' does not exist.")

    print(f"\n[{skin}] transferring {len(mapping)} joint(s)...")

    # 1. Every joint named in the mapping must exist.
    for src, tgt in mapping:
        if not mc.objExists(src):
            raise RuntimeError(f"Source joint '{src}' does not exist.")
        if not mc.objExists(tgt):
            raise RuntimeError(f"Target joint '{tgt}' does not exist.")

    shape_dag = _skin_geometry(skin)

    # 2. Bind any target joint that isn't already an influence.
    influences = {
        _short(n) for n in (mc.skinCluster(skin, query=True, influence=True) or [])
    }
    for _, tgt in mapping:
        if _short(tgt) not in influences:
            mc.skinCluster(skin, edit=True, addInfluence=tgt, weight=0.0)
            influences.add(_short(tgt))
            print(f"  bound new influence: {tgt}")

    sel = om.MSelectionList()
    sel.add(skin)
    skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))

    infl_paths = skin_fn.influenceObjects()
    col_of: dict[str, int] = {}
    infl_indices = om.MIntArray()
    for col, path in enumerate(infl_paths):
        infl_indices.append(skin_fn.indexForInfluenceObject(path))
        col_of[path.partialPathName()] = col
        col_of[path.fullPathName()] = col
    n_infl = len(infl_paths)

    pair_cols: list[tuple[int, int, str, str]] = []
    for src, tgt in mapping:
        if _short(src) not in col_of:
            # Source carries no weight on this skinCluster — nothing to move.
            print(f"  skip: '{src}' is not an influence (no weight to move).")
            continue
        src_col = col_of.get(src, col_of.get(_short(src)))
        tgt_col = col_of.get(tgt, col_of.get(_short(tgt)))
        pair_cols.append((src_col, tgt_col, src, tgt))

    if not pair_cols:
        print("  nothing to transfer.")
        return

    # 3. Read all weights, move src -> tgt per vertex, write back.
    comp = _full_vertex_component(shape_dag)
    weights, _ = skin_fn.getWeights(shape_dag, comp)

    n_verts = len(weights) // n_infl
    moved = {tgt: 0.0 for _, _, _, tgt in pair_cols}
    for row in range(n_verts):
        base = row * n_infl
        for src_col, tgt_col, _, tgt in pair_cols:
            w = weights[base + src_col]
            if w != 0.0:
                weights[base + tgt_col] += w
                weights[base + src_col] = 0.0
                moved[tgt] += w

    skin_fn.setWeights(shape_dag, comp, infl_indices, weights, False)
    for src_col, tgt_col, src, tgt in pair_cols:
        print(f"  {src} -> {tgt}  (moved weight sum {moved[tgt]:.4f})")

    # 4. Remove the emptied source influences.
    if remove_sources:
        for src_col, tgt_col, src, tgt in pair_cols:
            if mc.objExists(src):
                mc.skinCluster(skin, edit=True, removeInfluence=src)
                print(f"  removed influence: {src}")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _short(name: str) -> str:
    return name.split("|")[-1].split(":")[-1]


def _skin_geometry(skin: str) -> om.MDagPath:
    geo = mc.skinCluster(skin, query=True, geometry=True) or []
    if not geo:
        raise RuntimeError(f"skinCluster '{skin}' drives no geometry.")
    dag = _dag(geo[0])
    if not dag.hasFn(om.MFn.kShape):
        dag.extendToShape()
    return dag


def _full_vertex_component(shape_dag: om.MDagPath) -> om.MObject:
    n_verts = om.MFnMesh(shape_dag).numVertices
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.addElements(list(range(n_verts)))
    return comp


def _dag(name: str) -> om.MDagPath:
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDagPath(0)
