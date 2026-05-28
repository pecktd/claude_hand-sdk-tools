r"""Apply captured pose data as set-driven-keys.

Intended to be called from a builder script::

    import apply_pose_sdk
    importlib.reload(apply_pose_sdk)

    apply_pose_sdk.apply(data)
"""

from __future__ import annotations

import maya.cmds as mc


def apply(data: dict, clear_existing: bool = True) -> None:
    """Build set-driven-keys from a captured pose-data dict.

    Multiple poses can drive the same shape attr; Maya inserts a
    `blendWeighted` node automatically so the SDKs coexist.

    `clear_existing=True` removes time-based animation from the driver
    attrs and from every driven shape attr ONCE up-front, so the SDK
    becomes the sole source of motion.  It does NOT clear between
    poses (that would wipe out SDKs built by earlier poses).
    """
    if not data:
        mc.warning("No pose data provided.")
        return

    if clear_existing:
        _clear_existing_anim(data)

    for pose, info in data.items():
        driver_attr = info["driver"]
        shape = info["shape"]
        samples = info["samples"]

        if not mc.objExists(driver_attr.split(".")[0]):
            mc.warning(f"[{pose}] driver node missing; skipping.")
            continue
        if not mc.objExists(shape):
            mc.warning(f"[{pose}] shape '{shape}' missing; skipping.")
            continue

        active = _active_attrs(samples)
        if not active:
            print(f"[{pose}] no varying shape attrs; skipping.")
            continue

        for attr in active:
            for s in samples:
                mc.setDrivenKeyframe(
                    shape,
                    attribute=attr,
                    currentDriver=driver_attr,
                    driverValue=s["driver_value"],
                    value=s["shape_values"][attr],
                )
        print(f"[{pose}] built SDK for {len(active)} attr(s) "
              f"across {len(samples)} key(s)")

    print("\n[DONE]")


def _clear_existing_anim(data: dict) -> None:
    """Cut time-based keys on all drivers + every driven plug, once."""
    driver_plugs: set[str] = set()
    driven_plugs: set[str] = set()
    for info in data.values():
        driver_plugs.add(info["driver"])
        shape = info["shape"]
        for attr in _active_attrs(info["samples"]):
            driven_plugs.add(f"{shape}.{attr}")

    for plug in driver_plugs | driven_plugs:
        if mc.objExists(plug):
            mc.cutKey(plug, clear=True)


def _active_attrs(samples: list[dict]) -> list[str]:
    """Return shape attrs whose value is non-zero at any sample frame."""
    if not samples:
        return []
    active: list[str] = []
    for attr in samples[0]["shape_values"]:
        for s in samples:
            if s["shape_values"].get(attr, 0.0) != 0.0:
                active.append(attr)
                break
    return active
