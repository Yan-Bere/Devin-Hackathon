# Cold-plate demo stack

Three stages + a dashboard:
- `stage1_intake/` — Gradio chat (:7860) that finalizes requirements.
- `stage2_optimizer/` — teammate optimizer (kept as is).
- `stage3_modelling/` — this repo's reduced-order engine (Devin parse ->
  normalized inputs -> channel designs -> thermal/hydraulic -> Pareto).
- `cfd-dashboard/` — run/Pareto dashboard (:8000); also ingests stage-3 runs.

## Demo (one command)

PowerShell or Git Bash:

    python run_demo_stack.py

DEMO=true (default) replays a real recorded run into the dashboard in ~10 s;
DEMO=false runs the live engine (uses Devin quota).

## Components

- stage3 engine docs: `stage3_modelling/README.md` (paths updated for the move).
- Engine results contract: `stage3_modelling/docs/API_CONTRACT.md`.
