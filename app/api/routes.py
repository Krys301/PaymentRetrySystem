from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Payment, PaymentStatus, get_db
from app.workers.celery_app import process_payment

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentRequest(BaseModel):
    idempotency_key: str
    amount: float
    currency: str = "EUR"


class PaymentResponse(BaseModel):
    id: int
    idempotency_key: str
    amount: float
    currency: str
    status: str
    retry_count: int
    error_message: str | None = None


@router.post("/", response_model=PaymentResponse, status_code=202)
def create_payment(payload: PaymentRequest, db: Session = Depends(get_db)):
    # Idempotency check — same key returns the existing record, no duplicate charge
    existing = db.query(Payment).filter(
        Payment.idempotency_key == payload.idempotency_key
    ).first()

    if existing:
        return existing

    payment = Payment(
        idempotency_key=payload.idempotency_key,
        amount=payload.amount,
        currency=payload.currency,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # Dispatch to Celery worker asynchronously
    process_payment.delay(payment.id)

    return payment


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get("/", response_model=list[PaymentResponse])
def list_payments(status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Payment)
    if status:
        query = query.filter(Payment.status == status)
    return query.order_by(Payment.created_at.desc()).limit(50).all()
