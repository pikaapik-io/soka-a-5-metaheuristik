#!/usr/bin/env bash
# Simulasi CloudSim HS & CSA lengkap: build, sampel 5 task, S1-S3 x HS/CSA x 10 run,
# sensitivitas w, cek determinisme, verifikasi mapping Java vs Python, lalu analisis.
#
#   ./run.sh                    semua langkah (±10-15 menit)
#   ./run.sh --quick            hanya build + sampel 5 task
#   ./run.sh --algorithm HS     satu algoritma saja (HS atau CSA)
#   ./run.sh --no-sensitivity   lewati w = 0,8 dan 0,2
#   ./run.sh --no-verify        lewati verify_mapping.py (port Python lebih lambat)
#   ./run.sh --runs 10 --seed 42 --budget 10000
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

ALGORITHMS="HS CSA"
RUNS=10
SEED=42
BUDGET=10000
QUICK=0
SENSITIVITY=1
VERIFY=1
VERIFY_RUNS=3
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=1; shift ;;
    --algorithm) ALGORITHMS="${2^^}"; ALGORITHMS="${ALGORITHMS//,/ }"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --no-sensitivity) SENSITIVITY=0; shift ;;
    --no-verify) VERIFY=0; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Opsi tidak dikenal: $1 (lihat ./run.sh --help)"; exit 2 ;;
  esac
done
for alg in $ALGORITHMS; do
  case "$alg" in HS|CSA) ;; *) echo "Algoritma harus HS atau CSA, bukan $alg"; exit 2 ;; esac
done

DATASET_DIR=src/main/resources/dataset
SIM_DIR=results/simulation
WEIGHTS="0.5"
[[ "$SENSITIVITY" == "1" ]] && WEIGHTS="0.5 0.8 0.2"

echo "[1/6] Build (mvn compile)..."
mvn -q compile

echo "[2/6] Sampel 5 task (HS dan CSA, 2 run)..."
for alg in $ALGORITHMS; do
  mvn -q exec:java -Dexec.args="- $alg 2 $SEED" | grep -E '^(scheduler|\[run|  makespan|  mapping)'
done
[[ "$QUICK" == "1" ]] && { echo "Selesai (--quick)."; exit 0; }

# summary.csv dan aggregate.csv bersifat append, jadi hasil lama dipindah (tidak dihapus).
if [[ -d "$SIM_DIR" ]] && [[ -n "$(ls -A "$SIM_DIR")" ]]; then
  backup="results/simulation_previous_$(date +%Y%m%d_%H%M%S)"
  mv "$SIM_DIR" "$backup"
  echo "      hasil lama dipindah ke $backup"
fi
mkdir -p "$SIM_DIR"

echo "[3/6] Simulasi S1-S3 x {$ALGORITHMS} x w {$WEIGHTS}, $RUNS run, budget $BUDGET..."
for w in $WEIGHTS; do
  for n in 100 500 1000; do
    for alg in $ALGORITHMS; do
      log="$SIM_DIR/log_GoCJ_Dataset_${n}_${alg}_w${w}.txt"
      mvn -q exec:java -Dexec.args="$DATASET_DIR/GoCJ_Dataset_$n.txt $alg $RUNS $SEED $w $BUDGET" > "$log" 2>&1
      printf '      GoCJ %-4s %-3s w=%s  ' "$n" "$alg" "$w"
      grep -E '^  (fitness|makespan_s) ' "$log" | awk '{printf "%s=%s±%s  ", $1, $2, $4} END {print ""}'
    done
  done
done

echo "[4/6] Determinisme: ulangi run 1 S1 dengan seed yang sama..."
DET_DIR=results/determinism
mkdir -p "$DET_DIR"
for alg in $ALGORITHMS; do
  mvn -q exec:java -Dout="$DET_DIR" -Dexec.args="$DATASET_DIR/GoCJ_Dataset_100.txt $alg 1 $SEED 0.5 $BUDGET" > /dev/null
  a="$SIM_DIR/cloudlets_GoCJ_Dataset_100_${alg}_w0.5_run1.csv"
  b="$DET_DIR/cloudlets_GoCJ_Dataset_100_${alg}_w0.5_run1.csv"
  if cmp -s <(cut -d, -f1,3 "$a") <(cut -d, -f1,3 "$b"); then
    echo "      $alg: mapping sama (deterministik)"
  else
    echo "      $alg: mapping BEDA"; exit 1
  fi
done

if [[ "$VERIFY" == "1" ]]; then
  echo "[5/6] verify_mapping.py: Python vs Java, S1-S3, $VERIFY_RUNS run..."
  ( cd realworld
    for n in 100 500 1000; do
      python3 verify_mapping.py --dataset "../$DATASET_DIR/GoCJ_Dataset_$n.txt" \
        --algorithm "${ALGORITHMS// /,}" --runs "$VERIFY_RUNS" --seed "$SEED" --budget "$BUDGET"
    done ) | tee "$SIM_DIR/verify_mapping.txt"
else
  echo "[5/6] verify_mapping.py dilewati (--no-verify)"
fi

echo "[6/6] Analisis: tabel, uji Wilcoxon, kurva konvergensi..."
python3 scripts/analyze.py
echo "Selesai. Hasil: $SIM_DIR/ dan results/analysis/"
