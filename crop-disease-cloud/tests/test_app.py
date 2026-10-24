"""Run with:  python -m unittest discover -s tests -v   (from the project root)"""
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from app import create_app  # noqa: E402
from detector import CLASSES  # noqa: E402
from leaf_generator import generate_leaf  # noqa: E402


def jpeg_bytes(label, seed):
    buf = io.BytesIO()
    generate_leaf(label, seed=seed).save(buf, "JPEG", quality=92)
    return buf.getvalue()


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.client = create_app({"TESTING": True, "DATA_DIR": cls.tmp.name}).test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["status"], "ok")
        self.assertIn("X-Served-By", r.headers)

    def test_predict_each_class(self):
        correct = 0
        for i, label in enumerate(CLASSES):
            r = self.client.post("/api/predict", data={"image": (io.BytesIO(jpeg_bytes(label, 777_000 + i)), "leaf.jpg")},
                                 content_type="multipart/form-data")
            self.assertEqual(r.status_code, 200, r.json)
            correct += r.json["label"] == label
            self.assertAlmostEqual(sum(r.json["probabilities"].values()), 1.0, places=2)
        self.assertGreaterEqual(correct, len(CLASSES) - 1)

    def test_rejects_missing_and_bad_files(self):
        self.assertEqual(self.client.post("/api/predict").status_code, 400)
        r = self.client.post("/api/predict", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/predict", data={"image": (io.BytesIO(b"hi"), "x.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_history_stats_and_upload_serving(self):
        r = self.client.post("/api/predict", data={"image": (io.BytesIO(jpeg_bytes("leaf_rust", 5)), "a.jpg")},
                             content_type="multipart/form-data")
        self.assertEqual(self.client.get(r.json["image_url"]).status_code, 200)
        self.assertGreaterEqual(len(self.client.get("/api/history").json), 1)
        self.assertGreaterEqual(self.client.get("/api/stats").json["total_scans"], 1)

    def test_path_traversal_blocked(self):
        self.assertEqual(self.client.get("/uploads/..%2Fscans.db").status_code, 404)

    def test_sample_endpoint(self):
        r = self.client.get("/api/sample/late_blight?seed=3")
        self.assertEqual(r.mimetype, "image/jpeg")
        self.assertEqual(self.client.get("/api/sample/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
