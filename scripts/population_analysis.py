#!/usr/bin/env python3
"""Analisis uji ukuran populasi: HMS untuk HS dan N untuk CSA, dengan budget evaluasi sama.

Membaca results/population/raw/pop<N>_<dataset>_<alg>/ (hasil scripts/population_sweep.sh),
lalu menulis ke results/population/:
  summary.csv                  rata-rata dan std per dataset x algoritma x ukuran populasi
  tables.md                    tabel fitness/makespan, ukuran terbaik, uji Wilcoxon
  population_fitness.svg       fitness rata-rata vs ukuran populasi per skenario
  population_convergence.svg   kurva konvergensi S3 untuk beberapa ukuran populasi
  hs_vs_csa.svg                HS vs CSA: kualitas pada ukuran 20 dan terbaik, serta waktu

Standard library saja. Contoh: python3 scripts/population_analysis.py
"""

import argparse
import csv
import glob
import math
import os
import re
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import (ALPHA, fmt, label, mean_std, pm, read_convergence, read_summary, sort_key,  # noqa: E402
                     wilcoxon_signed_rank)

DEFAULT_POP = 20
# Kurva konvergensi: terlalu kecil, terbaik rata-rata, terlalu besar (hasil sweep 2026-11-28).
CONVERGENCE_SIZES = (2, 10, 100)
ALGS = ["HS", "CSA"]
METRICS = ["fitness", "makespan_s", "energy_kwh", "avg_response_s", "di_used_vm", "scheduling_ms"]
DIR_NAME = re.compile(r"^pop(\d+)_(.+)_(HS|CSA)$")
SHORT = {"GoCJ_Dataset_100": "S1", "GoCJ_Dataset_500": "S2", "GoCJ_Dataset_1000": "S3"}
TASKS = {"GoCJ_Dataset_100": "100 task", "GoCJ_Dataset_500": "500 task", "GoCJ_Dataset_1000": "1.000 task"}


# ── Data ──────────────────────────────────────────────────────────────────────

def load(raw_dir):
    """(dataset, alg, pop) -> {"rows": baris summary.csv urut run, "dir": folder}."""
    data = {}
    for folder in sorted(glob.glob(os.path.join(raw_dir, "pop*"))):
        match = DIR_NAME.match(os.path.basename(folder))
        path = os.path.join(folder, "summary.csv")
        if not match or not os.path.exists(path):
            continue
        with open(path) as f:
            rows = sorted(csv.DictReader(f), key=lambda r: int(r["run"]))
        data[(match.group(2), match.group(3), int(match.group(1)))] = {"rows": rows, "dir": folder}
    return data


def values(data, key, metric):
    return [float(r[metric]) for r in data[key]["rows"]]


def gap(fitness):
    """F = 1 berarti tepat di batas bawah, jadi (F - 1) x 100 = persen di atas batas bawah."""
    return (fitness - 1) * 100


# ── SVG ───────────────────────────────────────────────────────────────────────

FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
# Palet kategorikal tervalidasi (slot 1 biru = HS, slot 2 oranye = CSA) dan ramp ordinal biru,
# masing-masing dengan langkah terpisah untuk mode gelap.
STYLE = """<style>
.bg{fill:#ffffff}.t1{fill:#191919}.t2{fill:#666666}.grid{stroke:#e7e7e7}.axis{stroke:#c2c2c2}
.ring{stroke:#ffffff}.band{fill:#191919;fill-opacity:.04}
.s-HS{stroke:#257de0}.f-HS{fill:#257de0}.s-CSA{stroke:#f47230}.f-CSA{fill:#f47230}
.s-o0{stroke:#84b9f3}.s-o1{stroke:#257de0}.s-o2{stroke:#0f4a96}
@media (prefers-color-scheme: dark){
.bg{fill:#191919}.t1{fill:#efefef}.t2{fill:#9c9c9c}.grid{stroke:#303030}.axis{stroke:#474747}
.ring{stroke:#191919}.band{fill:#efefef;fill-opacity:.05}
.s-HS{stroke:#338ced}.f-HS{fill:#338ced}.s-CSA{stroke:#e76624}.f-CSA{fill:#e76624}
.s-o0{stroke:#b6d5f8}.s-o1{stroke:#519ced}.s-o2{stroke:#1b64be}
}
</style>"""


