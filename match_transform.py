from typing import Dict, Any


def match_transform(
    source: str,
    target: str,
    translate: bool = True,
    rotate: bool = True,
) -> Dict[str, Any]:
    """Match the world-space transform of a target object to a source object.

    Uses xform with world space to correctly match transforms regardless of
    parent hierarchy or joint orient. This is the safe way to snap one object
    to another — never copy raw translate/rotate values with setAttr.

    Returns the resulting local translate and rotate values on the target
    after matching — use these directly as SDK driven values at driver=10.

    Args:
        source:    The object to match FROM (e.g. a pose joint).
        target:    The object to match TO (e.g. a finger ctrl_ofst node).
        translate: Whether to match world-space translation (default True).
        rotate:    Whether to match world-space rotation (default True).

    Returns:
        result_translate: Local translate [x, y, z] of target after match.
        result_rotate:    Local rotate [x, y, z] of target after match.

    Examples:
        # Match finger ctrl_ofst to pose joint in world space
        match_transform("pistol_lft_index_1_jnt", "lft_index_1_ctrl_ofst")

        # Match rotation only
        match_transform("pistol_lft_index_1_jnt", "lft_index_1_ctrl_ofst", translate=False)
    """
    import maya.cmds as cmds

    if not cmds.objExists(source):
        raise ValueError(f"Source object '{source}' does not exist in the scene.")

    if not cmds.objExists(target):
        raise ValueError(f"Target object '{target}' does not exist in the scene.")

    if translate:
        ws_translate = cmds.xform(source, q=True, ws=True, t=True)
        cmds.xform(target, ws=True, t=ws_translate)

    if rotate:
        ws_rotate = cmds.xform(source, q=True, ws=True, ro=True)
        cmds.xform(target, ws=True, ro=ws_rotate)

    # Read back the resulting local values on the target
    result_t = cmds.getAttr(f"{target}.translate")[0]
    result_r = cmds.getAttr(f"{target}.rotate")[0]

    return {
        "success":           True,
        "source":            source,
        "target":            target,
        "matched_translate": translate,
        "matched_rotate":    rotate,
        "result_translate":  list(result_t),
        "result_rotate":     list(result_r),
    }
