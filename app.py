
"""Drug Tariff Analytics website with a protected admin panel."""
import csv
import io
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

import pipeline
from sample import make_sample

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

WEB = Path(__file__).parent / "web"

# Keep the existing token protection for admin actions.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

SAMPLE = make_sample()


def live_data():
    return json.loads(pipeline.OUT.read_text()) if pipeline.OUT.exists() else None


def authorised() -> bool:
    supplied_token = request.form.get("token", "")
    return bool(ADMIN_TOKEN) and hmac.compare_digest(
        supplied_token, ADMIN_TOKEN
    )


def denied():
    if not ADMIN_TOKEN:
        msg = (
            "ADMIN_TOKEN is not set on the server, "
            "so admin actions are disabled."
        )
    else:
        msg = "Wrong or missing admin token."

    return jsonify(ok=False, message=msg), 403


# Require username and password for the admin page and
# every route under /admin/.
@app.before_request
def protect_admin_page():
    path = request.path

    if path != "/admin" and not path.startswith("/admin/"):
        return None

    username = os.environ.get("ADMIN_USERNAME", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    auth = request.authorization

    # Fail closed if credentials haven't been configured.
    if not username or not password:
        return "Admin authentication is not configured.", 503

    valid_user = (
        auth is not None
        and hmac.compare_digest(auth.username or "", username)
    )
    valid_password = (
        auth is not None
        and hmac.compare_digest(auth.password or "", password)
    )

    if not (valid_user and valid_password):
        return Response(
            "Login required.",
            status=401,
            headers={
                "WWW-Authenticate": 'Basic realm="Drug Tariff Admin"'
            },
        )

    return None


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


# Public dashboard
@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


# Protected admin page
@app.get("/admin")
def admin():
    return send_from_directory(WEB, "admin.html")


# Public health check for Render
@app.get("/healthz")
def healthz():
    return "ok"


# Public dashboard data API
@app.get("/api/data")
def api_data():
    live = live_data()

    if live:
        updated = datetime.fromtimestamp(
            pipeline.OUT.stat().st_mtime,
            timezone.utc,
        ).strftime("%d %b %Y %H:%M UTC")

        return jsonify({
            **live,
            "meta": {
                "source": "live",
                "updated": updated,
                "latest": live["months"][-1],
            },
        })

    return jsonify({
        **SAMPLE,
        "meta": {"source": "sample"},
    })


# Export the product history currently shown by the dashboard.
@app.get("/api/export.csv")
def export_csv():
    data = live_data() or SAMPLE
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["product", "pack_size", "month", "price_gbp", "category", "concession", "in_portfolio"])
    for product in data.get("products", []):
        months = data.get("months", [])
        prices = product.get("pr", [])
        categories = product.get("ct", [])
        concessions = product.get("cn", [])
        for index, month in enumerate(months):
            if index >= len(prices):
                continue
            writer.writerow([
                product.get("n", ""),
                product.get("pk", ""),
                month,
                prices[index],
                categories[index] if index < len(categories) else "",
                concessions[index] if index < len(concessions) else False,
                product.get("pf", False),
            ])
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="drug-tariff-history.csv"'},
    )


# Public status endpoint (does not reveal credentials)
@app.get("/api/status")
def api_status():
    live = live_data()
    files = (
        sorted(p.name for p in pipeline.RAW.glob("*"))
        if pipeline.RAW.exists()
        else []
    )

    return jsonify(
        source="live" if live else "sample",
        months=live["months"] if live else [],
        products=len((live or SAMPLE)["products"]),
        files=files,
        admin_enabled=bool(ADMIN_TOKEN),
    )


# Protected by admin login AND the existing admin token
@app.post("/admin/upload")
def upload():
    if not authorised():
        return denied()

    f = request.files.get("file")
    kind = request.form.get("kind")
    month = request.form.get("month", "")

    ext = (
        Path(secure_filename(f.filename or "")).suffix.lower()
        if f
        else ""
    )

    if (
        ext not in {".csv", ".xlsx"}
        or kind not in {"drug_tariff", "concessions"}
        or not re.fullmatch(r"\d{4}-\d{2}", month)
    ):
        return jsonify(
            ok=False,
            message="Choose a .csv or .xlsx file, a file type and a month.",
        ), 400

    pipeline.RAW.mkdir(parents=True, exist_ok=True)
    dest = pipeline.RAW / f"{kind}_{month}{ext}"
    backup = dest.read_bytes() if dest.exists() else None

    f.save(dest)

    try:
        info = pipeline.run()
    except Exception as e:
        # Restore the previous file if processing fails.
        dest.unlink(missing_ok=True)

        if backup is not None:
            dest.write_bytes(backup)

        app.logger.exception("Tariff file processing failed")

        return jsonify(
            ok=False,
            message=f"Could not process that file: {e}",
        ), 422

    return jsonify(
        ok=True,
        message=f"{dest.name} saved. {info}",
    )


# Protected by admin login AND the existing admin token
@app.post("/admin/portfolio")
def portfolio():
    if not authorised():
        return denied()

    terms = [
        term.strip()
        for term in request.form.get("terms", "")[:5000].splitlines()
        if term.strip()
    ]

    pipeline.PORTFOLIO.parent.mkdir(parents=True, exist_ok=True)
    pipeline.PORTFOLIO.write_text("\n".join(terms))

    try:
        note = pipeline.run()
    except FileNotFoundError:
        note = "It will apply once the first tariff file is uploaded."
    except Exception as e:
        app.logger.exception("Portfolio processing failed")

        return jsonify(
            ok=False,
            message=f"Saved, but processing failed: {e}",
        ), 422

    return jsonify(
        ok=True,
        message=f"Saved {len(terms)} portfolio entries. {note}",
    )


if __name__ == "__main__":
    app.run(
        debug=False,
        port=int(os.environ.get("PORT", 5000)),
    )