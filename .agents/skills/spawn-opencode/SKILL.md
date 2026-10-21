---
name: spawn-opencode
description: Spawns an interactive OpenCode CLI session with a specific provider/model and task prompt in a new terminal window so the user can provide live input and close it when done.
---

# Spawn OpenCode Interactive Session

Use this skill when the user asks to delegate a task to `opencode` in a new terminal window, specify an OpenCode model, or run an interactive OpenCode session.

## Parameters
1. **Model (`provider/model`)**: The model identifier in OpenCode format. Recommended defaults:
   - `opencode/deepseek-v4.1-flash-free` (Default fast free reasoning/coding model)
   - `opencode/glm-5.3-flash-free` (Free coding model)
2. **Initial Task Prompt**: The instruction or task for OpenCode to execute upon startup.

## Execution Steps
1. Verify `opencode` is installed (`opencode --version` or `Get-Command opencode` in PowerShell / `command -v opencode` in bash).
2. Run the bundled launcher script from the repository workspace:

### On Windows (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File ".agents/skills/spawn-opencode/scripts/launch_opencode.ps1" -Model "opencode/deepseek-v4.1-flash-free" -Prompt "<task_prompt>"
```

Or with GLM:
```powershell
powershell -ExecutionPolicy Bypass -File ".agents/skills/spawn-opencode/scripts/launch_opencode.ps1" -Model "opencode/glm-5.3-flash-free" -Prompt "<task_prompt>"
```

### On macOS / Linux / WSL / Git Bash:
```bash
./.agents/skills/spawn-opencode/scripts/launch_opencode.sh "opencode/deepseek-v4.1-flash-free" "<task_prompt>"
```

3. Wait for the script to finish (it blocks until the user closes the OpenCode session) and then inspect `git status` or modified files to continue the workflow.
