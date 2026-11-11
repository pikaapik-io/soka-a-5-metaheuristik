#!/usr/bin/env python3
"""Analisis hasil HS vs CSA (standard library saja, tanpa scipy/matplotlib).

Membaca results/simulation/summary.csv + convergence_*.csv (dan realworld/results/
aggregate.csv bila ada), lalu menulis ke results/analysis/:
  tables.md                   tabel mean ± std, analitik vs CloudSim, Wilcoxon, sensitivitas w,
                              makespan per seed, dan real world (dipakai untuk README)
  wilcoxon.csv                uji Wilcoxon signed-rank berpasangan (pasangan = seed sama)
  convergence_<dataset>_w<w>.svg  kurva konvergensi rata-rata HS vs CSA (pita = min-max antar run)

Contoh: python3 scripts/analyze.py [--sim results/simulation] [--out results/analysis]
"""

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict

ALPHA = 0.05
DATASETS = {"GoCJ_Dataset_100": "S1 (100)", "GoCJ_Dataset_500": "S2 (500)", "GoCJ_Dataset_1000": "S3 (1.000)"}
COLORS = {"HS": "#2563eb", "CSA": "#dc2626"}


# ── Statistik ─────────────────────────────────────────────────────────────────

def mean_std(values):
    mean = statistics.mean(values)
    return mean, statistics.stdev(values) if len(values) > 1 else 0.0


def wilcoxon_signed_rank(x, y):
    """Wilcoxon signed-rank dua sisi, eksak (enumerasi distribusi permutasi tanda).

    Selisih nol dibuang (metode Wilcoxon), seri diberi rank rata-rata. Mengembalikan
    (n efektif, W+, W-, p-value).
    """
    diffs = [a - b for a, b in zip(x, y) if a != b]
    n = len(diffs)
    if n == 0:
        return 0, 0.0, 0.0, 1.0
    order = sorted(range(n), key=lambda k: abs(diffs[k]))
    ranks = [0.0] * n
    k = 0
    while k < n:
        j = k
        while j + 1 < n and abs(diffs[order[j + 1]]) == abs(diffs[order[k]]):
            j += 1
        for t in range(k, j + 1):
            ranks[order[t]] = (k + j) / 2 + 1
        k = j + 1
    w_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, diffs) if d < 0)

    # Distribusi W+ di bawah H0: setiap rank bertanda + atau - dengan peluang 1/2.
    doubled = [int(round(2 * r)) for r in ranks]  # rank rata-rata bisa x,5
    counts = {0: 1}
    for r in doubled:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c
            nxt[s + r] += c
        counts = nxt
    total = 2 ** n
    obs = int(round(2 * w_plus))
    lower = sum(c for s, c in counts.items() if s <= obs) / total
    upper = sum(c for s, c in counts.items() if s >= obs) / total
    return n, w_plus, w_minus, min(1.0, 2 * min(lower, upper))


# ── Membaca data ──────────────────────────────────────────────────────────────

def read_summary(path):
    """Baris per (dataset, algoritma, w, run); bila ada duplikat, baris terakhir yang dipakai."""
    rows = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            rows[(row["dataset"], row["algorithm"], row["w"], int(row["run"]))] = row
    groups = defaultdict(list)
    for (dataset, algorithm, w, run), row in sorted(rows.items(), key=lambda kv: kv[0][3]):
        groups[(dataset, algorithm, w)].append(row)
    return groups


def read_convergence(path, budget):
    """Fungsi tangga convergence_*.csv -> nilai terbaik di setiap evaluasi 1..budget."""
    with open(path) as f:
        steps = [(int(r["evaluation"]), float(r["best_fitness"])) for r in csv.DictReader(f)]
    values = [math.nan] * budget
    for k, (evaluation, value) in enumerate(steps):
        end = steps[k + 1][0] - 1 if k + 1 < len(steps) else budget
        for e in range(evaluation - 1, min(end, budget)):
            values[e] = value
    return values


def sort_key(dataset):
    order = list(DATASETS)
    return order.index(dataset) if dataset in order else len(order)


def label(dataset):
    return DATASETS.get(dataset, dataset)


