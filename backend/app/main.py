from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.routers import activity, auth, clients, documents, intelligence, jobs, leads, marketing, products, team, web

settings = get_settings()
app = FastAPI(title=settings.app_name, version="5.0.0-phase5",
              description="GrowthCognix — multi-tenant growth intelligence platform (Phase 1 foundation + Phase 2 client intelligence engine + Phase 3 website audit & competitor intelligence + Phase 4 buyer discovery & lead intelligence + Phase 5 marketing strategy & campaigns).")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"].removeprefix("Value error, ")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Please check the highlighted fields", "errors": errors})


for r in (auth.router, team.router, clients.router, products.router, documents.router,
          jobs.router, jobs.agents_router, activity.router, intelligence.router, web.router, leads.router, marketing.router):
    app.include_router(r)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "phase": 5}