def svg_open(width, height, title, desc):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="12" role="img">',
            f"<title>{title}</title>", f"<desc>{desc}</desc>", STYLE,
            f'<rect class="bg" width="{width}" height="{height}" rx="8"/>']


def text(x, y, content, cls="t2", anchor="start", size=12, weight="normal", extra=""):
    return (f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{size}" '
            f'font-weight="{weight}"{extra}>{content}</text>')


def marker(alg, x, y, r):
    """HS = lingkaran, CSA = persegi (bentuk sebagai penanda kedua selain warna)."""
    if alg == "HS":
        return f'<circle class="f-{alg} ring" cx="{x:.1f}" cy="{y:.1f}" r="{r}" stroke-width="2"/>'
    return (f'<rect class="f-{alg} ring" x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" '
            f'rx="1.5" stroke-width="2"/>')


def legend(x, y, items):
    """items: [(alg, label)] dengan marker + garis pendek."""
    out = []
    for alg, name in items:
        out.append(f'<line class="s-{alg}" x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" stroke-width="2"/>')
        out.append(marker(alg, x + 11, y - 4, 4))
        out.append(text(x + 28, y, name, "t1"))
        x += 28 + 8 * len(name) + 22
    return out


def nice_ticks(lo, hi, count=5):
    step = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(step))
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= step), default=step)
    start = math.ceil(lo / step) * step
    ticks, t = [], start
    while t <= hi + 1e-12:
        ticks.append(round(t, 10))
        t += step
    return ticks, step


def decimals(step):
    return max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0


def spread_labels(items, min_gap, lo, hi):
    """items: [(y, ...)] -> posisi y tanpa tumpang tindih (jarak minimal min_gap)."""
    order = sorted(range(len(items)), key=lambda k: items[k][0])
    ys = [items[k][0] for k in order]
    for k in range(1, len(ys)):
        ys[k] = max(ys[k], ys[k - 1] + min_gap)
    overflow = ys[-1] - hi if ys else 0
    if overflow > 0:
        ys = [y - overflow for y in ys]
    for k in range(len(ys) - 2, -1, -1):
        ys[k] = min(ys[k], ys[k + 1] - min_gap)
    ys = [max(lo, y) for y in ys]
    result = [0.0] * len(items)
    for pos, k in enumerate(order):
        result[k] = ys[pos]
    return result


