# Cloud-Based Crop Disease Detection

A cloud-computing mini project: farmers upload a leaf photo, a containerised web service diagnoses the disease, stores the image in object storage, records the scan, and can be scaled behind a load balancer. A CloudSim-style simulation shows how many servers the service needs under a burst of uploads.

**Tools used:** Docker (+ Compose, nginx load balancer) - Oracle VirtualBox (guide) - AWS Console: EC2 + S3 + IAM (guide) - CloudSim-style simulation (Python)

---

## 1. Run it in VS Code (2 minutes, no Docker needed)

```bash
# open the project folder in VS Code, then in the integrated terminal:
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app/app.py
```
Open **http://localhost:5000**, click one of the sample-leaf buttons (or upload your own photo) and press *Analyze*.

Or press **F5** in VS Code and pick a launch configuration:

| # | Configuration | What it does |
|---|---|---|
| 1 | Run web app | Starts the service on port 5000 |
| 2 | Train model | Re-trains and writes `dataset/` images |
| 3 | CloudSim-style simulation | Prints the scenario table, saves CSV + chart to `results/` |
| 4 | Load test | Fires concurrent requests at the running server |
| 5 | Run unit tests | 6 API tests |

`model/model.json` is included; if you delete it the app trains a new one automatically on start (about 5 s).

## 2. Architecture

```
                         +-----------------------------------------------+
  Farmer (browser) --->  |  nginx load balancer  (port 8080)             |
                         +----------+------------------+-----------------+
                                    |                  |
                         +----------v--+  +------------v-+  +------------+
                         | api replica |  | api replica  |  | api replica|   Flask + gunicorn
                         |     #1      |  |     #2       |  |     #3     |   (Docker containers)
                         +------+------+  +------+-------+  +------+-----+
                                |                |                 |
                  +-------------v----------------v-----------------v---------+
                  |  Object storage: local volume  OR  Amazon S3 (USE_S3)    |
                  |  Scan history: SQLite (swap for RDS / DynamoDB on AWS)    |
                  +-----------------------------------------------------------+
```

| Cloud concept | Where it appears |
|---|---|
| IaaS | VirtualBox VM / AWS EC2 instance |
| Containers | `Dockerfile`, `docker-compose.yml` |
| SaaS | the web app itself |
| Object storage | `app/storage.py` -> local bucket or Amazon S3 |
| Load balancing | `nginx/nginx.conf` spreading requests over replicas |
| Horizontal scaling | `docker compose up --scale api=5` |
| Elasticity / cost | `cloudsim_sim/simulation.py` |
| Least-privilege security | IAM role limited to `s3:PutObject/GetObject` on one prefix |

## 3. Project structure

```
crop-disease-cloud/
|-- app/
|   |-- app.py             Flask service (UI + REST API)
|   |-- detector.py        feature extraction + Gaussian Naive Bayes classifier
|   |-- leaf_generator.py  synthetic leaf images (dataset + UI samples)
|   |-- train.py           training / evaluation script
|   |-- storage.py         local bucket or Amazon S3
|   `-- database.py        SQLite scan history
|-- templates/ static/     web interface
|-- model/                 model.json, metrics.json (accuracy + confusion matrix)
|-- dataset/               train/ (360) and test/ (120) sample leaf images, 6 classes
|-- cloudsim_sim/simulation.py   CloudSim-style experiments
|-- scripts/load_test.py   concurrent load test
|-- tests/test_app.py      unit tests
|-- results/               simulation CSV + chart
|-- nginx/nginx.conf  Dockerfile  docker-compose.yml  .env.example
|-- docs/AWS_DEPLOYMENT.md   docs/VIRTUALBOX_GUIDE.md
`-- .vscode/               launch / tasks / extension recommendations
```

## 4. REST API

| Method | Path | Description |
|---|---|---|
| POST | `/api/predict` | multipart field `image` -> diagnosis JSON (label, confidence, severity %, advice, serving node) |
| GET | `/api/history?limit=15` | recent scans |
| GET | `/api/stats` | totals, average latency, scans per class and per node |
| GET | `/api/health` | liveness check (used by Docker health check / load balancer) |
| GET | `/api/sample/<class>` | generated sample leaf JPEG |
| GET | `/uploads/<file>` | stored image (served from local volume or S3) |

```bash
curl -F "image=@leaf.jpg" http://localhost:5000/api/predict
```

## 5. How the detector works (and its limits)

Classes: healthy, early blight, late blight, leaf rust, powdery mildew, mosaic virus.

1. Resize to 128x128 and separate leaf from background (colour distance from the image border).
2. Measure colour fractions in HSV (green, yellow, orange, brown, dark, white), the number and size of lesion blobs, spread and texture - 12 features.
3. A Gaussian Naive Bayes model (NumPy only, stored as JSON) outputs class probabilities; severity = % of leaf area that is not healthy green.

