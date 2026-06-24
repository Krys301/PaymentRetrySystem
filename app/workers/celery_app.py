import random

from celery import Celery
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Payment, PaymentStatus, SessionLocal

celery_app = Celery(
    "payment_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)


def _simulate_payment_gateway(amount: float) -> bool:
    """Simulate an external payment gateway with a 30% failure rate."""
    return random.random() > 0.3


@celery_app.task(bind=True, name="process_payment")
def process_payment(self, payment_id: int):
    db: Session = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return {"error": "Payment not found"}

        payment.status = PaymentStatus.PROCESSING
        db.commit()

        success = _simulate_payment_gateway(payment.amount)

        if success:
            payment.status = PaymentStatus.SUCCESS
            payment.error_message = None
            db.commit()
            return {"status": "success", "payment_id": payment_id}

        # Payment failed — decide whether to retry or dead-letter
        payment.retry_count += 1
        payment.error_message = "Gateway declined the transaction"

        if payment.retry_count >= settings.max_retries:
            payment.status = PaymentStatus.DEAD_LETTER
            db.commit()
            return {"status": "dead_letter", "payment_id": payment_id, "retries": payment.retry_count}

        # Schedule next retry with exponential backoff
        delay = settings.retry_delays_seconds[payment.retry_count - 1]
        payment.status = PaymentStatus.PENDING
        db.commit()

        process_payment.apply_async(args=[payment_id], countdown=delay)
        return {"status": "retrying", "payment_id": payment_id, "retry": payment.retry_count, "delay_seconds": delay}

    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=60, max_retries=3)
    finally:
        db.close()
