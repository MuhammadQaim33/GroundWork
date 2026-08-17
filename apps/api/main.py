# ============================================================================
# main.py — the web API entrypoint.
#
# This file only ASSEMBLES the app: it creates the FastAPI app, mounts shared
# middleware/static files, registers one global error handler, and includes the
# route modules. Every endpoint lives in routes/*; every piece of logic lives
# in services/* or the domain modules (auth.py, store.py, llm.py, ...).
#
# Run it with:  poetry run uvicorn main:app --port 8000  (from apps/api)
# ============================================================================

import httpx

# FastAPI bits: FastAPI (the app itself), Request (the raw request).
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware  # lets the dashboard domain call us
from fastapi.responses import JSONResponse  # response types
from fastapi.staticfiles import StaticFiles  # serve static files (generated PDFs)

from compile import OUT_DIR
from errors import GenerationError
from routes import auth, generate, profile, settings

# Create the FastAPI application object. Routers below attach their routes to
# it. "title" is just the API's display name.
app = FastAPI(title="Groundwork Generator API")

# CORS = who is allowed to call this API from a browser. This opens it up to
# the local dashboard (localhost:3000) and all methods/headers. In production
# this would be locked to the real dashboard domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Make sure the folder for generated PDFs exists, then serve it at /out so
# the dashboard can fetch files by URL (e.g. /out/custom-resume-a1b2c3d4.pdf).
OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")


# A GLOBAL ERROR HANDLER: if any endpoint accidentally lets an LLM provider
# error (an httpx.HTTPStatusError) bubble up, this converts it into a clean,
# readable JSON error instead of an ugly server traceback.
@app.exception_handler(httpx.HTTPStatusError)
async def llm_provider_error(_request: Request, exc: httpx.HTTPStatusError):
    # 5xx provider errors = the AI service is broken → 502 (bad gateway).
    # Anything else (e.g. 400 bad request) → 400. Include a snippet of the
    # provider's message so the user has a clue what happened.
    status = 502 if exc.response.status_code >= 500 else 400
    snippet = exc.response.text[:300]
    return JSONResponse(
        status_code=status,
        content={"detail": f"LLM provider error ({exc.response.status_code}). {snippet}"},
    )


# The logic layer raises DOMAIN errors (errors.py), never HTTP ones. This is
# the single place they become HTTP responses — services stay usable by the
# MCP layer and the Radar cron, which catch them directly instead.
@app.exception_handler(GenerationError)
async def generation_error(_request: Request, exc: GenerationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)},
    )


# Attach every route module. Each one contributes the endpoints for one
# resource: auth, profile (CVs + brag doc), settings (keys + links), generate.
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(generate.router)