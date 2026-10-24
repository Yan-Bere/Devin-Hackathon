from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import AppConfig
from app.store import RunStore
from app.watcher import DirectoryWatcher, WebSocketHub


def create_app(cfg: AppConfig) -> FastAPI:
    store = RunStore(cfg)
    hub = WebSocketHub()
    watcher = DirectoryWatcher(store, hub)

    @asynccontextmanager
    async def lifespan(app):
        store.scan()
        watcher.start()
        yield
        await watcher.stop()

    app = FastAPI(title="CFD Optimization Dashboard", lifespan=lifespan)
    app.state.store = store
    app.state.watcher = watcher

    @app.get("/api/runs")
    def list_runs():
        return {"runs": store.list_runs(), "summary": store.summary()}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        residuals = run.residuals
        iterations = residuals["iterations"]
        fields = residuals["fields"]
        if len(iterations) > 500:
            indices = [round(i * (len(iterations) - 1) / 499) for i in range(500)]
            iterations = [iterations[index] for index in indices]
            fields = {
                name: [values[index] for index in indices]
                for name, values in fields.items()
            }
        return {**run.to_dict(), "residuals": {"iterations": iterations, "fields": fields}}

    @app.get("/api/runs/{run_id}/geometry")
    def get_geometry(run_id: str):
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        case_dir = cfg.runs_dir / run_id
        geometry_dir = case_dir / "constant" / "triSurface"
        files = sorted(geometry_dir.glob("*.stl")) if geometry_dir.is_dir() else []
        if not files:
            raise HTTPException(status_code=404, detail="Geometry not found")
        return FileResponse(files[0], media_type="model/stl", filename=files[0].name)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await hub.connect(websocket)
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "runs": store.list_runs(),
                    "summary": store.summary(),
                }
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)
        except Exception:
            hub.disconnect(websocket)
            raise

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
