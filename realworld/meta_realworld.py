#!/usr/bin/env python3
"""HS & CSA Real-World Runner, Kelompok 5 (turunan kpb_realworld.py).

Menjadwalkan task GoCJ ke 20 container Docker dengan Harmony Search (HS) atau Clonal
Selection Algorithm (CSA), mengeksekusinya secara nyata, lalu menghitung delapan metrik
Design Project bagian 4.1 ditambah nilai fitness.

Infrastruktur mengikuti desain (lihat docker-compose.yml):
  * 20 VM: V3 4 PE x 2.500 MIPS, V2 2 PE x 1.500, V1 1 PE x 1.000 (1,0 CPU = 10.000 MIPS)
  * 2 datacenter / 6 host sesuai penempatan VM hasil CloudSim
  * Time-shared: semua task dalam satu VM aktif bersamaan, tiap task maksimal 1 PE

HS/CSA ada di metaheuristic.py, port bit-identik dari kode Java. Run ke-r memakai
seed = seed dasar + r - 1, sehingga mapping-nya sama dengan simulasi CloudSim run ke-r
(cek dengan verify_mapping.py).

Contoh:
  python3 meta_realworld.py --algorithm HS --dataset ../src/main/resources/dataset/GoCJ_Dataset_100.txt
  python3 meta_realworld.py --algorithm CSA ... --quiet     (tanpa log broker per cloudlet)
"""

import argparse
import csv
import json
import os
import re
import statistics
import threading
import time
import urllib.request
from datetime import datetime

import metaheuristic

REF_MIPS = 10_000          # 1,0 CPU container = 10.000 MIPS
DEFAULT_ITERS_PER_MI = 14  # beban tetap: L x 14 iterasi CPU

# ── Infrastruktur (Design Project bagian 2) ───────────────────────────────────
# Host: PE x MIPS, daya idle/maks (W). Datacenter: biaya (bagian 2.2).
HOST_TYPES = {
    "A": {"pes": 8, "mips": 3_000, "p_idle": 175, "p_max": 250},
    "B": {"pes": 8, "mips": 1_800, "p_idle": 72, "p_max": 120},
}
DATACENTERS = {
    1: {"name": "DC-1 Performance", "host_type": "A", "cost_sec": 0.05, "cost_gb_ram": 0.02, "cost_bw": 0.005},
    2: {"name": "DC-2 Efficiency", "host_type": "B", "cost_sec": 0.03, "cost_gb_ram": 0.01, "cost_bw": 0.003},
}
HOSTS = [(dc, h) for dc in DATACENTERS for h in range(3)]

VM_TYPES = {
    "V3": {"pes": 4, "mips": 2_500, "ram_gb": 8, "bw": 1_000},
    "V2": {"pes": 2, "mips": 1_500, "ram_gb": 4, "bw": 1_000},
    "V1": {"pes": 1, "mips": 1_000, "ram_gb": 2, "bw": 500},
}
# Penempatan VM -> (datacenter, host) hasil CloudSim (results/simulation/placement.csv)
PLACEMENT = [(1, 0), (1, 1), (1, 2), (1, 0), (1, 1), (1, 2), (1, 1), (1, 2), (2, 0), (2, 1),
             (2, 2), (2, 0), (2, 1), (2, 2), (2, 1), (2, 2), (2, 0), (2, 1), (2, 2), (2, 0)]
VMS = []
for i, vm_type in enumerate(["V3"] * 4 + ["V2"] * 8 + ["V1"] * 8):
    spec = VM_TYPES[vm_type]
    VMS.append({
        "name": f"vm{i:02d}", "type": vm_type, "url": f"http://127.0.0.1:{9100 + i}",
        "pes": spec["pes"], "mips": spec["mips"], "capacity": spec["pes"] * spec["mips"],
        "ram_gb": spec["ram_gb"], "bw": spec["bw"],
        "dc": PLACEMENT[i][0], "host": PLACEMENT[i][1],
    })


def energy_model():
    """Sama dengan CloudSimAdapter.energyModel(): sum P_idle semua host dan kappa per VM."""
    idle = 0.0
    for dc, _ in HOSTS:
        idle += HOST_TYPES[DATACENTERS[dc]["host_type"]]["p_idle"]
    kappa = []
    for vm in VMS:
        host = HOST_TYPES[DATACENTERS[vm["dc"]]["host_type"]]
        kappa.append(metaheuristic.EnergyModel.kappa(host["p_max"], host["p_idle"], host["pes"], host["mips"]))
    return metaheuristic.EnergyModel(idle, kappa)


def capacities():
    return [vm["capacity"] for vm in VMS]


