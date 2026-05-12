from typing import Dict, Any, Optional


def add_attribute(
    object_name: str,
    attribute: str,
    attribute_type: str = "float",
    default_value: float = 0.0,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    keyable: bool = True,
    locked: bool = False,
) -> Dict[str, Any]:
    """Add a custom attribute to a Maya object.

    Available attribute types:
    - float: Floating point number
    - int: Integer number (stored as 'long' in Maya)
    - bool: Boolean (True/False)
    - string: String value

    Args:
        object_name:    Name of the Maya object.
        attribute:      Name of the new attribute.
        attribute_type: Type of the attribute — 'float', 'int', 'bool', 'string'.
        default_value:  Default value for the attribute (float/int/bool only).
        min_value:      Optional minimum value (float/int only).
        max_value:      Optional maximum value (float/int only).
        keyable:        Whether the attribute appears in the channel box (default True).
        locked:         Whether the attribute is locked after creation (default False).

    Examples:
        # Add a float pose slider
        add_attribute("lft_hand_ctrl", "poseFist", "float", min_value=0, max_value=10)

        # Add a locked int separator
        add_attribute("lft_hand_ctrl", "__pose__", "int", locked=True)

        # Add a bool toggle
        add_attribute("myCtrl", "ikFkSwitch", "bool", default_value=0)
    """
    import maya.cmds as cmds

    if not cmds.objExists(object_name):
        raise ValueError(f"Object '{object_name}' does not exist in the scene.")

    if cmds.attributeQuery(attribute, node=object_name, exists=True):
        raise ValueError(f"Attribute '{attribute}' already exists on '{object_name}'.")

    # Map friendly type names to Maya attributeType values
    type_map = {
        "float":  "double",
        "int":    "long",
        "bool":   "bool",
        "string": "string",
    }

    at = type_map.get(attribute_type.lower())
    if at is None:
        raise ValueError(
            f"Unknown attribute_type '{attribute_type}'. Use: float, int, bool, string."
        )

    kwargs = {
        "longName":      attribute,
        "attributeType": at,
        "keyable":       keyable,
    }

    if at not in ("string", "bool"):
        kwargs["defaultValue"] = default_value
        if min_value is not None:
            kwargs["minValue"] = min_value
        if max_value is not None:
            kwargs["maxValue"] = max_value

    cmds.addAttr(object_name, **kwargs)

    if locked:
        cmds.setAttr(f"{object_name}.{attribute}", lock=True)

    return {
        "success":        True,
        "object":         object_name,
        "attribute":      attribute,
        "attribute_type": at,
        "default_value":  default_value,
        "min_value":      min_value,
        "max_value":      max_value,
        "keyable":        keyable,
        "locked":         locked,
    }