def chart_fitness(path, data, datasets, sizes, best):
    width, height = 960, 430
    pw, ph, top = 250, 220, 140
    xs0 = [74, 384, 694]
    out = svg_open(width, height, "Fitness vs ukuran populasi",
                   "Rata-rata fitness terbaik HS dan CSA untuk setiap ukuran populasi, per skenario. "
                   "Lebih rendah lebih baik.")
    out.append(text(24, 32, "Fitness terbaik vs ukuran populasi", "t1", size=16, weight="600"))
    out.append(text(24, 52, "Rata-rata 10 seed, w = 0,5, budget 10.000 evaluasi. Lebih rendah lebih baik. "
                            "Titik besar = ukuran terbaik; garis vertikal = default 20."))
    out += legend(24, 80, [("HS", "HS (HMS)"), ("CSA", "CSA (N)")])
    lo_x, hi_x = math.log10(min(sizes)), math.log10(max(sizes))
    pad_x = (hi_x - lo_x) * 0.06

    for x0, dataset in zip(xs0, datasets):
        means = {(alg, s): statistics.mean(values(data, (dataset, alg, s), "fitness"))
                 for alg in ALGS for s in sizes if (dataset, alg, s) in data}
        y_lo, y_hi = min(means.values()), max(means.values())
        pad = (y_hi - y_lo) * 0.12 or 0.001
        y_lo, y_hi = y_lo - pad, y_hi + pad
        ticks, step = nice_ticks(y_lo, y_hi, 5)

        def sx(size):
            return x0 + pw * (math.log10(size) - lo_x + pad_x) / (hi_x - lo_x + 2 * pad_x)

        def sy(v):
            return top + ph * (1 - (v - y_lo) / (y_hi - y_lo))

        out.append(text(x0, top - 30, f"{SHORT[dataset]} ({TASKS[dataset]})", "t1", size=13, weight="600"))
        best_text = ", ".join(f"{alg} = {best[(dataset, alg)]}" for alg in ALGS)
        out.append(text(x0, top - 14, f"terbaik: {best_text}"))
        for t in ticks:
            if y_lo <= t <= y_hi:
                out.append(f'<line class="grid" x1="{x0}" y1="{sy(t):.1f}" x2="{x0 + pw}" y2="{sy(t):.1f}"/>')
                out.append(text(x0 - 8, sy(t) + 4, fmt(t, decimals(step) + 1), anchor="end",
                                extra=' style="font-variant-numeric:tabular-nums"'))
        out.append(f'<line class="axis" x1="{x0}" y1="{top + ph}" x2="{x0 + pw}" y2="{top + ph}"/>')
        dx = sx(DEFAULT_POP)
        out.append(f'<line class="axis" x1="{dx:.1f}" y1="{top}" x2="{dx:.1f}" y2="{top + ph}"/>')
        out.append(text(dx + 4, top + 12, "default"))
        for s in sizes:  # 10px: 15 dan 20 hanya berjarak ~16px di skala log
            out.append(text(sx(s), top + ph + 18, str(s), anchor="middle", size=10))
        out.append(text(x0 + pw / 2, top + ph + 38, "ukuran populasi (skala log)", anchor="middle"))
        for alg in ALGS:
            pts = [(sx(s), sy(means[(alg, s)])) for s in sizes if (alg, s) in means]
            out.append(f'<polyline class="s-{alg}" fill="none" stroke-width="2" stroke-linejoin="round" '
                       f'points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
            for s in sizes:
                if (alg, s) in means:
                    out.append(marker(alg, sx(s), sy(means[(alg, s)]), 6 if s == best[(dataset, alg)] else 4))
    out.append(text(22, top + ph / 2, "fitness F(x)", anchor="middle",
                    extra=f' transform="rotate(-90 22 {top + ph / 2})"'))
    out.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(out))


