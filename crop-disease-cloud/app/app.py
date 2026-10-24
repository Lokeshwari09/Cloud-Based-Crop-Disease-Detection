"""
Cloud-Based Crop Disease Detection - Flask web service.

Run locally:   python app/app.py          ->  http://localhost:5000
Run in Docker: docker compose up --build  ->  http://localhost:8080
"""
from __future__ import annotations

import io
import os
import socket
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from database import Database  # noqa: E402
from detector import CLASSES, DISPLAY_NAMES, CropDiseaseModel, load_image  # noqa: E402
from leaf_generator import generate_leaf  # noqa: E402
from storage import get_storage  # noqa: E402

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
MODEL_PATH = Path(os.getenv("MODEL_PATH", ROOT / "model" / "model.json"))
INSTANCE_ID = os.getenv("INSTANCE_ID") or socket.gethostname()
ALLOWED = {"jpg", "jpeg", "png", "bmp", "webp"}


def load_model() -> CropDiseaseModel:
    if not MODEL_PATH.exists():
        print("model/model.json not found - training a model first (takes ~5 s) ...")
        import train
        train.main([])
    return CropDiseaseModel.load(MODEL_PATH)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
    if test_config:
        app.config.update(test_config)

    data_dir = Path(app.config.get("DATA_DIR", DATA_DIR))
    db = Database(data_dir / "scans.db")
    storage = get_storage(data_dir)
    model = load_model()
    started = time.time()

    @app.after_request
    def add_headers(resp):
        resp.headers["X-Served-By"] = INSTANCE_ID
        return resp

    # ------------------------------------------------------------------ UI
    @app.get("/")
    def index():
        return render_template("index.html", classes=[(c, DISPLAY_NAMES[c]) for c in CLASSES])

    # ----------------------------------------------------------------- API
    @app.get("/api/health")
    def health():
        return jsonify(status="ok", instance=INSTANCE_ID, storage=storage.kind,
                       uptime_s=round(time.time() - started, 1), classes=model.classes)

    @app.post("/api/predict")
    def predict():
        t0 = time.perf_counter()
        f = request.files.get("image")
        if f is None or f.filename == "":
            return jsonify(error="Send a leaf photo as multipart field 'image'."), 400
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED:
            return jsonify(error=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED))}"), 400

        raw = f.read()
        try:
            img = load_image(raw)
        except Exception:
            return jsonify(error="File is not a valid image."), 400

        result = model.predict_image(img)

        scan_id = uuid.uuid4().hex[:12]
        key = f"{scan_id}.jpg"
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        url = storage.save(key, buf.getvalue())

        latency = round((time.perf_counter() - t0) * 1000, 1)
        db.add_scan(id=scan_id, filename=f.filename[:120], image_key=key, label=result["label"],
                    confidence=result["confidence"], severity=result["severity_percent"],
                    latency_ms=latency, served_by=INSTANCE_ID)
        result.update(id=scan_id, image_url=url, latency_ms=latency, served_by=INSTANCE_ID,
                      storage=storage.kind)
        return jsonify(result)

    @app.get("/api/history")
    def history():
        limit = max(1, min(int(request.args.get("limit", 15)), 100))
        rows = db.history(limit)
        for r in rows:
            r["display_name"] = DISPLAY_NAMES.get(r["label"], r["label"])
            r["image_url"] = f"/uploads/{r['image_key']}"
        return jsonify(rows)

    @app.get("/api/stats")
    def stats():
        s = db.stats()
        s["instance"] = INSTANCE_ID
        s["storage"] = storage.kind
        return jsonify(s)

    @app.get("/api/sample/<label>")
    def sample(label: str):
        if label not in CLASSES:
            return jsonify(error="unknown class"), 404
        seed = int(request.args.get("seed", uuid.uuid4().int % 1_000_000))
        buf = io.BytesIO()
        generate_leaf(label, seed=seed).save(buf, "JPEG", quality=92)
        return Response(buf.getvalue(), mimetype="image/jpeg")

    @app.get("/uploads/<name>")
    def uploads(name: str):
        if not name.endswith(".jpg") or "/" in name or ".." in name:
            return jsonify(error="not found"), 404
        data = storage.read(name)
        if data is None:
            return jsonify(error="not found"), 404
        return Response(data, mimetype="image/jpeg")

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Image too large (max 8 MB)."), 413

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  Crop Disease Detection running on http://localhost:{port}  (instance: {INSTANCE_ID})\n")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