**Be upfront about this in your report/viva:** the bundled model is trained on *synthetically generated* leaf images, so the 98.3% test accuracy (118/120 held-out synthetic images; both errors were powdery mildew predicted as leaf rust) only shows the pipeline works - it is **not** a measure of accuracy on real field photos. A colour/blob feature model will be noticeably weaker on real photos with varied lighting and backgrounds.

To use real data (e.g. the PlantVillage dataset, one sub-folder per class, folder names become labels):
```bash
python app/train.py --data path/to/PlantVillage-subset
```
For a production-grade detector, replace `detector.py` with a CNN (e.g. MobileNetV2 transfer learning); the cloud parts (API, storage, Docker, scaling) stay unchanged.

## 6. Docker (load-balanced replicas)

```bash
docker compose up --build              # 3 api replicas + nginx -> http://localhost:8080
docker compose up --build --scale api=5
python scripts/load_test.py --url http://localhost:8080 --requests 200 --threads 16
docker compose down                    # add -v to delete stored scans/uploads
```
The load-test output lists how many requests each container served, which demonstrates load balancing.
> The Docker files passed `docker compose config` validation, but the containers were not built or run while preparing this project (no Docker daemon was available). If the build fails on your machine, the plain-Python run in section 1 is unaffected.

## 7. VirtualBox and AWS

- `docs/VIRTUALBOX_GUIDE.md` - Ubuntu VM with port forwarding, Docker inside the VM.
- `docs/AWS_DEPLOYMENT.md` - S3 bucket, IAM role, EC2 + Docker, optional ALB / Auto Scaling / CloudWatch.

Both are step-by-step guides written for the Console workflow; they were not executed during preparation.

## 8. CloudSim-style simulation

`python cloudsim_sim/simulation.py` simulates one datacenter (4 hosts x 8 PEs) receiving 1,093 image-analysis cloudlets in 120 s, with a burst of 22 req/s between t=40 s and 70 s (5 req/s otherwise). SLA target: 2 s per request. Cost uses an illustrative $0.0416/VM-hour.

| Scenario | Avg response | SLA violations | VM-seconds | Cost (2-min run) |
|---|---|---|---|---|
| A: 2 VMs, round-robin | 27.17 s | 80.8% | 319 | $0.0037 |
| B: 4 VMs, round-robin | 4.32 s | 55.2% | 479 | $0.0055 |
| C: 4 VMs, least-loaded | 4.28 s | 55.9% | 479 | $0.0055 |
| D: 7 VMs fixed (sized for peak) | 0.28 s | 0.0% | 839 | $0.0097 |
| E: auto-scaling from 2 VMs (max 12) | 3.59 s | 57.1% | 718 | $0.0083 |
| F: auto-scaling from 4 VMs (max 12) | 1.09 s | 25.3% | 738 | $0.0085 |

What it shows:
- Too few VMs (A) collapses under the burst; the scheduling policy (B vs C) matters little compared with capacity.
- Sizing for the peak (D) meets the SLA but pays for idle VMs outside the burst (34% average utilisation).
- Reactive auto-scaling (E) is cheaper than D but **does not meet the SLA here**: a new VM needs 10 s to boot, which is long compared with a 30 s burst. Keeping a larger warm pool (F) helps a lot but still misses the SLA for a quarter of requests. Faster scaling triggers, predictive/scheduled scaling or a higher minimum would be the next steps.

The classes map to CloudSim as: `Datacenter`, `Host`, `Vm` (+ first-fit allocation), `Cloudlet`, `Broker`, per-VM FCFS queues (like `CloudletSchedulerSpaceShared`). This is a **Python re-implementation of CloudSim's concepts, not the Java CloudSim toolkit itself** - if your course specifically requires the Java library, the same scenarios can be ported. All parameters (VM size, workload, prices) are illustrative assumptions.

## 9. Tests

```bash
python -m unittest discover -s tests -v
```
Covers health, prediction for every class, input validation (missing/invalid/wrong-type files), history/stats, image serving, path-traversal protection.

## 10. Likely viva questions

- *Why containers instead of only VMs?* Faster start, smaller footprint, identical environment on laptop / VirtualBox / EC2.
- *How does the system scale?* Stateless API replicas behind nginx; state is in shared storage (S3) and a database (RDS/DynamoDB in production) - see section 2.
- *Why an IAM role instead of access keys?* No long-lived secrets on the server; permissions limited to one bucket prefix.
- *What are SQLite's limits here?* Fine for the demo on one host; for multi-server deployments use a managed database.
- *What does CloudSim give you that AWS doesn't?* Repeatable what-if experiments (capacity, policies, cost) without paying for or provisioning real machines.
- *What is the weakness of the detector?* See section 5 - trained on synthetic images; needs real data or a CNN for field use.

## Troubleshooting

- `ModuleNotFoundError: flask` - activate the virtual environment and run `pip install -r requirements.txt`.
- Port 5000 busy (common on macOS) - `set PORT=5001` (Windows) / `PORT=5001 python app/app.py` and open that port.
- Charts missing from the simulation - `pip install matplotlib` (the table still prints without it).
