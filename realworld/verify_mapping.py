#!/usr/bin/env python3
"""Cek bahwa HS/CSA versi Python menghasilkan mapping yang IDENTIK dengan CloudSim (Java).

Untuk setiap run r, mapping Python dengan seed = seed dasar + r - 1 dibandingkan dengan
kolom vm di results/simulation/cloudlets_<dataset>_<ALG>_w<w>_run<r>.csv. Fitness akhir
juga dibandingkan dengan baris terakhir convergence_*.csv (harus sama persis, bukan
sekadar dekat). Dengan --trace, kurva konvergensi lengkap dibandingkan dan evaluasi
pertama yang berbeda dicetak, untuk melacak langkah yang divergen.

Contoh:
  python3 verify_mapping.py --dataset ../src/main/resources/dataset/GoCJ_Dataset_100.txt --runs 3
  python3 verify_mapping.py --dataset ... --algorithm HS --runs 10 --trace
Exit code 1 bila ada yang BEDA atau file simulasi tidak ditemukan.
"""

import argparse
import csv
import os
import sys

import meta_realworld as rw
import metaheuristic


def read_java_mapping(path):
    with open(path) as f:
        rows = sorted(csv.DictReader(f), key=lambda row: int(row["task_id"]))
    return [int(row["vm"]) for row in rows]


def read_convergence(path):
    """Fungsi tangga {evaluasi: fitness terbaik} dari convergence_*.csv."""
    with open(path) as f:
        return [(int(row["evaluation"]), float(row["best_fitness"])) for row in csv.DictReader(f)]


def first_trace_difference(steps, trace):
    """Evaluasi pertama di mana fitness terbaik Python != Java, atau None."""
    for k, (evaluation, value) in enumerate(steps):
        end = steps[k + 1][0] - 1 if k + 1 < len(steps) else evaluation
        for e in range(evaluation, end + 1):
            if e > len(trace) or trace[e - 1] != value:
                return e
    return None if len(trace) == steps[-1][0] else steps[-1][0] + 1


def main():
    parser = argparse.ArgumentParser(description="Bandingkan mapping Python vs CloudSim (Java)")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--algorithm", default="HS,CSA", help="HS, CSA, atau HS,CSA")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--w", type=float, default=metaheuristic.DEFAULT_WEIGHT)
    parser.add_argument("--budget", type=int, default=metaheuristic.DEFAULT_BUDGET)
    parser.add_argument("--sim-dir", default="../results/simulation")
    parser.add_argument("--trace", action="store_true", help="bandingkan kurva konvergensi lengkap")
    args = parser.parse_args()

    lengths = rw.load_gocj(args.dataset)
    dataset = os.path.splitext(os.path.basename(args.dataset))[0]
    failures = 0
    for algorithm in [a.strip().upper() for a in args.algorithm.split(",") if a.strip()]:
        for run in range(1, args.runs + 1):
            seed = args.seed + run - 1
            tag = f"{dataset}_{algorithm}_w{args.w:g}_run{run}"
            cloudlets = os.path.join(args.sim_dir, f"cloudlets_{tag}.csv")
            convergence = os.path.join(args.sim_dir, f"convergence_{tag}.csv")
            label = f"{dataset} {algorithm:<3} run {run} seed={seed}"
            if not os.path.exists(cloudlets):
                print(f"{label}: FILE TIDAK ADA ({cloudlets}); jalankan simulasi dulu")
                failures += 1
                continue

            mapping, scheduler, sched_ms = rw.schedule(algorithm, lengths, seed, args.w, args.budget)
            java = read_java_mapping(cloudlets)
            same = sum(a == b for a, b in zip(mapping, java))
            identical = mapping == java
            note = ""
            if os.path.exists(convergence):
                steps = read_convergence(convergence)
                java_fitness = steps[-1][1]
                fitness_same = java_fitness == scheduler.best_fitness
                identical = identical and fitness_same
                note = f", fitness {'sama' if fitness_same else 'BEDA'} ({scheduler.best_fitness!r})"
                if args.trace:
                    diff = first_trace_difference(steps, scheduler.trace)
                    note += ", trace sama" if diff is None else f", trace BEDA mulai evaluasi {diff}"
                    identical = identical and diff is None
            print(f"{label}: {'IDENTIK' if identical else 'BEDA'} - {same} / {len(java)} task sama{note} "
                  f"[Python {sched_ms / 1000:.1f} s]", flush=True)
            failures += 0 if identical else 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
