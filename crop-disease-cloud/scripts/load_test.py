"""
Simple load test for the deployed service - shows scalability and load balancing.

    python scripts/load_test.py                       # 60 requests, 8 threads, http://localhost:5000
    python scripts/load_test.py --url http://localhost:8080 --requests 200 --threads 16

With `docker compose up --scale api=3` the "served by" table shows requests
being spread across the three containers by the nginx load balancer.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CLASSES = ["healthy", "early_blight", "late_blight", "leaf_rust", "powdery_mildew", "mosaic_virus"]


def fetch_sample(base: str, label: str, seed: int) -> bytes:
    with urllib.request.urlopen(f"{base}/api/sample/{label}?seed={seed}", timeout=30) as r:
        return r.read()


def multipart(field: str, filename: str, data: bytes):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def one_request(base: str, label: str, img: bytes):
    body, ctype = multipart("image", f"{label}.jpg", img)
    req = urllib.request.Request(f"{base}/api/predict", data=body, headers={"Content-Type": ctype})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            return (time.perf_counter() - t0) * 1000, r.headers.get("X-Served-By", "?"), data["label"] == label, None
    except Exception as exc:
        return (time.perf_counter() - t0) * 1000, "-", False, str(exc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5000")
    ap.add_argument("--requests", type=int, default=60)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    base = a.url.rstrip("/")

    print(f"Preparing {len(CLASSES)} sample images from {base} ...")
    samples = {c: fetch_sample(base, c, 424_242) for c in CLASSES}
    jobs = [CLASSES[i % len(CLASSES)] for i in range(a.requests)]

    print(f"Sending {a.requests} requests with {a.threads} concurrent clients ...")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        results = list(ex.map(lambda c: one_request(base, c, samples[c]), jobs))
    wall = time.perf_counter() - t0

    lat = sorted(r[0] for r in results if r[3] is None)
    errors = [r[3] for r in results if r[3] is not None]
    if not lat:
        raise SystemExit(f"All requests failed: {errors[:3]}")
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    print("\n--- Results ---")
    print(f"Successful      : {len(lat)}/{a.requests}   errors: {len(errors)}")
    print(f"Total time      : {wall:.2f} s   throughput: {len(lat) / wall:.1f} req/s")
    print(f"Latency (ms)    : avg {statistics.mean(lat):.0f} | median {statistics.median(lat):.0f} | p95 {p95:.0f} | max {lat[-1]:.0f}")
    print(f"Correct labels  : {sum(r[2] for r in results)}/{a.requests}")
    print("Served by       :")
    for node, n in Counter(r[1] for r in results if r[3] is None).most_common():
        print(f"   {node:<20} {n:>4} requests")


if __name__ == "__main__":
    main()
