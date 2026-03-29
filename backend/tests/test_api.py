from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.deps import get_orchestrator, get_export_service
from backend.app.main import create_app
from backend.app.schemas.responses import InsightPackage
from backend.app.schemas.domain import ArtifactRef, Citation, Entity, Metric, TableData, VisualizationSpec


class DummyArtifactContext:
    pass


class FakeOrchestrator:
    async def analyze(self, _request):
        return InsightPackage(
            analysis_id="analysis-1",
            summary="Revenue rose in Q2.",
            insights=["Q2 was the peak quarter."],
            metrics=[Metric(label="Peak revenue", value=89)],
            entities=[Entity(name="Q2", type="quarter", value=89)],
            tables=[TableData(name="Revenue", columns=["quarter", "revenue"], rows=[["Q1", 45], ["Q2", 89]])],
            visualizations=[
                VisualizationSpec(
                    id="viz-1",
                    title="Revenue by quarter",
                    kind="bar",
                    reason="Category comparison",
                    labels=["Q1", "Q2"],
                    values=[45, 89],
                )
            ],
            citations=[Citation(title="Uploaded data", artifact_name="inputs/source_1.normalized.txt")],
            artifacts=[ArtifactRef(name="analyses/analysis-1.json", mime_type="application/json", version=1)],
        )

    def artifact_context_for(self, _analysis_id):
        return DummyArtifactContext()

    def ensure_google_auth(self):
        return None


class FakeExportService:
    def build_export(self, analysis_id, fmt, _artifact_context):
        assert analysis_id == "analysis-1"
        if fmt == "json":
            return '{"analysis_id":"analysis-1"}\n', "application/json", "exports/analysis-1.json"
        return "summary,chart_type,label,value\nRevenue rose in Q2.,bar,Q1,45\n", "text/csv; charset=utf-8", "exports/analysis-1.csv"


def create_test_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: FakeOrchestrator()
    app.dependency_overrides[get_export_service] = lambda: FakeExportService()
    return TestClient(app)


def test_health_endpoint() -> None:
    client = create_test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_endpoint() -> None:
    client = create_test_client()
    response = client.post(
        "/api/v1/analyze",
        json={
            "prompt": "Analyze revenue",
            "sources": [{"type": "text", "text": "Q1 45, Q2 89"}],
            "options": {"allow_web_research": False, "allow_scraping": True, "max_visualizations": 2},
        },
    )
    assert response.status_code == 200
    assert response.json()["analysis_id"] == "analysis-1"


def test_legacy_run_endpoint() -> None:
    client = create_test_client()
    response = client.post("/run", json={"text": "Q1 45, Q2 89"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["chart_type"] == "bar"
    assert payload["chart_data"]["labels"] == ["Q1", "Q2"]


def test_export_endpoint_json() -> None:
    client = create_test_client()
    response = client.post("/api/v1/export", json={"analysis_id": "analysis-1", "format": "json"})
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('analysis-1.json"')


def test_export_endpoint_csv() -> None:
    client = create_test_client()
    response = client.post("/api/v1/export", json={"analysis_id": "analysis-1", "format": "csv"})
    assert response.status_code == 200
    assert response.text.startswith("summary,chart_type,label,value")
