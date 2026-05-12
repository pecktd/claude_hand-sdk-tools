from typing import Dict, Any, Optional


def lock_attribute(
    object_name: str,
    attribute: str,
    locked: bool = True,
    keyable: Optional[bool] = None,
) -> Dict[str, Any]:
    """Lock or unlock an attribute on a Maya object.
    Optionally set its keyable state at the same time.

    Args:
        object_name: Name of the Maya object.
        attribute:   Name of the attribute to lock/unlock.
        locked:      True to lock, False to unlock (default True).
        keyable:     Optionally set the keyable state at the same time.

    Examples:
        # Lock a separator attribute
        lock_attribute("lft_hand_ctrl", "__pose__", locked=True)

        # Unlock an attribute and hide it from the channel box
        lock_attribute("lft_hand_ctrl", "poseFist", locked=False, keyable=False)
    """
    import maya.cmds as cmds

    if not cmds.objExists(object_name):
        raise ValueError(f"Object '{object_name}' does not exist in the scene.")

    if not cmds.attributeQuery(attribute, node=object_name, exists=True):
        raise ValueError(f"Attribute '{attribute}' does not exist on '{object_name}'.")

    full_attr = f"{object_name}.{attribute}"

    # Must unlock briefly to change keyable state if currently locked
    if keyable is not None:
        was_locked = cmds.getAttr(full_attr, lock=True)
        if was_locked:
            cmds.setAttr(full_attr, lock=False)
        cmds.setAttr(full_attr, keyable=keyable)
        if was_locked:
            cmds.setAttr(full_attr, lock=True)

    cmds.setAttr(full_attr, lock=locked)

    return {
        "success":   True,
        "object":    object_name,
        "attribute": attribute,
        "locked":    locked,
        "keyable":   keyable,
    }
