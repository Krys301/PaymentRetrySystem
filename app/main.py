from fastapi import FastAPI

from app.api.routes import router
from app.db.models import create_tables

app = FastAPI(
    title="Payment Retry System",
    description="Fault-tolerant distributed payment processing with idempotency and automatic retries",
    version="1.0.0",
)

app.include_router(router)


@app.on_event("startup")
def startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok"}
