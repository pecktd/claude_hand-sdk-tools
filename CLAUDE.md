# Hand Pose SDK Setup — Claude Code Prompt

You are working on a Maya rigging project to set up pose-driven finger controls
using MayaMCP. All project files are in this folder.

---

## Project Files

- `hand_pose_setup.py` — Standalone Python script (run directly in Maya Script Editor)
- `mcp_tools/add_attribute.py` — MCP tool to add to MayaMCP server
- `mcp_tools/lock_attribute.py` — MCP tool to add to MayaMCP server
- `mcp_tools/match_transform.py` — MCP tool to add to MayaMCP server

---

## Context

The Maya scene contains a character rig with:
- `hand_pose_grp` — root group containing pose reference joints
- `lft_hand_ctrl` and `rgt_hand_ctrl` — hand controls to receive attributes
- Individual finger control offset nodes named exactly `[side]_[finger]_[number]_ctrl_ofst`
  - Example: `lft_thumb_1_ctrl_ofst`, `lft_index_2_ctrl_ofst`, `rgt_middle_3_ctrl_ofst`
  - These are finger-level nodes only — never target `lft_hand_ctrl_ofst` or any hand-level offset

---

## Pose Joint Naming Convention

```
[pose]_[side]_[part]_jnt
```
Example: `pistol_lft_index_1_jnt`

- `pose` = first token (e.g. `fist`, `pistol`, `pinky`)
- `side` = second token (`lft` or `rgt`)
- `part` = third token (finger name or arm part)

---

## MCP Tools Available

Make sure these three tools are added to the MayaMCP server before running:
- `add_attribute` — add attributes with type, min, max, locked, keyable
- `lock_attribute` — lock/unlock attributes
- `match_transform` — snap target to source in world space, returns `result_translate`
  and `result_rotate` to use directly as SDK values at driver=10

Built-in MayaMCP tools also used:
- `set_object_attribute` — set driver attribute values
- `set_object_transform_attributes` — reset finger offset nodes translate/rotate to zero
- `set_driven_key` — create SDK relationships
- `manage_attributes` with `reorder_attr` — reorder attributes if needed

---

## Task — Execute in this exact order

### Step 1 — Add attributes
For each hand ctrl (`lft_hand_ctrl`, `rgt_hand_ctrl`):

1. Add a separator attribute named `__pose__`:
   - type: `int`
   - locked: `True`
   - keyable: `True`

2. Add one float attribute per pose found under `hand_pose_grp`:
   - name: `pose` + capitalized pose name — e.g. `poseFist`, `posePistol`, `posePinky`
   - type: `float`
   - min: `0`, max: `10`, default: `0`
   - keyable: `True`

Use the `add_attribute` MCP tool for this.

### Step 2 — Set up Set Driven Keys

**Finger parts to include:** `thumb`, `index`, `middle`, `ring`, `pinky`
**Skip:** arm, wrist, hand joints

Process each pose, each side, each finger — strictly in parent-to-child order
(`_1` → `_2` → `_3` → `_4`). Complete all steps A → B → C for one joint
before moving to the next.

---

## Per-Joint SDK Sequence

Using `lft_thumb_1_ctrl_ofst` driven by `lft_hand_ctrl.poseFist` from pose
joint `fist_lft_thumb_1_jnt` as the example:

**Step A — Match and store:**
- Call `match_transform(source=fist_lft_thumb_1_jnt, target=lft_thumb_1_ctrl_ofst)`
- Store the returned `result_translate` and `result_rotate` as the pose values

**Step B — Set driven keys:**
- Using `set_driven_key`, set up both key states:
  - Driver: `lft_hand_ctrl.poseFist`
  - Driven: `lft_thumb_1_ctrl_ofst`
  - At driver value `0` → translate `[0, 0, 0]`, rotate `[0, 0, 0]`
  - At driver value `10` → translate and rotate = stored values from Step A

**Step C — Set driver to 10:**
- Set `lft_hand_ctrl.poseFist` to `10` using `set_object_attribute`
- This keeps `lft_thumb_1_ctrl_ofst` in its matched pose position so the next
  child (`lft_thumb_2_ctrl_ofst`) can be correctly matched in world space

**Repeat Steps A → B → C** for `_2`, `_3`, `_4` and so on.

**Step D — Cleanup after all joints in this pose are done:**
- Set driver attr back to `0` using `set_object_attribute`
- The SDK automatically drives all finger offset nodes back to zero —
  no manual reset needed

---

## Important Rules

- **Complete Steps A → B → C for each joint before moving to the next**
- **Driver stays at 10 between joints (Step C)** — keeps parent in posed position
  so child matches correctly in world space
- **Only set driver back to 0 after entire pose is done (Step D)** — SDK handles
  resetting all offsets automatically
- **`match_transform` only** — never use `setAttr`, `xform`, or raw value copying
- **Finger offsets only** — driven object is always `[side]_[finger]_[number]_ctrl_ofst`,
  never a hand-level node like `lft_hand_ctrl_ofst`
- Skip any joint or finger offset that doesn't exist — warn and continue
- Both `lft` and `rgt` sides must be fully set up

---

Begin with Step 1.
