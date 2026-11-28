#!/usr/bin/env bash
# Uji ukuran populasi (HS: HMS, CSA: N) dengan budget evaluasi yang sama.
# Setiap kombinasi ukuran x dataset x algoritma ditulis ke folder sendiri, lalu
# scripts/population_analysis.py membuat tabel dan grafik di results/population/.
#
#   scripts/population_sweep.sh                         semua ukuran (±10-15 menit)
#   scripts/population_sweep.sh --sizes "10 20 50" --runs 5 --jobs 2
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

SIZES="2 3 5 10 15 20 30 50 100"
DATASETS="100 500 1000"
ALGORITHMS="HS CSA"
RUNS=10
SEED=42
W=0.5
BUDGET=10000
JOBS=3
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sizes) SIZES="$2"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Opsi tidak dikenal: $1"; exit 2 ;;
  esac
done

RAW_DIR=results/population/raw
rm -rf "$RAW_DIR"
mkdir -p "$RAW_DIR"
mvn -q compile

jobs_file="$(mktemp)"
trap 'rm -f "$jobs_file"' EXIT
for size in $SIZES; do
  for n in $DATASETS; do
    for alg in $ALGORITHMS; do
      echo "$size $n $alg" >> "$jobs_file"
    done
  done
done
echo "Sweep: ukuran {$SIZES} x dataset {$DATASETS} x {$ALGORITHMS}, $RUNS run, w=$W, budget $BUDGET, $JOBS job paralel"

run_one() {
  local size="$1" n="$2" alg="$3"
  local out="$RAW_DIR/pop${size}_GoCJ_Dataset_${n}_${alg}"
  mkdir -p "$out"
  # Folder per kombinasi: summary.csv bersifat append, jadi job paralel tidak boleh berbagi file.
  mvn -q -Dpop="$size" -Dout="$out" exec:java \
    -Dexec.args="src/main/resources/dataset/GoCJ_Dataset_$n.txt $alg $RUNS $SEED $W $BUDGET" > "$out/log.txt" 2>&1
  rm -f "$out"/cloudlets_*.csv  # tidak dipakai analisis, dan ukurannya besar
  printf '  pop=%-3s GoCJ %-4s %-3s %s\n' "$size" "$n" "$alg" "$(grep -E '^  fitness ' "$out/log.txt" | awk '{print "fitness=" $2 "±" $4}')"
}
export -f run_one
export RAW_DIR RUNS SEED W BUDGET
MAVEN_OPTS="${MAVEN_OPTS:--Xmx768m}" xargs -P "$JOBS" -L 1 bash -c 'run_one "$@"' _ < "$jobs_file"

python3 scripts/population_analysis.py
