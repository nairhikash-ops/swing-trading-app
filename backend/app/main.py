from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.schemas import HealthResponse, RenewResponse, TokenStatusResponse, TokenUpdateRequest
from app.scheduler import RenewalScheduler
from app.store import TokenStore
from app.token_service import TokenService


def build_token_service(settings: Settings) -> TokenService:
    return TokenService(settings=settings, store=TokenStore(settings.database_path))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    token_service = build_token_service(settings)
    scheduler = RenewalScheduler(settings, token_service)
    app.state.settings = settings
    app.state.token_service = token_service
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Swing Trading App", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_token_service_dep() -> TokenService:
    return app.state.token_service


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app="swing-trading-app")


@app.get("/api/dhan/status", response_model=TokenStatusResponse)
async def dhan_status(token_service: TokenService = Depends(get_token_service_dep)) -> TokenStatusResponse:
    return token_service.status()


@app.post("/api/dhan/status/refresh", response_model=TokenStatusResponse)
async def dhan_refresh_status(token_service: TokenService = Depends(get_token_service_dep)) -> TokenStatusResponse:
    try:
        return await token_service.refresh_profile()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dhan/token", response_model=TokenStatusResponse)
async def dhan_update_token(
    request: TokenUpdateRequest,
    token_service: TokenService = Depends(get_token_service_dep),
) -> TokenStatusResponse:
    try:
        return await token_service.save_manual_token(
            dhan_client_id=request.dhan_client_id,
            access_token=request.access_token,
            expiry_time=request.expiry_time,
            validate_with_dhan=request.validate_with_dhan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dhan/renew", response_model=RenewResponse)
async def dhan_renew(token_service: TokenService = Depends(get_token_service_dep)) -> RenewResponse:
    try:
        renewed, status, message = await token_service.renew_if_needed(force=True)
        return RenewResponse(renewed=renewed, status=status, message=message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
