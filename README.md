# Hand Pose SDK Setup

Maya rigging project — pose-driven finger controls via Set Driven Keys.

## Folder Structure

```
hand_pose_with_sdk/
│
├── CLAUDE.md                  # Claude Code prompt — open this in Claude Code
│
├── hand_pose_setup.py         # Standalone Maya Python script
│                                Run directly in Maya Script Editor
│
└── mcp_tools/
    ├── add_attribute.py       # Add to MayaMCP server
    ├── lock_attribute.py      # Add to MayaMCP server
    └── match_transform.py     # Add to MayaMCP server
```

## Usage

### Option A — Claude Code + MayaMCP
1. Add the three files in `mcp_tools/` to your MayaMCP server
2. Open this folder in Claude Code: `claude C:\dev\hand_pose_with_sdk`
3. Claude Code will read `CLAUDE.md` automatically and execute the full setup via MCP

### Option B — Maya Script Editor
1. Open `hand_pose_setup.py` in Maya's Script Editor
2. Set tab to Python and run with Ctrl+Enter