def chart_convergence(path, data, dataset, conv_sizes, budget):
    width, height = 960, 420
    pw, ph, top = 330, 240, 120
    xs0 = [80, 560]
    names = {"HS": "HMS", "CSA": "N"}
    out = svg_open(width, height, "Konvergensi per ukuran populasi",
                   f"Rata-rata fitness terbaik selama pencarian pada {label(dataset)} untuk beberapa "
                   "ukuran populasi, HS dan CSA.")
    out.append(text(24, 32, f"Konvergensi pada {SHORT[dataset]} ({TASKS[dataset]}) untuk beberapa ukuran populasi",
                    "t1", size=16, weight="600"))
    out.append(text(24, 52, "Rata-rata fitness terbaik dari 10 seed selama 10.000 evaluasi. Makin gelap = "
                            "populasi makin besar. Sumbu y dipotong agar bagian akhir terlihat."))
    curves = {}
    for alg in ALGS:
        for s in conv_sizes:
            folder = data[(dataset, alg, s)]["dir"]
            runs = [read_convergence(p, budget) for p in sorted(glob.glob(os.path.join(folder, "convergence_*.csv")))]
            curves[(alg, s)] = [statistics.mean(r[e] for r in runs) for e in range(budget)]
    finals = [c[-1] for c in curves.values()]
    y_lo = min(finals)
    y_hi = max(c[budget // 10] for c in curves.values())
    pad = (y_hi - y_lo) * 0.06
    y_lo, y_hi = y_lo - pad, y_hi + pad
    ticks, step = nice_ticks(y_lo, y_hi, 5)
    evals = sorted({int(round(1 + (budget - 1) * k / 399)) for k in range(400)})

    for x0, alg in zip(xs0, ALGS):
        def sx(e):
            return x0 + pw * e / budget

        def sy(v):
            return top + ph * (1 - (v - y_lo) / (y_hi - y_lo))

        out.append(text(x0, top - 14, f"{alg} (ukuran = {names[alg]})", "t1", size=13, weight="600"))
        out.append(f'<clipPath id="clip-{alg}"><rect x="{x0}" y="{top}" width="{pw}" height="{ph}"/></clipPath>')
        for t in ticks:
            if y_lo <= t <= y_hi:
                out.append(f'<line class="grid" x1="{x0}" y1="{sy(t):.1f}" x2="{x0 + pw}" y2="{sy(t):.1f}"/>')
                out.append(text(x0 - 8, sy(t) + 4, fmt(t, decimals(step) + 1), anchor="end",
                                extra=' style="font-variant-numeric:tabular-nums"'))
        out.append(f'<line class="axis" x1="{x0}" y1="{top + ph}" x2="{x0 + pw}" y2="{top + ph}"/>')
        for e in range(0, budget + 1, budget // 5):
            out.append(text(sx(e), top + ph + 18, fmt(e, 0), anchor="middle"))
        out.append(text(x0 + pw / 2, top + ph + 38, "evaluasi fitness", anchor="middle"))
        label_items = []
        for k, s in enumerate(conv_sizes):
            curve = curves[(alg, s)]
            pts = " ".join(f"{sx(e):.1f},{sy(curve[e - 1]):.1f}" for e in evals)
            out.append(f'<polyline class="s-o{k}" clip-path="url(#clip-{alg})" fill="none" stroke-width="2" '
                       f'stroke-linejoin="round" points="{pts}"/>')
            label_items.append((sy(curve[-1]), s))
        for (_, s), y in zip(label_items, spread_labels(label_items, 14, top + 8, top + ph - 2)):
            out.append(text(x0 + pw + 6, y + 4, f"{names[alg]} {s}", "t1"))
    out.append(text(22, top + ph / 2, "fitness terbaik F(x)", anchor="middle",
                    extra=f' transform="rotate(-90 22 {top + ph / 2})"'))
    # Legenda ramp ordinal.
    lx = 24
    for k, s in enumerate(conv_sizes):
        out.append(f'<line class="s-o{k}" x1="{lx}" y1="{80 - 4}" x2="{lx + 22}" y2="{80 - 4}" stroke-width="3"/>')
        out.append(text(lx + 28, 80, f"ukuran {s}" + (" (default)" if s == DEFAULT_POP else ""), "t1"))
        lx += 150
    out.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(out))


def rounded_bar(cls, x, y_top, w, y_base, r=4):
    """Batang dengan ujung data membulat 4px dan pangkal rata di baseline."""
    h = y_base - y_top
    r = min(r, h / 2, w / 2)
    if h <= 0:
        return ""
    return (f'<path class="{cls}" d="M{x:.1f},{y_base:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},'
            f'{y_top:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} V{y_base:.1f} Z"/>')


def bar_panel(out, x0, top, pw, ph, title, subtitle, groups, y_max, unit_digits, y_label=None, notes=None):
    """groups: [(label, {alg: value})]. Batang HS/CSA berdampingan dengan celah 2px.
    notes: teks kecil opsional di bawah label tiap grup."""
    ticks, step = nice_ticks(0, y_max, 4)
    y_max = max(y_max, ticks[-1])

    def sy(v):
        return top + ph * (1 - v / y_max)

    out.append(text(x0, top - 30, title, "t1", size=13, weight="600"))
    out.append(text(x0, top - 14, subtitle))
    for t in ticks:
        out.append(f'<line class="grid" x1="{x0}" y1="{sy(t):.1f}" x2="{x0 + pw}" y2="{sy(t):.1f}"/>')
        out.append(text(x0 - 8, sy(t) + 4, fmt(t, decimals(step)), anchor="end",
                        extra=' style="font-variant-numeric:tabular-nums"'))
    out.append(f'<line class="axis" x1="{x0}" y1="{top + ph}" x2="{x0 + pw}" y2="{top + ph}"/>')
    slot = pw / len(groups)
    bw = min(34, slot * 0.42)
    for k, (name, vals) in enumerate(groups):
        cx = x0 + slot * (k + 0.5)
        for j, alg in enumerate(ALGS):
            x = cx - bw - 1 if j == 0 else cx + 1
            v = vals[alg]
            out.append(rounded_bar(f"f-{alg}", x, sy(v), bw, top + ph))
            out.append(text(x + bw / 2, sy(v) - 5, fmt(v, unit_digits), "t1", anchor="middle", size=11))
        out.append(text(cx, top + ph + 18, name, anchor="middle"))
        for line, note in enumerate(notes[k] if notes else []):
            out.append(text(cx, top + ph + 34 + 14 * line, note, anchor="middle", size=11))
    if y_label:
        out.append(text(x0 - 46, top + ph / 2, y_label, anchor="middle",
                        extra=f' transform="rotate(-90 {x0 - 46} {top + ph / 2})"'))


def chart_hs_vs_csa(path, data, datasets, best, timing_main):
    """timing_main: {dataset: {alg: ms}} dari eksperimen utama (berurutan), atau None."""
    width, height = 960, 430
    pw, ph, top = 250, 220, 140
    out = svg_open(width, height, "HS vs CSA",
                   "Perbandingan HS dan CSA: selisih fitness dari batas bawah pada ukuran populasi 20 dan "
                   "ukuran terbaik, serta waktu penjadwalan pada ukuran 20.")
    out.append(text(24, 32, "HS vs CSA", "t1", size=16, weight="600"))
    out.append(text(24, 52, "Kualitas = selisih fitness dari batas bawah, (F − 1) × 100%. Lebih rendah lebih "
                            "baik untuk ketiga panel. Rata-rata 10 seed, w = 0,5."))
    timing_note = "milidetik per run (eksperimen utama)" if timing_main else "milidetik per run (sweep)"
    out += legend(24, 80, [("HS", "HS"), ("CSA", "CSA")])

    def mean_of(dataset, alg, size, metric):
        return statistics.mean(values(data, (dataset, alg, size), metric))

    default = [(SHORT[d], {a: gap(mean_of(d, a, DEFAULT_POP, "fitness")) for a in ALGS}) for d in datasets]
    tuned = [(SHORT[d], {a: gap(mean_of(d, a, best[(d, a)], "fitness")) for a in ALGS}) for d in datasets]
    timing = [(SHORT[d], timing_main[d] if timing_main else
               {a: mean_of(d, a, DEFAULT_POP, "scheduling_ms") for a in ALGS}) for d in datasets]
    q_max = max(v for _, vals in default + tuned for v in vals.values()) * 1.12
    t_max = max(v for _, vals in timing for v in vals.values()) * 1.12
    bar_panel(out, 74, top, pw, ph, "Kualitas, populasi 20", "selisih dari batas bawah (%)", default, q_max, 2,
              "selisih dari batas bawah (%)")
    bar_panel(out, 384, top, pw, ph, "Kualitas, populasi terbaik", "ukuran terbaik masing-masing algoritma",
              tuned, q_max, 2, notes=[(f"HS {best[(d, 'HS')]}", f"CSA {best[(d, 'CSA')]}") for d in datasets])
    bar_panel(out, 694, top, pw, ph, "Waktu penjadwalan, populasi 20", timing_note, timing, t_max, 0)
    out.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(out))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", default="results/population/raw")
    parser.add_argument("--out", default="results/population")
    parser.add_argument("--main", default="results/simulation/summary.csv",
                        help="summary.csv eksperimen utama untuk waktu penjadwalan (berjalan berurutan)")
    args = parser.parse_args()

    data = load(args.raw)
    if not data:
        sys.exit(f"Tidak ada hasil di {args.raw}; jalankan scripts/population_sweep.sh dulu.")
    datasets = sorted({d for d, _, _ in data}, key=sort_key)
    sizes = sorted({s for _, _, s in data})
    budget = int(next(iter(data.values()))["rows"][0]["budget"])
    os.makedirs(args.out, exist_ok=True)

    # Ukuran terbaik = rata-rata fitness terkecil per (dataset, algoritma).
    mean_fit = {k: statistics.mean(values(data, k, "fitness")) for k in data}
    best = {(d, a): min((s for s in sizes if (d, a, s) in data), key=lambda s: mean_fit[(d, a, s)])
            for d in datasets for a in ALGS}
    # Peringkat rata-rata antar skenario (1 = terbaik).
    ranks = defaultdict(list)
    for d in datasets:
        for a in ALGS:
            order = sorted((s for s in sizes if (d, a, s) in data), key=lambda s: mean_fit[(d, a, s)])
            for r, s in enumerate(order, 1):
                ranks[(a, s)].append(r)

    with open(os.path.join(args.out, "summary.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset", "algorithm", "population", "runs"]
                        + [f"{m}_{x}" for m in METRICS for x in ("mean", "std")])
        for d in datasets:
            for a in ALGS:
                for s in sizes:
                    if (d, a, s) not in data:
                        continue
                    row = [d, a, s, len(data[(d, a, s)]["rows"])]
                    for m in METRICS:
                        mean, std = mean_std(values(data, (d, a, s), m))
                        row += [f"{mean:.6f}", f"{std:.6f}"]
                    writer.writerow(row)

    md = ["# Uji Ukuran Populasi HS (HMS) dan CSA (N)", "",
          "Dibuat otomatis oleh `scripts/population_analysis.py` dari `results/population/raw/`. "
          f"Budget {fmt(budget, 0)} evaluasi, w = 0,5, 10 seed yang sama (42–51) untuk setiap ukuran. "
          "CSA memakai n = N/2 dan d = N/10 (minimal 1), sama dengan rasio default N = 20, n = 10, d = 2. "
          "Nilai = rata-rata ± std; **tebal** = terbaik di kolom.", ""]

    for metric, title, digits in (("fitness", "Fitness", 4), ("makespan_s", "Makespan CloudSim (s)", 2),
                                  ("energy_kwh", "Energi CloudSim (kWh)", 4)):
        md += [f"## {title}", "",
               "| Ukuran | " + " | ".join(f"{SHORT[d]} {a}" for d in datasets for a in ALGS) + " |",
               "|:---:|" + "---:|" * (len(datasets) * len(ALGS))]
        col_best = {(d, a): min((s for s in sizes if (d, a, s) in data),
                                key=lambda s: statistics.mean(values(data, (d, a, s), metric)))
                    for d in datasets for a in ALGS}
        for s in sizes:
            cells = []
            for d in datasets:
                for a in ALGS:
                    if (d, a, s) not in data:
                        cells.append("–")
                        continue
                    cell = pm(values(data, (d, a, s), metric), digits)
                    cells.append(f"**{cell}**" if col_best[(d, a)] == s else cell)
            md.append(f"| {s}{' (default)' if s == DEFAULT_POP else ''} | " + " | ".join(cells) + " |")
        md.append("")

    md += ["## Ukuran terbaik vs default 20", "",
           "Wilcoxon signed-rank berpasangan (pasangan = seed sama), dua sisi, α = 0,05, pada fitness.", "",
           "| Skenario | Algoritma | Ukuran terbaik | Fitness terbaik | Fitness default 20 | Perubahan makespan | "
           "p-value | Kesimpulan |",
           "|:---:|:---:|:---:|---:|---:|---:|---:|:---|"]
    wilcoxon_rows = []
    for d in datasets:
        for a in ALGS:
            s = best[(d, a)]
            fb, f20 = values(data, (d, a, s), "fitness"), values(data, (d, a, DEFAULT_POP), "fitness")
            mb = statistics.mean(values(data, (d, a, s), "makespan_s"))
            m20 = statistics.mean(values(data, (d, a, DEFAULT_POP), "makespan_s"))
            if s == DEFAULT_POP:
                p, verdict = 1.0, "default sudah terbaik"
            else:
                n, wp, wm, p = wilcoxon_signed_rank(fb, f20)
                verdict = (f"{s} lebih baik secara bermakna" if p < ALPHA else "tidak berbeda bermakna")
            wilcoxon_rows.append((d, a, "best_vs_20", s, p))
            md.append(f"| {label(d)} | {a} | {s} | {pm(fb, 4)} | {pm(f20, 4)} | "
                      f"{fmt((mb - m20) / m20 * 100, 2)}% | {fmt(p, 4)} | {verdict} |")
    md.append("")

    md += ["## Peringkat rata-rata ukuran populasi", "",
           "Peringkat fitness rata-rata di tiap skenario (1 = terbaik), lalu dirata-rata atas skenario.", "",
           "| Ukuran | " + " | ".join(ALGS) + " |", "|:---:|" + "---:|" * len(ALGS)]
    for s in sizes:
        md.append(f"| {s}{' (default)' if s == DEFAULT_POP else ''} | "
                  + " | ".join(fmt(statistics.mean(ranks[(a, s)]), 2) if ranks[(a, s)] else "–" for a in ALGS)
                  + " |")
    md.append("")

    md += ["## HS vs CSA", "",
           "Wilcoxon berpasangan pada fitness (pasangan = seed sama). Selisih dari batas bawah = (F − 1) × 100%.",
           "", "| Skenario | Konfigurasi | HS | CSA | Selisih HS (%) | Selisih CSA (%) | p-value | Kesimpulan |",
           "|:---:|:---|---:|---:|---:|---:|---:|:---|"]
    for d in datasets:
        for name, hs_size, csa_size in (("ukuran 20", DEFAULT_POP, DEFAULT_POP),
                                        ("ukuran terbaik", best[(d, "HS")], best[(d, "CSA")])):
            fh, fc = values(data, (d, "HS", hs_size), "fitness"), values(data, (d, "CSA", csa_size), "fitness")
            n, wp, wm, p = wilcoxon_signed_rank(fh, fc)
            if p >= ALPHA:
                verdict = "tidak berbeda bermakna"
            else:
                verdict = "HS lebih baik" if statistics.mean(fh) < statistics.mean(fc) else "CSA lebih baik"
            wilcoxon_rows.append((d, "HS_vs_CSA", name, f"{hs_size}/{csa_size}", p))
            md.append(f"| {label(d)} | {name} (HS {hs_size}, CSA {csa_size}) | {fmt(statistics.mean(fh), 4)} | "
                      f"{fmt(statistics.mean(fc), 4)} | {fmt(gap(statistics.mean(fh)), 2)} | "
                      f"{fmt(gap(statistics.mean(fc)), 2)} | {fmt(p, 4)} | {verdict} |")
    md.append("")

    md += ["## Waktu penjadwalan (ms)", "",
           "Sweep berjalan beberapa job paralel, jadi waktu ini indikatif; jumlah evaluasi selalu sama.", "",
           "| Ukuran | " + " | ".join(f"{SHORT[d]} {a}" for d in datasets for a in ALGS) + " |",
           "|:---:|" + "---:|" * (len(datasets) * len(ALGS))]
    for s in sizes:
        md.append(f"| {s} | " + " | ".join(pm(values(data, (d, a, s), "scheduling_ms"), 1)
                                          if (d, a, s) in data else "–" for d in datasets for a in ALGS) + " |")
    md.append("")

    with open(os.path.join(args.out, "tables.md"), "w") as f:
        f.write("\n".join(md))
    with open(os.path.join(args.out, "wilcoxon.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset", "algorithm_or_test", "comparison", "population", "p_value"])
        writer.writerows(wilcoxon_rows)

    chart_fitness(os.path.join(args.out, "population_fitness.svg"), data, datasets, sizes, best)
    largest = datasets[-1]
    conv_sizes = [s for s in CONVERGENCE_SIZES if s in sizes]
    if len(conv_sizes) < 3:
        conv_sizes = sorted({min(sizes), DEFAULT_POP, max(sizes)})
    if all((largest, a, s) in data for a in ALGS for s in conv_sizes):
        chart_convergence(os.path.join(args.out, "population_convergence.svg"), data, largest, conv_sizes, budget)
    timing_main = None
    if os.path.exists(args.main):
        groups = read_summary(args.main)
        if all((d, a, "0.5") in groups for d in datasets for a in ALGS):
            timing_main = {d: {a: statistics.mean(float(r["scheduling_ms"]) for r in groups[(d, a, "0.5")])
                               for a in ALGS} for d in datasets}
    if all((d, a, DEFAULT_POP) in data for d in datasets for a in ALGS):
        chart_hs_vs_csa(os.path.join(args.out, "hs_vs_csa.svg"), data, datasets, best, timing_main)

    print("Ukuran terbaik (fitness rata-rata terkecil):")
    for d in datasets:
        print(f"  {label(d):<11} " + "  ".join(f"{a}={best[(d, a)]:<3}" for a in ALGS))
    print("Peringkat rata-rata: " + "; ".join(
        f"{a}: " + ", ".join(f"{s}={statistics.mean(ranks[(a, s)]):.2f}" for s in sizes if ranks[(a, s)])
        for a in ALGS))
    print(f"analisis -> {args.out}/tables.md, summary.csv, wilcoxon.csv, *.svg")


if __name__ == "__main__":
    main()
