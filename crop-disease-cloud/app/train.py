"""
Train the crop-disease model and save model/model.json.

Usage (from the project root):
    python app/train.py                       # synthetic data generated in memory
    python app/train.py --save-dataset        # also write dataset/train + dataset/test images
    python app/train.py --data path/to/dir    # real photos: one sub-folder per class
                                              #   (e.g. PlantVillage-style folders)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from detector import CLASSES, CropDiseaseModel, extract_features, load_image  # noqa: E402
from leaf_generator import generate_leaf  # noqa: E402

MODEL_PATH = ROOT / "model" / "model.json"
METRICS_PATH = ROOT / "model" / "metrics.json"
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def synth(n_per_class: int, seed0: int, save_dir: Path | None = None):
    X, y = [], []
    for ci, c in enumerate(CLASSES):
        if save_dir:
            (save_dir / c).mkdir(parents=True, exist_ok=True)
        for i in range(n_per_class):
            img = generate_leaf(c, seed=seed0 + ci * 10_000 + i)
            if save_dir:
                img.save(save_dir / c / f"{c}_{i:03d}.jpg", quality=90)
            X.append(extract_features(img)[0])
            y.append(c)
    return np.array(X), y


def from_folder(folder: Path, limit: int | None = None):
    X, y = [], []
    for cdir in sorted(p for p in folder.iterdir() if p.is_dir()):
        files = [f for f in sorted(cdir.iterdir()) if f.suffix.lower() in EXTS]
        for f in files[:limit]:
            try:
                X.append(extract_features(load_image(f))[0])
                y.append(cdir.name)
            except Exception as exc:  # corrupt image
                print(f"  skipped {f.name}: {exc}")
    if not X:
        raise SystemExit(f"No images found under {folder}")
    return np.array(X), y


def confusion(model, X, y):
    idx = {c: i for i, c in enumerate(model.classes)}
    m = np.zeros((len(model.classes),) * 2, dtype=int)
    for xi, yi in zip(X, y):
        pred = int(np.argmax(model.predict_proba_vec(xi)))
        m[idx[yi], pred] += 1
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, help="folder with one sub-folder per class (real images)")
    ap.add_argument("--train-per-class", type=int, default=60)
    ap.add_argument("--test-per-class", type=int, default=20)
    ap.add_argument("--save-dataset", action="store_true", help="write the synthetic images to dataset/")
    ap.add_argument("--limit", type=int, default=None, help="max images per class when using --data")
    a = ap.parse_args(argv)

    t0 = time.time()
    if a.data:
        print(f"Loading real images from {a.data} ...")
        X, y = from_folder(a.data, a.limit)
        rng = np.random.default_rng(0)
        order = rng.permutation(len(X))
        cut = int(len(X) * 0.8)
        Xtr, ytr = X[order[:cut]], [y[i] for i in order[:cut]]
        Xte, yte = X[order[cut:]], [y[i] for i in order[cut:]]
        source = f"folder:{a.data}"
    else:
        ds = ROOT / "dataset"
        if a.save_dataset:
            print("Generating synthetic dataset and saving images to dataset/ ...")
            Xtr, ytr = synth(a.train_per_class, 1, ds / "train")
            Xte, yte = synth(a.test_per_class, 900_000, ds / "test")
        else:
            print("Generating synthetic leaf images in memory ...")
            Xtr, ytr = synth(a.train_per_class, 1)
            Xte, yte = synth(a.test_per_class, 900_000)
        source = "synthetic"

    model = CropDiseaseModel().fit(Xtr, ytr)
    model.meta = {"source": source, "train_images": len(ytr), "test_images": len(yte)}

    cm = confusion(model, Xte, yte)
    acc = float(np.trace(cm) / cm.sum())
    per_class = {c: round(float(cm[i, i] / max(cm[i].sum(), 1)), 3) for i, c in enumerate(model.classes)}

    model.save(MODEL_PATH)
    METRICS_PATH.write_text(json.dumps({
        "accuracy": round(acc, 4),
        "per_class_recall": per_class,
        "classes": model.classes,
        "confusion_matrix": cm.tolist(),
        "source": source,
        "train_images": len(ytr),
        "test_images": len(yte),
    }, indent=2))

    print(f"\nTrained on {len(ytr)} images, tested on {len(yte)} images in {time.time() - t0:.1f}s")
    print(f"Test accuracy: {acc * 100:.1f}%\n")
    width = max(len(c) for c in model.classes) + 2
    print(" " * width + "".join(f"{c[:6]:>8}" for c in model.classes))
    for c, row in zip(model.classes, cm):
        print(f"{c:<{width}}" + "".join(f"{v:>8}" for v in row))
    print(f"\nModel saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
