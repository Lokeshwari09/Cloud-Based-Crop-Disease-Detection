"""
Crop disease detector.

A lightweight, dependency-free (NumPy + Pillow) image classifier:

    leaf image -> colour / lesion-pattern features -> Gaussian Naive Bayes

It is deliberately small so the whole project runs on a laptop, in a Docker
container or on a t2/t3.micro EC2 instance without a GPU or TensorFlow.
The model is stored as a plain JSON file (model/model.json).
"""
from __future__ import annotations

import io
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

IMG_SIZE = 128
GRID = 32  # lesion map resolution used for connected-component statistics

CLASSES = [
    "healthy",
    "early_blight",
    "late_blight",
    "leaf_rust",
    "powdery_mildew",
    "mosaic_virus",
]

DISPLAY_NAMES = {
    "healthy": "Healthy Leaf",
    "early_blight": "Early Blight",
    "late_blight": "Late Blight",
    "leaf_rust": "Leaf Rust",
    "powdery_mildew": "Powdery Mildew",
    "mosaic_virus": "Mosaic Virus",
}

ADVICE = {
    "healthy": {
        "cause": "No visible disease symptoms.",
        "treatment": [
            "Keep the current irrigation and fertiliser schedule.",
            "Scout the field weekly and upload new photos if spots appear.",
        ],
    },
    "early_blight": {
        "cause": "Fungus (Alternaria solani) - brown spots with concentric rings.",
        "treatment": [
            "Remove and destroy infected lower leaves.",
            "Apply a copper-based or mancozeb fungicide as per label.",
            "Rotate crops and avoid overhead irrigation.",
        ],
    },
    "late_blight": {
        "cause": "Oomycete (Phytophthora infestans) - large dark, water-soaked blotches.",
        "treatment": [
            "Isolate and remove affected plants immediately - spreads fast in cool, wet weather.",
            "Spray a protectant fungicide (e.g. chlorothalonil) and improve air flow.",
            "Do not compost infected material.",
        ],
    },
    "leaf_rust": {
        "cause": "Rust fungus (Puccinia spp.) - small orange pustules on the leaf.",
        "treatment": [
            "Prune infected leaves and keep foliage dry.",
            "Use a triazole or sulphur-based fungicide at first sign.",
            "Plant rust-resistant varieties next season.",
        ],
    },
    "powdery_mildew": {
        "cause": "Fungus (Erysiphales) - white powdery patches on the surface.",
        "treatment": [
            "Increase spacing and sunlight exposure.",
            "Spray sulphur, potassium bicarbonate or neem oil.",
            "Avoid excess nitrogen fertiliser.",
        ],
    },
    "mosaic_virus": {
        "cause": "Plant virus (spread by aphids / whiteflies) - yellow-green mottling.",
        "treatment": [
            "There is no cure - uproot and destroy infected plants.",
            "Control aphids/whiteflies with neem oil or insecticidal soap.",
            "Disinfect tools and use virus-free seed.",
        ],
    },
}

FEATURE_NAMES = [
    "green", "yellow", "orange", "brown", "dark", "white", "other",
    "n_blobs", "largest_blob", "spread", "v_std", "s_mean",
]


# --------------------------------------------------------------------------
# Image loading + feature extraction
# --------------------------------------------------------------------------
def load_image(src) -> Image.Image:
    """Accepts a path, bytes or file-like object; returns an RGB PIL image."""
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    img = Image.open(src)
    img.load()
    return img.convert("RGB")


def _leaf_mask(rgb: np.ndarray) -> np.ndarray:
    """Background = pixels close to the median colour of the image border."""
    h, w, _ = rgb.shape
    b = max(3, h // 16)
    border = np.concatenate([
        rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
        rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3),
    ]).astype(np.float32)
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
    mask = dist > 38
    if mask.mean() < 0.05:  # nothing stands out -> use the whole frame
        mask = np.ones((h, w), dtype=bool)
    return mask


def _components(cell_mask: np.ndarray):
    """4-connected component sizes of a small boolean grid."""
    h, w = cell_mask.shape
    seen = np.zeros_like(cell_mask, dtype=bool)
    sizes = []
    for y in range(h):
        for x in range(w):
            if cell_mask[y, x] and not seen[y, x]:
                q = deque([(y, x)])
                seen[y, x] = True
                n = 0
                while q:
                    cy, cx = q.popleft()
                    n += 1
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < h and 0 <= nx < w and cell_mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
                sizes.append(n)
    return sizes


