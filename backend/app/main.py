from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.services.ingestion_service import seed_all
from app.routes import tickets, orders, seed, similarity, resolution, replies, dashboard, human_decisions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown actions."""
    await init_db()
    if settings.AUTO_SEED_ON_STARTUP:
        try:
            await seed_all(settings.CSV_DIR)
        except Exception as e:
            # Prevent startup crash if sample data is missing in test environments
            pass
    yield


app = FastAPI(
    title="Support Ticket Manager API",
    description="Backend API for customer support ticket management and similarity matching",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(tickets.router)
app.include_router(orders.router)
app.include_router(seed.router)
app.include_router(similarity.router)
app.include_router(resolution.router)
app.include_router(replies.router)
app.include_router(dashboard.router)
app.include_router(human_decisions.router)


@app.get("/")
async def root():
    return {"message": "Support Ticket Manager API is running"}