def fmt(value, digits):
    """Angka gaya Indonesia: titik ribuan, koma desimal."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def pm(values, digits):
    mean, std = mean_std(values)
    return f"{fmt(mean, digits)} ± {fmt(std, digits)}"


# ── SVG kurva konvergensi ─────────────────────────────────────────────────────

def svg_convergence(path, title, curves, budget):
    """curves: {alg: [run1 values, run2 values, ...]}. Dua panel: semua evaluasi (x log)
    dan zoom 10-100% budget (x linear)."""
    width, height = 960, 380
    panels = [(60, "Semua evaluasi (sumbu x log)", 1, True), (540, "Zoom: evaluasi 10%–100% budget", 0.1, False)]
    pw, ph, top = 380, 270, 50
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="{width / 2}" y="22" text-anchor="middle" font-size="15" font-weight="bold" '
           f'fill="#111827">{title}</text>']
    stats = {}
    for alg, runs in curves.items():
        mean = [statistics.mean(r[e] for r in runs) for e in range(budget)]
        low = [min(r[e] for r in runs) for e in range(budget)]
        high = [max(r[e] for r in runs) for e in range(budget)]
        stats[alg] = (mean, low, high)

    for x0, subtitle, start_frac, log_x in panels:
        first = 1 if log_x else max(1, int(budget * start_frac))
        evals = sorted({int(round(first * (budget / first) ** (k / 299))) for k in range(300)}) if log_x \
            else sorted({int(round(first + (budget - first) * k / 299)) for k in range(300)})
        y_values = [v for alg in stats for series in stats[alg] for e in evals for v in [series[e - 1]]]
        y_min, y_max = min(y_values), max(y_values)
        if not log_x:  # zoom: skala dari kurva rata-rata + pita
            pad = (y_max - y_min) * 0.05 or 0.001
            y_min, y_max = y_min - pad, y_max + pad
        else:
            pad = (y_max - y_min) * 0.03 or 0.001
            y_min, y_max = y_min - pad, y_max + pad

        def sx(e):
            if log_x:
                return x0 + pw * (math.log10(e) - math.log10(first)) / (math.log10(budget) - math.log10(first))
            return x0 + pw * (e - first) / (budget - first)

        def sy(v):
            return top + ph * (1 - (v - y_min) / (y_max - y_min))

        out.append(f'<text x="{x0 + pw / 2}" y="{top - 8}" text-anchor="middle" fill="#374151">{subtitle}</text>')
        out.append(f'<rect x="{x0}" y="{top}" width="{pw}" height="{ph}" fill="none" stroke="#9ca3af"/>')
        for k in range(6):  # grid + label y
            v = y_min + (y_max - y_min) * k / 5
            y = sy(v)
            out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + pw}" y2="{y:.1f}" stroke="#e5e7eb"/>')
            out.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#4b5563">{v:.3f}</text>')
        ticks = [t for t in (1, 10, 100, 1000, 10000, 100000) if first <= t <= budget] if log_x \
            else [int(first + (budget - first) * k / 4) for k in range(5)]
        for t in ticks:
            x = sx(t)
            out.append(f'<line x1="{x:.1f}" y1="{top + ph}" x2="{x:.1f}" y2="{top + ph + 4}" stroke="#6b7280"/>')
            out.append(f'<text x="{x:.1f}" y="{top + ph + 17}" text-anchor="middle" fill="#4b5563">{t}</text>')
        out.append(f'<text x="{x0 + pw / 2}" y="{top + ph + 34}" text-anchor="middle" fill="#374151">'
                   f'evaluasi fitness</text>')
        for alg, (mean, low, high) in stats.items():
            band = [f"{sx(e):.1f},{sy(high[e - 1]):.1f}" for e in evals] + \
                   [f"{sx(e):.1f},{sy(low[e - 1]):.1f}" for e in reversed(evals)]
            out.append(f'<polygon points="{" ".join(band)}" fill="{COLORS.get(alg, "#000")}" fill-opacity="0.12"/>')
            line = " ".join(f"{sx(e):.1f},{sy(mean[e - 1]):.1f}" for e in evals)
            out.append(f'<polyline points="{line}" fill="none" stroke="{COLORS.get(alg, "#000")}" stroke-width="2"/>')
    out.append(f'<text x="22" y="{top + ph / 2}" text-anchor="middle" fill="#374151" '
               f'transform="rotate(-90 22 {top + ph / 2})">fitness terbaik F(x)</text>')
    lx = width - 230
    for k, alg in enumerate(stats):
        out.append(f'<line x1="{lx + k * 110}" y1="{height - 12}" x2="{lx + k * 110 + 24}" y2="{height - 12}" '
                   f'stroke="{COLORS.get(alg, "#000")}" stroke-width="3"/>')
        out.append(f'<text x="{lx + k * 110 + 30}" y="{height - 8}" fill="#111827">{alg} (rata-rata)</text>')
    out.append(f'<text x="60" y="{height - 8}" fill="#6b7280">Pita tipis = min–max antar run</text>')
    out.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(out))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analisis hasil HS vs CSA")
    parser.add_argument("--sim", default="results/simulation")
    parser.add_argument("--realworld", default="realworld/results")
    parser.add_argument("--out", default="results/analysis")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    groups = read_summary(os.path.join(args.sim, "summary.csv"))
    datasets = sorted({d for d, _, _ in groups}, key=sort_key)
    weights = sorted({w for _, _, w in groups}, key=lambda w: (w != "0.5", -float(w)))
    algorithms = [a for a in ("HS", "CSA") if any(a == g[1] for g in groups)]
    md = ["# Hasil Analisis HS vs CSA", "",
          "Dibuat otomatis oleh `scripts/analyze.py` dari `results/simulation/summary.csv`. "
          "Nilai = rata-rata ± std (sample, n - 1) antar run.", ""]

    # 1. Delapan metrik + fitness, w = 0,5
    main_w = "0.5" if "0.5" in weights else weights[0]
    md += [f"## 1. Delapan metrik desain (CloudSim, w = {main_w})", "",
           "| Skenario | Algoritma | Run | Fitness | Makespan (s) | Energi (kWh) | Avg response (s) | Utilisasi (%) "
           "| DI semua VM | DI VM terpakai | Throughput (task/s) | Biaya (USD) | Waktu penjadwalan (ms) | Evaluasi |",
           "|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d in datasets:
        for a in algorithms:
            rows = groups.get((d, a, main_w))
            if not rows:
                continue
            col = lambda key: [float(r[key]) for r in rows]  # noqa: E731
            md.append(f"| {label(d)} | {a} | {len(rows)} | {pm(col('fitness'), 4)} | {pm(col('makespan_s'), 2)} | "
                      f"{pm(col('energy_kwh'), 4)} | {pm(col('avg_response_s'), 2)} | {pm(col('utilization_pct'), 2)} | "
                      f"{pm(col('di_all_vm'), 3)} | {pm(col('di_used_vm'), 3)} | {pm(col('throughput_task_s'), 4)} | "
                      f"{pm(col('cost_usd'), 2)} | {pm(col('scheduling_ms'), 1)} | {int(statistics.mean(col('evaluations')))} |")
    md.append("")

    # 2. Analitik vs CloudSim
    md += [f"## 2. Model analitik vs CloudSim (w = {main_w})", "",
           "| Skenario | Algoritma | Makespan analitik (s) | Makespan CloudSim (s) | Selisih | "
           "Energi analitik (kWh) | Energi CloudSim (kWh) | Selisih |",
           "|:---:|:---:|---:|---:|---:|---:|---:|---:|"]
    for d in datasets:
        for a in algorithms:
            rows = groups.get((d, a, main_w))
            if not rows:
                continue
            am = [float(r["analytic_makespan_s"]) for r in rows]
            cm = [float(r["makespan_s"]) for r in rows]
            ae = [float(r["analytic_energy_kwh"]) for r in rows]
            ce = [float(r["energy_kwh"]) for r in rows]
            gap_m = statistics.mean((c - x) / x * 100 for c, x in zip(cm, am))
            gap_e = statistics.mean((c - x) / x * 100 for c, x in zip(ce, ae))
            md.append(f"| {label(d)} | {a} | {fmt(statistics.mean(am), 2)} | {fmt(statistics.mean(cm), 2)} | "
                      f"{fmt(gap_m, 2)}% | {fmt(statistics.mean(ae), 4)} | {fmt(statistics.mean(ce), 4)} | {fmt(gap_e, 2)}% |")
    md.append("")

    # 3. Wilcoxon
    wil_rows = []
    if len(algorithms) == 2:
        md += ["## 3. Uji Wilcoxon signed-rank berpasangan (HS vs CSA, pasangan = seed sama)", "",
               f"Dua sisi, eksak, α = {fmt(ALPHA, 2)}. Selisih nol dibuang. W+ = jumlah rank untuk HS > CSA "
               "(HS lebih buruk, karena semua metrik di bawah ini diminimalkan).", "",
               "| Skenario | w | Metrik | Mean HS | Mean CSA | n | W+ | W− | p-value | Kesimpulan |",
               "|:---:|:---:|:---|---:|---:|:---:|---:|---:|---:|:---|"]
        for w in weights:
            for d in datasets:
                hs, csa = groups.get((d, "HS", w)), groups.get((d, "CSA", w))
                if not hs or not csa:
                    continue
                pairs = {int(r["seed"]): r for r in hs}
                paired = [(pairs[int(r["seed"])], r) for r in csa if int(r["seed"]) in pairs]
                for metric, digits in (("fitness", 5), ("makespan_s", 2), ("energy_kwh", 5)):
                    x = [float(p[0][metric]) for p in paired]
                    y = [float(p[1][metric]) for p in paired]
                    n, wp, wm, p = wilcoxon_signed_rank(x, y)
                    mx, my = statistics.mean(x), statistics.mean(y)
                    if p < ALPHA:
                        verdict = f"berbeda bermakna, {'HS' if mx < my else 'CSA'} lebih baik"
                    else:
                        verdict = "tidak berbeda bermakna"
                    wil_rows.append({"dataset": d, "w": w, "metric": metric, "pairs": len(paired), "n_nonzero": n,
                                     "mean_hs": mx, "mean_csa": my, "w_plus": wp, "w_minus": wm,
                                     "p_value": p, "significant": p < ALPHA})
                    md.append(f"| {label(d)} | {w} | {metric} | {fmt(mx, digits)} | {fmt(my, digits)} | {n} | "
                              f"{fmt(wp, 1)} | {fmt(wm, 1)} | {fmt(p, 4)} | {verdict} |")
        md.append("")
        with open(os.path.join(args.out, "wilcoxon.csv"), "w", newline="") as f:
            if wil_rows:
                writer = csv.DictWriter(f, fieldnames=list(wil_rows[0]))
                writer.writeheader()
                writer.writerows(wil_rows)

    # 4. Sensitivitas w
    if len(weights) > 1:
        md += ["## 4. Sensitivitas bobot w", "",
               "w = bobot makespan; 1 - w = bobot energi. Fitness tidak bisa dibandingkan antar w "
               "(fungsinya berbeda), jadi yang dibandingkan makespan dan energi CloudSim.", "",
               "| Skenario | Algoritma | w | Fitness | Makespan (s) | Energi (kWh) | Energi dinamis analitik (kWh) |",
               "|:---:|:---:|:---:|---:|---:|---:|---:|"]
        for d in datasets:
            for a in algorithms:
                for w in sorted(weights, key=lambda v: -float(v)):
                    rows = groups.get((d, a, w))
                    if not rows:
                        continue
                    # E = Cmax x sum P_idle + dinamis  ->  dinamis = E - Cmax x 741 W
                    dyn = [float(r["analytic_energy_kwh"]) - float(r["analytic_makespan_s"]) * 741 / 3_600_000
                           for r in rows]
                    md.append(f"| {label(d)} | {a} | {w} | {pm([float(r['fitness']) for r in rows], 4)} | "
                              f"{pm([float(r['makespan_s']) for r in rows], 2)} | "
                              f"{pm([float(r['energy_kwh']) for r in rows], 4)} | {pm(dyn, 5)} |")
        md.append("")

    # 5. Makespan analitik per seed
    md += [f"## 5. Makespan analitik per seed (w = {main_w})", ""]
    for d in datasets:
        seeds = sorted({int(r["seed"]) for a in algorithms for r in groups.get((d, a, main_w), [])})
        md += [f"**{label(d)}**", "", "| Algoritma | " + " | ".join(str(s) for s in seeds) + " |",
               "|:---|" + "---:|" * len(seeds)]
        for a in algorithms:
            by_seed = {int(r["seed"]): float(r["analytic_makespan_s"]) for r in groups.get((d, a, main_w), [])}
            md.append(f"| {a} | " + " | ".join(fmt(by_seed[s], 1) if s in by_seed else "-" for s in seeds) + " |")
        md.append("")

    # 6. Kurva konvergensi
    md += ["## 6. Kurva konvergensi", ""]
    for w in weights:
        for d in datasets:
            curves, budget = {}, None
            for a in algorithms:
                rows = groups.get((d, a, w))
                if not rows:
                    continue
                budget = int(rows[0]["budget"])
                files = [os.path.join(args.sim, f"convergence_{d}_{a}_w{w}_run{r['run']}.csv") for r in rows]
                files = [p for p in files if os.path.exists(p)]
                if files:
                    curves[a] = [read_convergence(p, budget) for p in files]
            if not curves:
                continue
            name = f"convergence_{d}_w{w}.svg"
            runs = min(len(v) for v in curves.values())
            svg_convergence(os.path.join(args.out, name), f"Konvergensi {label(d)}, w = {w}, {runs} run", curves, budget)
            md.append(f"- `{name}`")
    md.append("")

    # 7. Real world
    agg_path = os.path.join(args.realworld, "aggregate.csv")
    if os.path.exists(agg_path):
        with open(agg_path) as f:
            agg = {}
            for row in csv.DictReader(f):
                if "algorithm" in row:
                    agg[(row["dataset"], row["algorithm"], row["w"], row["tasks"])] = row
        sim_means = {}
        for (d, a, w), rows in groups.items():
            sim_means[(d, a, w)] = statistics.mean(float(r["analytic_makespan_s"]) for r in rows)
        md += ["## 7. Real world (Docker, aggregate.csv terakhir per konfigurasi)", "",
               "| Skenario | Algoritma | Run | Fitness | Makespan (s) | Energi (kWh) | Avg response (s) | Utilisasi (%) "
               "| DI semua VM | DI VM terpakai | Throughput (task/s) | Biaya (USD) | Waktu penjadwalan Python (ms) |",
               "|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for (d, a, w, n), r in sorted(agg.items(), key=lambda kv: (sort_key(kv[0][0]), kv[0][1] != "HS", kv[0][2])):
            g = lambda key, digits: f"{fmt(float(r[key + '_mean']), digits)} ± {fmt(float(r[key + '_std']), digits)}"  # noqa: E731
            name = label(d) if str(n) in label(d).replace(".", "") else f"{label(d)}, n={n}"
            md.append(f"| {name} | {a} | {r['runs']} | {g('fitness', 4)} | {g('makespan_s', 2)} | {g('energy_kwh', 5)} | "
                      f"{g('avg_response_s', 2)} | {g('utilization_pct', 2)} | {g('di_all_vm', 3)} | "
                      f"{g('di_used_vm', 3)} | {g('throughput_task_s', 3)} | {g('cost_usd', 2)} | "
                      f"{g('scheduling_ms', 0)} |")
        md.append("")
        summary_path = os.path.join(args.realworld, "summary.csv")
        if os.path.exists(summary_path):
            md += ["Real world vs prediksi analitik (makespan analitik × `scale` kalibrasi):", "",
                   "| Skenario | Algoritma | Run | Seed | Prediksi (s) | Nyata (s) | Nyata / prediksi |",
                   "|:---:|:---:|:---:|:---:|---:|---:|---:|"]
            with open(summary_path) as f:
                latest = {}
                for row in csv.DictReader(f):
                    latest[(row["dataset"], row["algorithm"], row["w"], row["tasks"], row["run"])] = row
            for key, row in sorted(latest.items(), key=lambda kv: (sort_key(kv[0][0]), kv[0][1] != "HS", int(kv[0][4]))):
                pred, real = float(row["predicted_makespan_s"]), float(row["makespan_s"])
                md.append(f"| {label(row['dataset'])} | {row['algorithm']} | {row['run']} | {row['seed']} | "
                          f"{fmt(pred, 2)} | {fmt(real, 2)} | {fmt(real / pred, 2)}× |")
            md.append("")

    with open(os.path.join(args.out, "tables.md"), "w") as f:
        f.write("\n".join(md))
    print(f"analisis -> {args.out}/tables.md, wilcoxon.csv, convergence_*.svg")


if __name__ == "__main__":
    main()