def schedule(algorithm, lengths, seed, weight, budget):
    """Jalankan HS/CSA versi Python. Mengembalikan (mapping, scheduler, waktu ms)."""
    scheduler = metaheuristic.create(algorithm, energy_model(), seed, weight, budget)
    start = time.perf_counter()
    mapping = scheduler.schedule(lengths, capacities())
    return mapping, scheduler, (time.perf_counter() - start) * 1000


# ── Dataset ───────────────────────────────────────────────────────────────────

def load_gocj(path):
    """Sama dengan GoCJLoader.java: angka dipisah spasi/koma/titik koma, '#' komentar."""
    lengths = []
    with open(path) as f:
        for line in f:
            content = line.split("#", 1)[0].strip()
            if content:
                lengths += [float(tok) for tok in re.split(r"[,;\s]+", content)]
    return lengths


# ── Komunikasi dengan worker ──────────────────────────────────────────────────

def post_stream(url, payload, timeout=7200):
    """POST lalu baca balasan NDJSON worker baris per baris, begitu barisnya dikirim."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if line.strip():
                yield json.loads(line)


def where(vm):
    """Contoh: vm00 (V3) di DC-1/Host A0."""
    return f"{vm['name']} ({vm['type']}) di DC-{vm['dc']}/Host {DATACENTERS[vm['dc']]['host_type']}{vm['host']}"


def check_workers():
    for vm in VMS:
        try:
            with urllib.request.urlopen(vm["url"] + "/health", timeout=5) as resp:
                health = json.loads(resp.read())
        except OSError as exc:
            raise SystemExit(f"[ERROR] {vm['name']} ({vm['url']}) tidak merespons: {exc}\n"
                             "        Jalankan dulu: docker compose up -d")
        if not health.get("stream"):
            raise SystemExit(f"[ERROR] {vm['name']} masih memakai worker versi lama (tanpa log real-time).\n"
                             "        Jalankan ulang: docker compose restart")
        if health.get("pes") != vm["pes"]:
            raise SystemExit(f"[ERROR] {vm['name']} punya {health.get('pes')} PE, seharusnya {vm['pes']}.\n"
                             "        Jalankan ulang: docker compose up -d --force-recreate")


def check_placement(path):
    """Cocokkan PLACEMENT dengan hasil CloudSim bila file-nya ada."""
    if not os.path.exists(path):
        return "placement CloudSim belum ada (jalankan simulasi dulu untuk verifikasi)"
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for row, vm in zip(rows, VMS):
        if (int(row["datacenter"]), int(row["host"])) != (vm["dc"], vm["host"]):
            raise SystemExit(f"[ERROR] Penempatan {vm['name']} beda dengan CloudSim: "
                             f"DC{row['datacenter']}/H{row['host']} vs DC{vm['dc']}/H{vm['host']}")
    return "placement cocok dengan CloudSim"


def calibrate(iterations=2_000_000):
    """Iterasi per detik setara 1,0 CPU, diukur pada 1 PE V3 (0,25 CPU)."""
    t0 = time.monotonic()
    elapsed = None
    for event in post_stream(VMS[0]["url"] + "/batch", {"tasks": [{"id": 0, "iterations": iterations}]}):
        if "id" in event:
            elapsed = event["finish"] - t0
    return iterations / elapsed * (REF_MIPS / VMS[0]["mips"])


# ── Eksekusi satu run ─────────────────────────────────────────────────────────

def execute(lengths, mapping, iters_per_mi, live=True):
    """Kirim satu batch per VM, lalu tampilkan setiap cloudlet yang selesai secara real-time.

    Waktu di log = detik sejak batch dikirim (t0). Waktu selesai diukur di dalam
    container, jadi pencetakan log tidak memengaruhi metrik.
    """
    batches = {j: [] for j in range(len(VMS))}
    for task, vm in enumerate(mapping):
        batches[vm].append({"id": task, "iterations": int(lengths[task] * iters_per_mi)})

    total = len(mapping)
    finish = {}  # task -> (indeks VM, detik sejak t0)
    cpu_s = [0.0] * len(VMS)
    errors = []
    lock = threading.Lock()

    def log(t, message):
        if live:
            print(f"{t:9.2f}: Broker: {message}", flush=True)

    for task, vm in enumerate(mapping):
        log(0.0, f"Mengirim Cloudlet #{task} ({int(lengths[task])} MI) ke {where(VMS[vm])}")
    t0 = time.monotonic()

    def run_vm(j):
        vm = VMS[j]
        try:
            for event in post_stream(vm["url"] + "/batch", {"tasks": batches[j]}):
                with lock:
                    if "id" in event:
                        task, t = int(event["id"]), event["finish"] - t0
                        finish[task] = (j, t)
                        log(t, f"Cloudlet #{task} selesai di {where(vm)}, diterima broker")
                        log(t, f"Jumlah cloudlet selesai: {len(finish)}/{total}")
                    else:
                        cpu_s[j] = event["cpu_s"]
                        log(time.monotonic() - t0, f"{vm['name']} ({vm['type']}) selesai: "
                            f"{len(batches[j])} cloudlet, CPU terpakai {cpu_s[j]:.2f} s")
        except Exception as exc:  # noqa: BLE001 - dilaporkan setelah join
            with lock:
                errors.append(f"{vm['name']}: {exc}")

    threads = [threading.Thread(target=run_vm, args=(j,)) for j in batches if batches[j]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise SystemExit("[ERROR] " + "; ".join(errors))
    if len(finish) != total:
        raise SystemExit(f"[ERROR] Hanya {len(finish)} dari {total} cloudlet yang selesai")
    log(max(t for _, t in finish.values()), f"Semua cloudlet selesai ({total}/{total}). Finishing...")

    records = []
    for task, (j, t) in finish.items():
        records.append({
            "task_id": task, "length_mi": int(lengths[task]),
            "vm": VMS[j]["name"], "vm_type": VMS[j]["type"],
            "datacenter": VMS[j]["dc"], "host": VMS[j]["host"],
            "finish_s": round(t, 4),
        })
    return sorted(records, key=lambda r: r["task_id"]), cpu_s


# ── Metrik (Design Project bagian 4.1) ────────────────────────────────────────

def degree_of_imbalance(times):
    avg = sum(times) / len(times) if times else 0
    return (max(times) - min(times)) / avg if avg > 0 else 0.0


def compute_metrics(records, cpu_s):
    vm_finish = [0.0] * len(VMS)
    for r in records:
        j = int(r["vm"][2:])
        vm_finish[j] = max(vm_finish[j], r["finish_s"])
    makespan = max(vm_finish)

    # Energi: P(u) = P_idle + (P_max - P_idle) * u untuk 6 host dari 0 sampai Cmax.
    # integral u_k dt = CPU-detik VM di host k / kapasitas CPU host k.
    joules = 0.0
    for dc, h in HOSTS:
        host = HOST_TYPES[DATACENTERS[dc]["host_type"]]
        host_cpu = host["pes"] * host["mips"] / REF_MIPS
        busy = sum(cpu_s[j] for j, vm in enumerate(VMS) if (vm["dc"], vm["host"]) == (dc, h))
        joules += host["p_idle"] * makespan + (host["p_max"] - host["p_idle"]) * busy / host_cpu

    # Biaya: rumus yang sama dengan VmCost CloudSim (CPU + RAM + BW), VM hidup selama Cmax.
    cost = 0.0
    for vm in VMS:
        dc = DATACENTERS[vm["dc"]]
        host_mips_per_pe = HOST_TYPES[dc["host_type"]]["mips"]
        cost += dc["cost_sec"] * (vm["capacity"] / host_mips_per_pe) * makespan
        cost += dc["cost_gb_ram"] * vm["ram_gb"] + dc["cost_bw"] * vm["bw"]

    return {
        "tasks": len(records),
        "makespan_s": makespan,
        "energy_kwh": joules / 3_600_000,
        "avg_response_s": sum(r["finish_s"] for r in records) / len(records),
        "utilization_pct": 100 * sum(vm_finish) / (len(VMS) * makespan),
        "di_all_vm": degree_of_imbalance(vm_finish),
        "di_used_vm": degree_of_imbalance([t for t in vm_finish if t > 0]),
        "throughput_task_s": len(records) / makespan,
        "cost_usd": cost,
        "vms_used": sum(1 for t in vm_finish if t > 0),
    }


# ── Output ────────────────────────────────────────────────────────────────────

def append_csv(path, row):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


METRICS = ["fitness", "makespan_s", "energy_kwh", "avg_response_s", "utilization_pct", "di_all_vm",
           "di_used_vm", "throughput_task_s", "cost_usd", "scheduling_ms"]


def main():
    parser = argparse.ArgumentParser(description="HS & CSA real-world runner (Docker)")
    parser.add_argument("--algorithm", default="HS", type=str.upper, choices=["HS", "CSA"])
    parser.add_argument("--dataset", default="../src/main/resources/dataset/GoCJ_Dataset_100.txt")
    parser.add_argument("--repeat", type=int, default=3, help="jumlah repetisi (default 3)")
    parser.add_argument("--seed", type=int, default=42, help="seed dasar; run ke-r memakai seed + r - 1")
    parser.add_argument("--w", type=float, default=metaheuristic.DEFAULT_WEIGHT, help="bobot makespan [0, 1]")
    parser.add_argument("--budget", type=int, default=metaheuristic.DEFAULT_BUDGET, help="evaluasi fitness per run")
    parser.add_argument("--iters-per-mi", type=float, default=DEFAULT_ITERS_PER_MI,
                        help="iterasi CPU per MI (beban tetap, default 14)")
    parser.add_argument("--limit", type=int, default=0, help="hanya pakai N task pertama")
    parser.add_argument("--out", default="results")
    parser.add_argument("--placement", default="../results/simulation/placement.csv")
    parser.add_argument("--quiet", action="store_true", help="sembunyikan log broker per cloudlet")
    args = parser.parse_args()
    if not 0 <= args.w <= 1:
        raise SystemExit("--w harus di rentang [0, 1]")
    if args.repeat < 1:
        raise SystemExit("--repeat minimal 1")

    lengths = load_gocj(args.dataset)
    if args.limit:
        lengths = lengths[:args.limit]

    check_workers()
    placement_note = check_placement(args.placement)
    rate = calibrate()
    scale = args.iters_per_mi * REF_MIPS / rate  # 1 detik simulasi = scale detik nyata

    dataset_name = os.path.splitext(os.path.basename(args.dataset))[0]
    tag = f"{dataset_name}_n{len(lengths)}_{args.algorithm}_w{args.w:g}"
    os.makedirs(args.out, exist_ok=True)
    print(f"scheduler={args.algorithm} realworld (Python), {placement_note}")
    print(f"dataset={args.dataset} tasks={len(lengths)} repeat={args.repeat} seed={args.seed}.."
          f"{args.seed + args.repeat - 1} w={args.w:g} budget={args.budget} "
          f"itersPerMI={args.iters_per_mi:g} scale={scale:.4f}")

    runs = []
    for run in range(1, args.repeat + 1):
        seed = args.seed + run - 1
        print(f"[run {run}/{args.repeat} seed={seed}] menjadwalkan dengan {args.algorithm}...", flush=True)
        mapping, scheduler, sched_ms = schedule(args.algorithm, lengths, seed, args.w, args.budget)
        analytic = scheduler.objective.makespan(mapping)
        analytic_kwh = scheduler.objective.energy_joules(mapping) / 3_600_000
        predicted = analytic * scale

        print(f"  fitness={scheduler.best_fitness:.6f} evaluations={scheduler.evaluations_used} "
              f"schedulingTime={sched_ms:.1f} ms, makespan analitik={analytic:.3f} s", flush=True)
        print(f"  menjalankan task di container... (prediksi analitik ±{predicted:.1f} s)", flush=True)
        records, cpu_s = execute(lengths, mapping, args.iters_per_mi, live=not args.quiet)
        m = compute_metrics(records, cpu_s)
        m["scheduling_ms"] = sched_ms
        m["fitness"] = scheduler.best_fitness
        runs.append(m)

        print(f"  makespan={m['makespan_s']:.3f}s, energy={m['energy_kwh']:.6f} kWh, "
              f"avgResponse={m['avg_response_s']:.3f}s, utilization={m['utilization_pct']:.2f}%, "
              f"DI={m['di_all_vm']:.4f} (VM terpakai {m['di_used_vm']:.4f}), "
              f"throughput={m['throughput_task_s']:.3f} task/s, cost=${m['cost_usd']:.2f}, "
              f"schedulingTime={sched_ms:.1f} ms, vmsUsed={m['vms_used']}/20", flush=True)

        write_csv(os.path.join(args.out, f"tasks_{tag}_run{run}.csv"), records)
        row = {"timestamp": datetime.now().isoformat(timespec="seconds"), "dataset": dataset_name,
               "tasks": m["tasks"], "algorithm": args.algorithm, "w": f"{args.w:g}", "budget": args.budget,
               "run": run, "seed": seed, "evaluations": scheduler.evaluations_used,
               "iters_per_mi": args.iters_per_mi, "scale": round(scale, 5),
               "analytic_makespan_s": round(analytic, 4), "analytic_energy_kwh": round(analytic_kwh, 6),
               "predicted_makespan_s": round(predicted, 4)}
        row.update({key: round(m[key], 10 if key == "fitness" else 6) for key in METRICS})
        row["vms_used"] = m["vms_used"]
        append_csv(os.path.join(args.out, "summary.csv"), row)

    agg = {"dataset": dataset_name, "tasks": len(lengths), "algorithm": args.algorithm, "w": f"{args.w:g}",
           "budget": args.budget, "runs": len(runs), "seed_first": args.seed}
    print(f"rata-rata ± std dari {len(runs)} run:")
    for key in METRICS:
        values = [r[key] for r in runs]
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        agg[f"{key}_mean"], agg[f"{key}_std"] = round(mean, 6), round(std, 6)
        print(f"  {key:<18} {mean:12.4f} ± {std:.4f}")
    append_csv(os.path.join(args.out, "aggregate.csv"), agg)
    print(f"hasil -> {args.out}/summary.csv, {args.out}/aggregate.csv, {args.out}/tasks_{tag}_run*.csv")


if __name__ == "__main__":
    main()
