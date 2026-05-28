r"""Caller:

import sys, importlib

project_path = r"C:\dev\hand_pose_with_sdk"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import capture_pose_data
importlib.reload(capture_pose_data)

data = capture_pose_data.run()
"""

from __future__ import annotations

import json

import maya.cmds as mc


CTRL: str = "lft_hand_ctrl"
SHAPE: str = "lft_hand_ctrlShape"

POSES: dict[str, tuple[int, int]] = {
    "poseFist":    (0, 19),
    "posePinky":   (20, 39),
    "poseScissor": (40, 59),
    "posePistol":  (60, 79),
}

SHAPE_ATTRS: tuple[str, ...] = (
    "fistWrist",
    "fistUpperHand",
    "fistLowerHand",
    "fistUpperThumb1",
    "fistLowerThumb1",
    "fistThumb2",
    "fistThumb3",
    "fistThumb4",
    "fistThumb5",
    "fistUpperIndex2",
    "fistLowerIndex2",
    "fistIndex3",
    "fistIndex4",
    "fistIndex5",
    "fistIndex6",
    "fistIndex7",
    "fistUpperMiddle2",
    "fistLowerMiddle2",
    "fistMiddle3",
    "fistMiddle4",
    "fistMiddle5",
    "fistMiddle6",
    "fistMiddle7",
    "fistUpperRing2",
    "fistLowerRing2",
    "fistRing3",
    "fistRing4",
    "fistRing5",
    "fistRing6",
    "fistRing7",
    "fistUpperPinky1",
    "fistLowerPinky1",
    "fistUpperPinky2",
    "fistLowerPinky2",
    "fistPinky3",
    "fistPinky4",
    "fistPinky5",
    "fistPinky6",
    "fistPinky7",
)

OUTPUT_PATH: str = r"C:\dev\hand_pose_with_sdk\pose_data.json"


def run(
    ctrl: str = CTRL,
    shape: str = SHAPE,
    poses: dict[str, tuple[int, int]] = POSES,
    shape_attrs: tuple[str, ...] = SHAPE_ATTRS,
    output_path: str = OUTPUT_PATH,
) -> dict:
    """Sample pose driver + shape attrs at every keyed frame in each range.

    Only attrs listed in `shape_attrs` are captured (missing ones are
    skipped with a warning).  Returns the dict and writes it to
    `output_path`.
    """
    if not mc.objExists(ctrl):
        mc.warning(f"Ctrl '{ctrl}' not found.")
        return {}
    if not mc.objExists(shape):
        mc.warning(f"Shape '{shape}' not found.")
        return {}

    attrs = [a for a in shape_attrs
             if mc.attributeQuery(a, node=shape, exists=True)]
    missing = set(shape_attrs) - set(attrs)
    if missing:
        mc.warning(f"Missing on '{shape}': {sorted(missing)}")
    if not attrs:
        mc.warning(f"None of the requested attrs exist on '{shape}'.")
        return {}

    original_time = mc.currentTime(query=True)

    data: dict = {}
    for pose, (start, end) in poses.items():
        driver_attr = f"{ctrl}.{pose}"
        if not mc.attributeQuery(pose, node=ctrl, exists=True):
            mc.warning(f"'{driver_attr}' not found; skipping.")
            continue

        frames = _keyed_frames(driver_attr, shape, attrs, start, end)
        if not frames:
            mc.warning(f"[{pose}] no keys found in frame {start}-{end}.")
            continue

        samples = []
        for f in frames:
            mc.currentTime(f)
            samples.append(
                {
                    "frame": float(f),
                    "driver_value": mc.getAttr(driver_attr),
                    "shape_values": {
                        a: mc.getAttr(f"{shape}.{a}") for a in attrs
                    },
                }
            )

        data[pose] = {
            "frame_range": [start, end],
            "samples": samples,
        }
        print(f"[{pose}] {len(samples)} key(s) across frame {start}-{end}")

    mc.currentTime(original_time)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved -> {output_path}")
    return data


def _keyed_frames(
    driver_attr: str,
    shape: str,
    shape_attrs: list[str],
    start: int,
    end: int,
) -> list[float]:
    keyed: set[float] = set()
    for plug in [driver_attr] + [f"{shape}.{a}" for a in shape_attrs]:
        times = mc.keyframe(plug, query=True, time=(start, end)) or []
        keyed.update(times)
    return sorted(keyed)
