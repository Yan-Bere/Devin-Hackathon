"""Single-process demo backend: dashboard (+API, /ws) at / and the Gradio chat at /chat."""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("PORT", "8080"))
os.environ.setdefault("DEMO", "true")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DASHBOARD_URL", f"http://127.0.0.1:{PORT}")
os.environ.setdefault("DASHBOARD_BROWSER_URL", "/")

sys.path.insert(0, str(ROOT / "cfd-dashboard" / "backend"))
from app.config import AppConfig  # noqa: E402  (cfd-dashboard package "app")
from app.main import create_app  # noqa: E402

# stage1_intake/app.py clashes with the dashboard's "app" package; load it by path.
sys.path.append(str(ROOT / "stage1_intake"))
_spec = importlib.util.spec_from_file_location("intake_app", ROOT / "stage1_intake" / "app.py")
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)

import gradio as gr  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
import uvicorn  # noqa: E402

runs_dir = Path(os.getenv("CFD_RUNS_DIR", ROOT / "cfd-dashboard" / "runs_modelling"))
runs_dir.mkdir(parents=True, exist_ok=True)
app = create_app(AppConfig(
    runs_dir=runs_dir,
    budget=int(os.getenv("CFD_BUDGET", "40")),
    poll_interval=float(os.getenv("CFD_POLL_INTERVAL", "0.25")),
))

# The dashboard's static mount at "/" would shadow /chat, so mount Gradio first.
frontend = [r for r in app.router.routes if getattr(r, "name", None) == "frontend"]
for route in frontend:
    app.router.routes.remove(route)
app.add_api_route("/chat", lambda: RedirectResponse("/chat/"), include_in_schema=False)
app = gr.mount_gradio_app(app, intake.build_app(os.getenv("LLM_PROVIDER")).queue(),
                          path="/chat", **intake.ui_style.LAUNCH_KWARGS)
app.router.routes.extend(frontend)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
