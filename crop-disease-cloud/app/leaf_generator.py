"""
Synthetic leaf image generator.

Draws a green leaf on a neutral background and paints class-specific lesions
on it. Used to (1) create the demo dataset, (2) train the model out of the box
and (3) give the web UI "try a sample" buttons - so the project works without
downloading any external dataset.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SIZE = 192

BACKGROUNDS = [(200, 200, 205), (185, 190, 200), (208, 200, 186),
               (172, 176, 182), (215, 212, 205), (190, 198, 188)]


def _jit(rng, color, spread):
    return tuple(int(np.clip(c + rng.normal(0, spread), 0, 255)) for c in color)


def _leaf_polygon(rng):
    a = rng.uniform(62, 74)          # half length
    b = rng.uniform(34, 46)          # half width
    ang = rng.uniform(0, 2 * math.pi)
    cx = SIZE / 2 + rng.uniform(-6, 6)
    cy = SIZE / 2 + rng.uniform(-6, 6)
    pts = []
    for t in np.linspace(0, 2 * math.pi, 90, endpoint=False):
        x = a * math.cos(t)
        y = b * math.sin(t) * (1 - 0.35 * math.cos(t))  # pointed tip, rounded base
        pts.append((cx + x * math.cos(ang) - y * math.sin(ang),
                    cy + x * math.sin(ang) + y * math.cos(ang)))
    return pts, (cx, cy), ang, a


def _random_point_in_leaf(rng, center, ang, a, b_scale=0.55, edge_bias=False):
    cx, cy = center
    r = rng.uniform(0.55, 0.95) if edge_bias else math.sqrt(rng.uniform(0, 0.8))
    t = rng.uniform(0, 2 * math.pi)
    x = a * 0.85 * r * math.cos(t)
    y = a * b_scale * 0.62 * r * math.sin(t)
    return (cx + x * math.cos(ang) - y * math.sin(ang),
            cy + x * math.sin(ang) + y * math.cos(ang))


def _blob(draw, rng, pt, radius, color, wobble=0.35, parts=4):
    for _ in range(parts):
        dx = rng.normal(0, radius * wobble)
        dy = rng.normal(0, radius * wobble)
        r = radius * rng.uniform(0.6, 1.0)
        draw.ellipse([pt[0] + dx - r, pt[1] + dy - r, pt[0] + dx + r, pt[1] + dy + r], fill=color)


def generate_leaf(label: str, seed: int | None = None) -> Image.Image:
    rng = np.random.default_rng(seed)

    bg = _jit(rng, BACKGROUNDS[rng.integers(len(BACKGROUNDS))], 4)
    img = Image.new("RGB", (SIZE, SIZE), bg)

    poly, center, ang, a = _leaf_polygon(rng)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    # leaf body with a soft lighting gradient
    base = (int(rng.integers(38, 66)), int(rng.integers(118, 152)), int(rng.integers(38, 62)))
    leaf = Image.new("RGB", (SIZE, SIZE), base)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    grad = 1.0 + 0.18 * np.cos((xx - center[0]) / 55.0) * np.cos((yy - center[1]) / 55.0)
    arr = np.clip(np.asarray(leaf, dtype=np.float32) * grad[..., None], 0, 255).astype(np.uint8)
    leaf = Image.fromarray(arr)

    d = ImageDraw.Draw(leaf)
    # midrib + side veins
    tip = (center[0] + a * math.cos(ang), center[1] + a * math.sin(ang))
    base_pt = (center[0] - a * math.cos(ang), center[1] - a * math.sin(ang))
    vein = tuple(min(255, c + 35) for c in base)
    d.line([base_pt, tip], fill=vein, width=2)
    for f in np.linspace(0.15, 0.85, 6):
        px = base_pt[0] + (tip[0] - base_pt[0]) * f
        py = base_pt[1] + (tip[1] - base_pt[1]) * f
        for s in (-1, 1):
            ex = px + s * 30 * math.cos(ang + math.pi / 2 - s * 0.6)
            ey = py + s * 30 * math.sin(ang + math.pi / 2 - s * 0.6)
            d.line([(px, py), (ex, ey)], fill=vein, width=1)

    # lesions --------------------------------------------------------------
    layer = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    lmask = Image.new("L", (SIZE, SIZE), 0)
    ld, lm = ImageDraw.Draw(layer), ImageDraw.Draw(lmask)

    def paint(pt, radius, color, alpha=255, parts=4, wobble=0.35):
        _blob(ld, rng, pt, radius, color, wobble, parts)
        _blob(lm, rng, pt, radius, alpha, wobble, parts)

    if label == "early_blight":
        for _ in range(int(rng.integers(6, 13))):
            pt = _random_point_in_leaf(rng, center, ang, a)
            r = rng.uniform(6, 13)
            paint(pt, r, _jit(rng, (126, 80, 34), 8), parts=2, wobble=0.15)
            paint(pt, r * 0.55, _jit(rng, (96, 60, 28), 6), parts=1, wobble=0.0)
    elif label == "late_blight":
        for _ in range(int(rng.integers(2, 5))):
            pt = _random_point_in_leaf(rng, center, ang, a, edge_bias=True)
            paint(pt, rng.uniform(18, 30), _jit(rng, (46, 36, 30), 7), parts=6, wobble=0.5)
    elif label == "leaf_rust":
        for _ in range(int(rng.integers(45, 95))):
            pt = _random_point_in_leaf(rng, center, ang, a)
            paint(pt, rng.uniform(1.6, 3.6), _jit(rng, (216, 120, 30), 9), parts=1, wobble=0.0)
    elif label == "powdery_mildew":
        for _ in range(int(rng.integers(3, 7))):
            pt = _random_point_in_leaf(rng, center, ang, a)
            paint(pt, rng.uniform(13, 24), _jit(rng, (238, 238, 232), 5), alpha=225, parts=5, wobble=0.5)
    elif label == "mosaic_virus":
        for _ in range(int(rng.integers(7, 14))):
            pt = _random_point_in_leaf(rng, center, ang, a)
            paint(pt, rng.uniform(9, 20), _jit(rng, (202, 216, 86), 10), alpha=235, parts=4, wobble=0.45)
    elif label != "healthy":
        raise ValueError(f"unknown class: {label}")

    lmask = lmask.filter(ImageFilter.GaussianBlur(0.9))
    leaf.paste(layer, (0, 0), lmask)

    img.paste(leaf, (0, 0), mask)
    img = img.filter(ImageFilter.GaussianBlur(0.6))

    arr = np.asarray(img, dtype=np.float32) + rng.normal(0, 4.0, (SIZE, SIZE, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
