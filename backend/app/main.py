from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.bhavcopy import BhavcopyService, BhavcopyStore
from app.config import Settings, get_settings
from app.schemas import BhavcopyRow, CoverageResponse, HealthResponse, ImportResponse, ImportStatusResponse
from app.store import AppStore


def build_bhavcopy_service(settings: Settings) -> BhavcopyService:
    store = AppStore(settings.database_path)
    return BhavcopyService(settings=settings, store=BhavcopyStore(settings, store))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.bhavcopy_service = build_bhavcopy_service(settings)
    yield


app = FastAPI(title="Bhavcopy App", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_bhavcopy_service_dep() -> BhavcopyService:
    return app.state.bhavcopy_service


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app="bhavcopy-app")


@app.post("/api/bhavcopy/import/upload", response_model=ImportResponse)
async def upload_bhavcopy_files(
    files: list[UploadFile] = File(...),
    service: BhavcopyService = Depends(get_bhavcopy_service_dep),
) -> ImportResponse:
    try:
        payload = [(file.filename or "upload.csv", await file.read()) for file in files]
        return ImportResponse(**service.import_files(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bhavcopy import failed: {exc}") from exc


@app.post("/api/bhavcopy/import/scan", response_model=ImportResponse)
async def scan_bhavcopy_inbox(
    service: BhavcopyService = Depends(get_bhavcopy_service_dep),
) -> ImportResponse:
    try:
        return ImportResponse(**service.import_inbox())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bhavcopy folder scan failed: {exc}") from exc


@app.get("/api/bhavcopy/import/status", response_model=ImportStatusResponse)
async def bhavcopy_import_status(
    service: BhavcopyService = Depends(get_bhavcopy_service_dep),
) -> ImportStatusResponse:
    return ImportStatusResponse(**service.status())


@app.get("/api/bhavcopy/coverage", response_model=CoverageResponse)
async def bhavcopy_coverage(
    service: BhavcopyService = Depends(get_bhavcopy_service_dep),
) -> CoverageResponse:
    return CoverageResponse(**service.coverage())


@app.get("/api/bhavcopy/rows", response_model=list[BhavcopyRow])
async def bhavcopy_rows(
    symbol: str = Query(min_length=1, max_length=32),
    limit: int = Query(default=80, ge=1, le=500),
    service: BhavcopyService = Depends(get_bhavcopy_service_dep),
) -> list[BhavcopyRow]:
    return [BhavcopyRow.model_validate(item) for item in service.rows_for_symbol(symbol, limit)]
