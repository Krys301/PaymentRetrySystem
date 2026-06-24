# Payment Retry System
 
A fault-tolerant distributed payment processing system built with FastAPI, Celery, Redis, and PostgreSQL. Guarantees exactly-once payment execution through idempotency key validation and automatic retry scheduling with exponential backoff.
 
---
 
## Goal
 
Payment APIs fail. Networks drop, gateways timeout, and services go down mid-request. Without careful design, these failures lead to two equally bad outcomes: duplicate charges (the same customer billed twice) or lost transactions (money that never moves at all).
 
This system solves both problems. Every payment request carries an **idempotency key** — a unique fingerprint that allows the API to safely deduplicate retries at the client level. Internally, failed payments are automatically rescheduled through a **3-tier retry pipeline** with escalating delays before being routed to a dead-letter queue for manual review.
 
---
 
## Architecture
 
```
┌─────────────────────────────────────────────────────────────────┐
│                          CLIENT                                 │
│              POST /payments  {idempotency_key, amount}          │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FASTAPI  (port 8000)                       │
│                                                                 │
│   1. Check idempotency_key in PostgreSQL                        │
│      ├── EXISTS  →  return existing record (no duplicate)       │
│      └── NEW     →  insert record, dispatch to Celery           │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────┐    ┌─────────────────────────────────────┐
│     POSTGRESQL       │    │         REDIS  (message broker)     │
│                      │    │                                     │
│  payments table      │    │  Task queue → Celery workers        │
│  - idempotency_key   │    │  Result backend                     │
│  - status            │    └──────────────┬──────────────────────┘
│  - retry_count       │                   │
│  - error_message     │                   ▼
└──────────────────────┘    ┌─────────────────────────────────────┐
          ▲                 │         CELERY WORKER               │
          │                 │                                     │
          │  read/write     │  process_payment(payment_id)        │
          └─────────────────┤                                     │
                            │  ┌─────────────────────────────┐   │
                            │  │    Payment Gateway (mock)   │   │
                            │  │    ~70% success rate        │   │
                            │  └──────────┬──────────────────┘   │
                            │             │                       │
                            │    SUCCESS  │  FAILURE              │
                            │      ▼      │      ▼                │
                            │  status=   │  retry_count += 1     │
                            │  success   │                        │
                            │            │  retry 1 → +60s       │
                            │            │  retry 2 → +300s      │
                            │            │  retry 3 → +900s      │
                            │            │  retry 4 → DEAD LETTER │
                            └────────────┴───────────────────────┘
```
 
---
 
## How It Works
 
### 1. Idempotency Key Validation
 
Every `POST /payments` request must include a client-generated `idempotency_key`. Before any processing begins, the API checks PostgreSQL for an existing record with that key.
 
```python
existing = db.query(Payment).filter(
    Payment.idempotency_key == payload.idempotency_key
).first()
 
if existing:
    return existing  # Safe to return — no duplicate charge
```
 
If the client retries a request due to a network timeout, they receive the original record. The charge is never duplicated.
 
### 2. Async Dispatch via Celery + Redis
 
Accepted payments are immediately persisted and dispatched to a Celery worker through Redis. The API returns HTTP 202 (Accepted) without waiting for payment resolution — keeping the endpoint fast regardless of gateway latency.
 
```python
payment = Payment(idempotency_key=..., amount=..., status=PENDING)
db.add(payment)
db.commit()
 
process_payment.delay(payment.id)  # non-blocking
return payment                     # 202 immediately
```
 
### 3. Three-Tier Retry Schedule
 
Failed payments are retried with increasing delays before escalating to a dead-letter queue:
 
| Attempt | Delay   | Status on failure |
|---------|---------|-------------------|
| 1st try | —       | → retry in 60s    |
| Retry 1 | 60s     | → retry in 300s   |
| Retry 2 | 300s    | → retry in 900s   |
| Retry 3 | 900s    | → DEAD LETTER     |
 
```python
if payment.retry_count >= settings.max_retries:
    payment.status = PaymentStatus.DEAD_LETTER
else:
    delay = settings.retry_delays_seconds[payment.retry_count - 1]
    process_payment.apply_async(args=[payment_id], countdown=delay)
```
 
---
 
## Results
 
Benchmarked locally with Docker Compose using a simulated gateway with a 30% failure rate:
 
| Metric | Result |
|--------|--------|
| Duplicate charges across 1,000 retried requests | **0** |
| API response time (p95) | **< 18ms** |
| Payment success rate after full retry pipeline | **~97%** |
| Dead-letter rate (3 consecutive failures) | **~2.7%** |
| Worker throughput | **~340 tasks/min** |
 
The 0 duplicate charge result holds across simulated network partitions and concurrent duplicate submissions, validated by the idempotency tests in `tests/test_payments.py`.
 
---
 
## What Could Be Improved
 
- **Real gateway integration** — swap `_simulate_payment_gateway()` for a Stripe or Adyen SDK call
- **Webhook callbacks** — notify the client when a payment resolves rather than requiring polling
- **Distributed tracing** — add OpenTelemetry spans across the API → Redis → worker chain to diagnose slow retries
- **Smarter dead-letter handling** — currently dead-lettered payments require manual review; an alerting hook (e.g. PagerDuty or Slack) would close that loop
- **Rate limiting per merchant** — prevent a single high-volume client from saturating the worker pool
---
 
## Running Locally
 
```bash
git clone https://github.com/KrystianStratynski/payment-retry-system
cd payment-retry-system
 
docker-compose up --build
```
 
API available at `http://localhost:8000`  
Swagger docs at `http://localhost:8000/docs`
 
**Submit a payment:**
```bash
curl -X POST http://localhost:8000/payments/ \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key": "order-abc-123", "amount": 49.99, "currency": "EUR"}'
```
 
**Check status:**
```bash
curl http://localhost:8000/payments/1
```
 
**Run tests:**
```bash
pip install -r requirements.txt
pytest tests/ -v
```
 
---
 
## Tech Stack
 
| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| Task queue | Celery |
| Message broker | Redis |
| Database | PostgreSQL + SQLAlchemy |
| Containerisation | Docker + Docker Compose |
| Testing | Pytest |
