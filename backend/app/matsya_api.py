from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.matsya.api import router as matsya_router
from app.matsya.settings import MatsyaSettings


settings = MatsyaSettings.from_env()

app = FastAPI(title="Matsya API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(matsya_router)
