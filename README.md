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

## Run the full demo locally (landing → chat → dashboard)

Two PowerShell terminals, both started from the repository root. DEMO=true (the default) replays a precomputed real run in about 10 s, with a visible "Demo replay" tag; DEMO=false runs the real pipeline.

Terminal 1 (chat at http://127.0.0.1:8080/chat/, dashboard at http://127.0.0.1:8080/):
```
$env:GOOGLE_API_KEY="<your Gemini key>"; $env:GEMINI_API_KEY=$env:GOOGLE_API_KEY; $env:LLM_PROVIDER="gemini"; $env:DEMO="true"; $env:PORT="8080"; .venv\Scripts\python.exe deploy\server.py
```
Use `$env:LLM_PROVIDER="mock"` to run without a Gemini key. If a machine-wide `GOOGLE_API_KEY` exists, the Gemini SDK prefers it, so set it to the same key as above.

Terminal 2 (landing page at http://127.0.0.1:5500); the first time only, build it:
```
cd landing; npm ci; $env:VITE_CHAT_URL="http://127.0.0.1:8080/chat/"; npm run build:standalone; cd ..
mkdir runs_landing -Force; copy landing\dist-standalone\standalone.html runs_landing\index.html
.venv\Scripts\python.exe -m http.server 5500 --bind 127.0.0.1 --directory runs_landing
```

Walkthrough:
1. Open http://127.0.0.1:5500 and click **Start a design**.
2. In the chat, click **Load ITherm 2027 preset** (or upload a `.md` / `.pptx`) and answer `yes` to each group.
3. Click **Open modelling dashboard** and watch the Pareto front fill in.

CAD (STEP/STL/GLB) is exported only for the 5 selected designs, shown as diamonds on the plot. Other candidates show metrics only.
