import json
import subprocess
import sys
from pathlib import Path
from fastapi.testclient import TestClient

from services.extractor.main import app as extractor_app
from services.documents.main import app as documents_app


def test_extractor_health_ready_reflects_shutdown_state():
    with TestClient(extractor_app) as client:
        # Initially ready
        res = client.get("/health/ready")
        assert res.status_code == 200
        assert res.json()["status"] == "ready"

        # Simulate shutdown initiated
        extractor_app.state.extraction_runtime._accepting = False
        try:
            res = client.get("/health/ready")
            assert res.status_code == 503
            assert res.json()["status"] == "not_ready"
        finally:
            extractor_app.state.extraction_runtime._accepting = True


def test_documents_service_readiness_and_shutdown():
    with TestClient(documents_app) as client:
        res = client.get("/health/ready")
        assert res.status_code == 200
        assert res.json()["status"] == "ready"

        # Simulate shutdown
        documents_app.state.is_ready = False
        try:
            res = client.get("/health/ready")
            assert res.status_code == 503
            assert res.json()["status"] == "not_ready"
        finally:
            documents_app.state.is_ready = True


def test_benchmark_script_runs_successfully():
    sample_pdf = Path("tests/stress/pdfs/2020-Scrum-Guide-Spanish-Latin-South-American.pdf")
    assert sample_pdf.exists()

    result = subprocess.run(
        [sys.executable, "scripts/benchmark_extractor.py", str(sample_pdf), "--runs", "3"],
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)
    assert data["pages"] == 16
    assert data["bytes"] > 0
    assert data["runs"] == 3
    assert "milliseconds" in data
    assert "mean" in data["milliseconds"]
    assert "median" in data["milliseconds"]
