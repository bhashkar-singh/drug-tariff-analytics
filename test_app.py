import base64
import io

import pipeline
import app as webapp


def test_health_and_public_dashboard():
    client = webapp.app.test_client()
    assert client.get("/healthz").status_code == 200
    response = client.get("/api/data")
    assert response.status_code == 200
    assert "products" in response.get_json()


def test_admin_requires_basic_auth(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    client = webapp.app.test_client()
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-password").decode()}).status_code == 200


def test_csv_export_has_header():
    response = webapp.app.test_client().get("/api/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert response.get_data(as_text=True).startswith(
        "product,pack_size,month,price_gbp,category,concession,in_portfolio"
    )


def test_admin_upload_processes_file_with_title_row(tmp_path, monkeypatch):
    data = tmp_path / "data"
    raw = data / "raw"
    raw.mkdir(parents=True)
    monkeypatch.setattr(pipeline, "DATA", data)
    monkeypatch.setattr(pipeline, "RAW", raw)
    monkeypatch.setattr(pipeline, "DB", data / "tariff.db")
    monkeypatch.setattr(pipeline, "OUT", data / "dashboard.json")
    monkeypatch.setattr(pipeline, "PORTFOLIO", data / "portfolio.txt")
    monkeypatch.setattr(webapp, "ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")

    contents = (
        "Category M Prices - October 2026,,,,\n"
        "Drug Name,Pack Size,Basic Price\n"
        "Example medicine 10mg tablets,28,125.00\n"
    ).encode()
    response = webapp.app.test_client().post(
        "/admin/upload",
        data={
            "token": "test-token",
            "kind": "drug_tariff",
            "month": "2026-10",
            "file": (io.BytesIO(contents), "tariff.csv"),
        },
        headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-password").decode()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True
    assert (data / "dashboard.json").exists()
