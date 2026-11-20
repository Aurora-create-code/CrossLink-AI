from contextlib import asynccontextmanager
import logging
import sqlite3

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.config import Settings
from app import database
from app.adapters.thingo import ThingoAdapter
from app.documents import router_for, UploadLimitMiddleware
from app.knowledge import router_for as knowledge_router
from app.opportunities import router_for as opportunity_router
from app.reports import router_for as report_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.load()
    gateway = ThingoAdapter(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize(config.database_path)
        yield

    app = FastAPI(title='CrossLink AI API', version='0.5.0', lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware)
    app.include_router(router_for(config.database_path))
    app.include_router(knowledge_router(config.database_path, gateway))
    app.include_router(opportunity_router(config.database_path, gateway))
    app.include_router(report_router(config.database_path))

    @app.get('/api/health', tags=['system'])
    def health():
        try:
            db_status = database.health(config.database_path)
        except (sqlite3.Error, OSError, RuntimeError):
            logger.error('Database health check failed')
            return JSONResponse(status_code=503, content={
                'status': 'degraded', 'service': 'crosslink-api',
                'database': {'status': 'error'}, 'thingo': gateway.configuration_status(),
            })
        return {
            'status': 'ok', 'service': 'crosslink-api',
            'database': db_status, 'thingo': gateway.configuration_status(),
        }

    return app


app = create_app()
