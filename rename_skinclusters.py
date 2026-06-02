r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import rename_skinclusters
importlib.reload(rename_skinclusters)

rename_skinclusters.run()
"""
from __future__ import annotations

import maya.cmds as mc


def run() -> None:
    """Rename every skinCluster / blendShape to '<deformed geometry>_<type>'."""
    _rename_deformers("skinCluster")
    _rename_deformers("blendShape")


def _rename_deformers(node_type: str) -> None:
    for node in mc.ls(type=node_type) or []:
        geo = mc.deformer(node, query=True, geometry=True) or []
        if not geo:
            mc.warning(f"'{node}' drives no geometry; skipped.")
            continue

        transform = mc.listRelatives(geo[0], parent=True, path=True) or [geo[0]]
        base = transform[0].split("|")[-1].split(":")[-1]
        new_name = f"{base}_{node_type}"
        if node == new_name:
            continue

        result = mc.rename(node, new_name)
        print(f"{node} -> {result}")
