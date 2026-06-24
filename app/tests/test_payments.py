import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, get_db
from app.main import app

TEST_DB_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_payment():
    response = client.post("/payments/", json={
        "idempotency_key": "test-key-001",
        "amount": 49.99,
        "currency": "EUR"
    })
    assert response.status_code == 202
    data = response.json()
    assert data["idempotency_key"] == "test-key-001"
    assert data["amount"] == 49.99
    assert data["status"] == "pending"


def test_idempotency_same_key_returns_existing():
    payload = {"idempotency_key": "idempotent-key-002", "amount": 100.0}

    r1 = client.post("/payments/", json=payload)
    r2 = client.post("/payments/", json=payload)

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]  # Same record, no duplicate


def test_get_payment_not_found():
    response = client.get("/payments/99999")
    assert response.status_code == 404
