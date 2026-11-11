#!/usr/bin/env bash
# Real world HS & CSA: nyalakan 20 container, uji cepat, lalu S1-S3 x HS/CSA x 3 run.
#
#   ./run_realworld.sh                  semua langkah (±40-60 menit)
#   ./run_realworld.sh --quick          hanya uji cepat (--limit 20 --repeat 1)
#   ./run_realworld.sh --algorithm HS   satu algoritma saja (HS atau CSA)
#   ./run_realworld.sh --datasets "100 500" --repeat 3 --seed 42
#   ./run_realworld.sh --down           matikan container setelah selesai
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

ALGORITHMS="HS CSA"
DATASETS="100 500 1000"
REPEAT=3
SEED=42
QUICK=0
DOWN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=1; shift ;;
    --algorithm) ALGORITHMS="${2^^}"; ALGORITHMS="${ALGORITHMS//,/ }"; shift 2 ;;
    --datasets) DATASETS="$2"; shift 2 ;;
    --repeat) REPEAT="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --down) DOWN=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Opsi tidak dikenal: $1 (lihat ./run_realworld.sh --help)"; exit 2 ;;
  esac
done

echo "[1/5] Cek Docker..."
docker version --format 'Docker server {{.Server.Version}}' || { echo "Docker daemon belum jalan."; exit 1; }
if [[ -n "$(docker ps -q --filter name=kpb_vm)" ]]; then
  echo "Container KPB (kpb_vm*) masih jalan dan memakai port 9100-9119 yang sama."
  echo "Matikan dulu, misalnya: docker stop \$(docker ps -q --filter name=kpb_vm)"
  exit 1
fi

echo "[2/5] Nyalakan 20 container (docker compose up -d)..."
docker compose up -d
python3 - <<'EOF'
import json, time, urllib.request
deadline = time.time() + 90
for port in range(9100, 9120):
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                json.loads(r.read())
            break
        except OSError:
            if time.time() > deadline:
                raise SystemExit(f"Container di port {port} tidak siap dalam 90 detik")
            time.sleep(1)
print("      20/20 worker siap")
EOF

echo "[3/5] Uji cepat: 20 task pertama, 1 run..."
first="${ALGORITHMS%% *}"
python3 meta_realworld.py --algorithm "$first" --limit 20 --repeat 1 --quiet --out results_demo | tail -n 3
[[ "$QUICK" == "1" ]] && { echo "Selesai (--quick). Folder results_demo/ boleh dihapus."; exit 0; }

echo "[4/5] Skenario: GoCJ {$DATASETS} x {$ALGORITHMS} x $REPEAT run (summary/aggregate bersifat append)..."
mkdir -p results
for n in $DATASETS; do
  for alg in $ALGORITHMS; do
    echo "== GoCJ $n task, $alg =="
    python3 meta_realworld.py --algorithm "$alg" --dataset "../src/main/resources/dataset/GoCJ_Dataset_$n.txt" \
      --repeat "$REPEAT" --seed "$SEED" --quiet | tee "results/log_GoCJ_Dataset_${n}_${alg}.txt"
  done
done

echo "[5/5] Analisis..."
( cd .. && python3 scripts/analyze.py )
if [[ "$DOWN" == "1" ]]; then docker compose down; fi
echo "Selesai. Hasil: realworld/results/ dan results/analysis/tables.md (bagian 7)"
