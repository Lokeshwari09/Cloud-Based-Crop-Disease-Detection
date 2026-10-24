"""
CloudSim-style simulation of the Crop Disease Detection service.

This is a small Python re-implementation of the core CloudSim concepts so it
runs straight from VS Code (no Java / Maven needed):

    CloudSim (Java)              this file
    -------------------------    ---------------------------
    Datacenter                   Datacenter
    Host (PEs, MIPS, RAM)        Host
    Vm + VmAllocationPolicy      Vm + first-fit allocation
    Cloudlet                     Cloudlet  (= one leaf-image analysis request)
    DatacenterBroker             Broker    (round-robin / least-loaded / auto-scaling)
    CloudletSchedulerSpaceShared per-VM FCFS queue

The scenarios compare how many VMs and which scheduling policy cope with a
farm workload that has a burst (many farmers uploading photos after a storm).

Run:  python cloudsim_sim/simulation.py
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "results"

VM_PRICE_PER_HOUR = 0.0416   # illustrative on-demand price of a 2 vCPU / 4 GB instance (USD)
SLA_SECONDS = 2.0            # target response time per request
VM_BOOT_SECONDS = 10.0       # delay before a newly created VM can accept work
SCALE_IN_IDLE = 15.0         # an auto-scaled VM idle this long is shut down
MAX_BOOTING = 3              # scale-out adds at most this many VMs at a time


# ------------------------------------------------------------------ entities
@dataclass
class Host:
    id: int
    pes: int = 8
    mips: int = 2000
    ram: int = 16384
    used_pes: int = 0
    used_ram: int = 0

    def fits(self, vm: "Vm") -> bool:
        return self.pes - self.used_pes >= vm.pes and self.ram - self.used_ram >= vm.ram


@dataclass
class Vm:
    id: int
    mips: int = 1000
    pes: int = 2
    ram: int = 4096
    created_at: float = 0.0
    ready_at: float = 0.0          # when boot finishes
    available_at: float = 0.0      # when its queue drains
    retired_at: float | None = None
    host_id: int = -1
    busy_time: float = 0.0
    jobs: int = 0

    @property
    def capacity(self) -> float:   # MI per second
        return self.mips * self.pes


@dataclass
class Cloudlet:
    id: int
    arrival: float
    length: float                  # million instructions (MI)
    vm_id: int = -1
    start: float = 0.0
    finish: float = 0.0

    @property
    def response(self) -> float:
        return self.finish - self.arrival


@dataclass
class Datacenter:
    id: int
    hosts: list[Host] = field(default_factory=list)

    def allocate(self, vm: Vm) -> bool:
        for h in self.hosts:       # first-fit VmAllocationPolicy
            if h.fits(vm):
                h.used_pes += vm.pes
                h.used_ram += vm.ram
                vm.host_id = h.id
                return True
        return False

    def release(self, vm: Vm) -> None:
        h = self.hosts[vm.host_id]
        h.used_pes -= vm.pes
        h.used_ram -= vm.ram


# ------------------------------------------------------------------- broker
class Broker:
    def __init__(self, dc: Datacenter, policy: str, initial_vms: int,
                 autoscale: bool = False, max_vms: int = 12, wait_threshold: float = 1.0):
        self.dc, self.policy = dc, policy
        self.autoscale, self.max_vms, self.wait_threshold = autoscale, max_vms, wait_threshold
        self.min_vms = initial_vms
        self.all_vms: list[Vm] = []    # every VM ever created (for billing)
        self.vms: list[Vm] = []        # currently active VMs
        self._rr = 0
        for _ in range(initial_vms):
            self._create_vm(0.0, boot=0.0)

    def _create_vm(self, now: float, boot: float = VM_BOOT_SECONDS) -> Vm | None:
        vm = Vm(id=len(self.all_vms), created_at=now, ready_at=now + boot, available_at=now + boot)
        if not self.dc.allocate(vm):
            return None            # datacenter is full
        self.all_vms.append(vm)
        self.vms.append(vm)
        return vm

    def _finish_time(self, vm: Vm, c: Cloudlet):
        start = max(c.arrival, vm.available_at)
        return start, start + c.length / vm.capacity

    def _scale_in(self, now: float) -> None:
        for vm in list(self.vms):
            if len(self.vms) > self.min_vms and vm.available_at + SCALE_IN_IDLE <= now and vm.ready_at <= now:
                vm.retired_at = vm.available_at + SCALE_IN_IDLE
                self.vms.remove(vm)
                self.dc.release(vm)

    def submit(self, c: Cloudlet) -> None:
        now = c.arrival
        if self.autoscale:
            self._scale_in(now)

        if self.policy == "round_robin":
            vm = self.vms[self._rr % len(self.vms)]
            self._rr += 1
        else:                       # least_loaded = earliest finish time
            vm = min(self.vms, key=lambda v: self._finish_time(v, c)[1])

        start, finish = self._finish_time(vm, c)

        # scale out when requests are already waiting too long
        if self.autoscale and (start - now) > self.wait_threshold and len(self.vms) < self.max_vms:
            booting = sum(1 for v in self.vms if v.ready_at > now)
            if booting < MAX_BOOTING:
                self._create_vm(now)

        c.vm_id, c.start, c.finish = vm.id, start, finish
        vm.available_at = finish
        vm.busy_time += finish - start
        vm.jobs += 1


# ----------------------------------------------------------------- workload
def make_workload(seed: int = 42, duration: float = 120.0) -> list[Cloudlet]:
    """Poisson arrivals: 5 req/s normally, 22 req/s burst between t=40 s and t=70 s."""
    rng = np.random.default_rng(seed)
    t, cid, out = 0.0, 0, []
    while True:
        rate = 22.0 if 40 <= t < 70 else 5.0
        t += rng.exponential(1.0 / rate)
        if t >= duration:
            break
        length = float(np.clip(rng.lognormal(mean=np.log(500), sigma=0.35), 150, 2500))
        out.append(Cloudlet(id=cid, arrival=t, length=length))
        cid += 1
    return out


# -------------------------------------------------------------- experiments
def run(name, policy, vms, autoscale=False, seed=42):
    dc = Datacenter(0, [Host(i) for i in range(4)])      # 4 hosts x 8 PEs
    broker = Broker(dc, policy, vms, autoscale=autoscale)
    cloudlets = make_workload(seed)
    for c in cloudlets:                                  # already sorted by arrival
        broker.submit(c)

    resp = [c.response for c in cloudlets]
    makespan = max(c.finish for c in cloudlets)
    vm_seconds = sum((v.retired_at if v.retired_at is not None else makespan) - v.created_at
                     for v in broker.all_vms)
    util = statistics.mean(
        v.busy_time / max((v.retired_at if v.retired_at is not None else makespan) - v.ready_at, 1e-9)
        for v in broker.all_vms)
    return {
        "scenario": name,
        "vms_start": vms,
        "vms_created": len(broker.all_vms),
        "requests": len(cloudlets),
        "avg_response_s": round(statistics.mean(resp), 2),
        "p95_response_s": round(float(np.percentile(resp, 95)), 2),
        "max_response_s": round(max(resp), 2),
        "sla_violations_pct": round(100 * sum(r > SLA_SECONDS for r in resp) / len(resp), 1),
        "makespan_s": round(makespan, 1),
        "avg_vm_util_pct": round(100 * min(util, 1.0), 1),
        "vm_seconds": round(vm_seconds, 0),
        "cost_usd": round(vm_seconds / 3600 * VM_PRICE_PER_HOUR, 4),
    }, cloudlets, broker


def print_cloudsim_style(cloudlets, n=10):
    print("\n========== OUTPUT (first %d cloudlets of last scenario, CloudSim format) ==========" % n)
    print(f"{'Cloudlet ID':>11}  {'STATUS':<8}{'DC ID':>6}{'VM ID':>7}{'Time':>9}{'Start':>10}{'Finish':>10}")
    for c in cloudlets[:n]:
        print(f"{c.id:>11}  {'SUCCESS':<8}{2:>6}{c.vm_id:>7}{c.finish - c.start:>9.2f}{c.start:>10.2f}{c.finish:>10.2f}")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    scenarios = [
        ("A: 2 VMs, round-robin",            "round_robin", 2, False),
        ("B: 4 VMs, round-robin",            "round_robin", 4, False),
        ("C: 4 VMs, least-loaded",           "least_loaded", 4, False),
        ("D: 7 VMs fixed (peak sized)",      "least_loaded", 7, False),
        ("E: auto-scaling 2 -> 12 VMs",      "least_loaded", 2, True),
        ("F: auto-scaling 4 -> 12 (warm)",   "least_loaded", 4, True),
    ]
    rows, last = [], None
    for name, pol, n, auto in scenarios:
        row, cl, _ = run(name, pol, n, auto)
        rows.append(row)
        last = cl

    print("\nCloud-Based Crop Disease Detection - CloudSim-style results")
    print(f"Workload: {rows[0]['requests']} image-analysis cloudlets over 120 s (burst at 22 req/s during t=40-70 s)")
    print(f"SLA target: {SLA_SECONDS}s per request | VM price: ${VM_PRICE_PER_HOUR}/h (illustrative)\n")
    cols = ["scenario", "vms_start", "vms_created", "avg_response_s", "p95_response_s",
            "sla_violations_pct", "avg_vm_util_pct", "vm_seconds", "cost_usd"]
    widths = [32, 11, 13, 16, 16, 20, 17, 12, 10]
    print("".join(f"{c:<{w}}" for c, w in zip(cols, widths)))
    print("-" * sum(widths))
    for r in rows:
        print("".join(f"{str(r[c]):<{w}}" for c, w in zip(cols, widths)))

    with open(OUT_DIR / "cloudsim_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print_cloudsim_style(last)
    print(f"\nCSV saved to {OUT_DIR / 'cloudsim_results.csv'}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
        labels = [r["scenario"].split(":")[0] for r in rows]
        colors = ["#8aa58c"] * (len(rows) - 2) + ["#2f7d32"] * 2
        for a, key, title in zip(ax, ["avg_response_s", "sla_violations_pct", "cost_usd"],
                                 ["Avg response time (s)", "SLA violations (%)", "Cost for the 2-minute run (USD)"]):
            a.bar(labels, [r[key] for r in rows], color=colors)
            a.set_title(title, fontsize=10)
            a.spines[["top", "right"]].set_visible(False)
        fig.suptitle("A: 2 VMs RR | B: 4 VMs RR | C: 4 VMs least-loaded | D: 7 VMs fixed | "
                     "E: auto-scale from 2 | F: auto-scale from 4", fontsize=9)
        fig.tight_layout()
        fig.savefig(OUT_DIR / "cloudsim_comparison.png", dpi=130)
        print(f"Chart saved to {OUT_DIR / 'cloudsim_comparison.png'}")
    except ImportError:
        print("(matplotlib not installed - chart skipped)")


if __name__ == "__main__":
    main()
