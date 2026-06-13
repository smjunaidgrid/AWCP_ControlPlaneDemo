"""Unified AWCP gateway — one origin for the User/Control surface and the
Governance/Radar plane.

We MOUNT the two existing FastAPI apps rather than merging their routers. This
preserves each sub-app's lifespan and in-memory state unchanged:
  - the radar app keeps its background process scanner + Temporal client,
  - the control app keeps its registry bootstrap.

Routes:
  /                -> redirect to the user/control UI
  /healthz         -> gateway liveness + mount listing
  /control/...     -> control surface (/agents, /run, /ask, /status/{id}, UI)
  /governance/...  -> radar plane (/agents, /agents/{id}/gate, /signal, /events, ...)
"""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from awcp.control.api import app as control_app
from awcp.radar.api import app as radar_app

app = FastAPI(title="AWCP Gateway")

# Governance/registry plane (scanner + Temporal lifespan travels with it).
app.mount("/governance", radar_app)
# User/control surface (run, ask, status, picker UI).
app.mount("/control", control_app)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/control/")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "mounts": ["/control", "/governance"]}