def extract_features(img: Image.Image) -> tuple[np.ndarray, float]:
    """Returns (feature_vector, severity_percent)."""
    img = img.resize((IMG_SIZE, IMG_SIZE), Image.BILINEAR)
    rgb = np.asarray(img, dtype=np.uint8)
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32)
    hue = hsv[..., 0] * (360.0 / 255.0)
    sat = hsv[..., 1] / 255.0
    val = hsv[..., 2] / 255.0

    leaf = _leaf_mask(rgb)
    n_leaf = max(int(leaf.sum()), 1)

    dark = val < 0.28
    white = (sat < 0.18) & (val > 0.78)
    yellow = (hue >= 45) & (hue < 72) & (sat >= 0.35) & (val >= 0.5)
    warm = (hue >= 5) & (hue < 45) & (sat >= 0.3)
    orange = warm & (val >= 0.62) & (sat >= 0.45)
    brown = warm & (val >= 0.28) & (val < 0.62)
    green = (hue >= 72) & (hue <= 170) & (sat >= 0.2) & (val >= 0.28)

    taken = np.zeros_like(leaf)
    fracs = {}
    for name, m in (("dark", dark), ("white", white), ("yellow", yellow),
                    ("orange", orange), ("brown", brown), ("green", green)):
        m = m & leaf & ~taken
        fracs[name] = m.sum() / n_leaf
        taken |= m
    fracs["other"] = max(0.0, 1.0 - sum(fracs.values()))

    lesion = leaf & ~green
    severity = float(100.0 * lesion.sum() / n_leaf)

    # lesion map on a coarse grid -> blob statistics
    cell = IMG_SIZE // GRID
    les = lesion[: GRID * cell, : GRID * cell].reshape(GRID, cell, GRID, cell).mean(axis=(1, 3))
    lf = leaf[: GRID * cell, : GRID * cell].reshape(GRID, cell, GRID, cell).mean(axis=(1, 3))
    cells = (les > 0.3) & (lf > 0.3)
    sizes = _components(cells)
    total_cells = max(int((lf > 0.3).sum()), 1)
    n_blobs = min(len(sizes), 60) / 60.0
    largest = (max(sizes) / total_cells) if sizes else 0.0
    spread = cells.sum() / total_cells

    v_std = float(val[leaf].std()) if leaf.any() else 0.0
    s_mean = float(sat[leaf].mean()) if leaf.any() else 0.0

    vec = np.array([
        fracs["green"], fracs["yellow"], fracs["orange"], fracs["brown"],
        fracs["dark"], fracs["white"], fracs["other"],
        n_blobs, largest, spread, v_std, s_mean,
    ], dtype=np.float64)
    return vec, severity


# --------------------------------------------------------------------------
# Gaussian Naive Bayes
# --------------------------------------------------------------------------
class CropDiseaseModel:
    def __init__(self, classes=None, mean=None, var=None, prior=None, meta=None):
        self.classes = list(classes or CLASSES)
        self.mean = np.asarray(mean) if mean is not None else None
        self.var = np.asarray(var) if var is not None else None
        self.prior = np.asarray(prior) if prior is not None else None
        self.meta = meta or {}

    # -- training --------------------------------------------------------
    def fit(self, X: np.ndarray, y: list[str]) -> "CropDiseaseModel":
        y = np.asarray(y)
        self.classes = [c for c in CLASSES if c in set(y)] + \
                       sorted(c for c in set(y) if c not in CLASSES)
        means, vars_, priors = [], [], []
        floor = 2e-3  # variance floor keeps the model from becoming over-confident
        for c in self.classes:
            Xc = X[y == c]
            means.append(Xc.mean(axis=0))
            vars_.append(Xc.var(axis=0) + floor)
            priors.append(len(Xc) / len(X))
        self.mean, self.var, self.prior = np.array(means), np.array(vars_), np.array(priors)
        return self

    # -- inference -------------------------------------------------------
    def predict_proba_vec(self, x: np.ndarray) -> np.ndarray:
        ll = -0.5 * (np.log(2 * np.pi * self.var) + (x - self.mean) ** 2 / self.var).sum(axis=1)
        ll = ll + np.log(self.prior)
        ll = ll / 6.0  # temperature: softens the very sharp Naive-Bayes posteriors
        ll -= ll.max()
        p = np.exp(ll)
        return p / p.sum()

    def predict_image(self, img: Image.Image) -> dict:
        vec, severity = extract_features(img)
        probs = self.predict_proba_vec(vec)
        k = int(np.argmax(probs))
        label = self.classes[k]
        return {
            "label": label,
            "display_name": DISPLAY_NAMES.get(label, label),
            "confidence": round(float(probs[k]), 4),
            "probabilities": {c: round(float(p), 4) for c, p in zip(self.classes, probs)},
            "severity_percent": round(severity, 1) if label != "healthy" else round(min(severity, 5.0), 1),
            "advice": ADVICE.get(label, {}),
        }

    # -- persistence -----------------------------------------------------
    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "classes": self.classes,
            "mean": self.mean.tolist(),
            "var": self.var.tolist(),
            "prior": self.prior.tolist(),
            "features": FEATURE_NAMES,
            "meta": self.meta,
        }, indent=2))

    @classmethod
    def load(cls, path) -> "CropDiseaseModel":
        d = json.loads(Path(path).read_text())
        return cls(d["classes"], d["mean"], d["var"], d["prior"], d.get("meta"))
