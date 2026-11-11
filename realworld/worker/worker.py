#!/usr/bin/env python3
"""Worker yang berjalan di setiap container ("VM").

Meniru CloudletSchedulerTimeShared dari CloudSim:
  * VM punya PES proses ("PE"). Satu task hanya dikerjakan oleh satu PE pada satu
    waktu, sehingga kecepatannya maksimal MIPS per PE (sama seperti cloudlet 1 PE).
  * Semua task dalam batch aktif bersamaan dan bergiliran (round-robin per chunk)
    di PE yang tersedia, jadi kapasitas VM dibagi rata ke semua task.
  * Tiap PE membatasi dirinya ke PE_SHARE CPU (porsi MIPS per PE); total CPU
    container tetap dibatasi kernel lewat cpu_quota di docker-compose.yml.

Endpoint:
  GET  /health -> {"vm": ..., "pes": ..., "stream": true, "status": "ok"}
  POST /batch  {"tasks": [{"id": i, "iterations": n}, ...]}
               -> streaming NDJSON, satu baris per task begitu task selesai:
                  {"id": i, "finish": monotonic}
                  lalu baris terakhir {"vm": ..., "cpu_s": detik CPU cgroup}
"""

import json
import multiprocessing as mp
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

VM_NAME = os.environ.get("VM_NAME", "vm")
PORT = int(os.environ.get("PORT", "8000"))
PES = int(os.environ.get("PES", "1"))
PE_SHARE = float(os.environ.get("PE_SHARE", "1.0"))  # CPU per PE
CHUNK = int(os.environ.get("CHUNK", "50000"))        # iterasi per giliran
CPU_STAT_V2 = "/sys/fs/cgroup/cpu.stat"                     # cgroup v2: usage_usec
CPU_USAGE_V1 = "/sys/fs/cgroup/cpuacct/cpuacct.usage"       # cgroup v1: nanodetik


def burn(iterations):
    """Pekerjaan CPU deterministik (LCG), tanpa sleep."""
    x = 1
    for _ in range(iterations):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    return x


def cgroup_cpu_seconds():
    """Total CPU yang dipakai container (semua proses), dari cgroup."""
    try:
        with open(CPU_STAT_V2) as f:
            for line in f:
                key, value = line.split()
                if key == "usage_usec":
                    return int(value) / 1e6
    except OSError:
        pass
    try:
        with open(CPU_USAGE_V1) as f:
            return int(f.read()) / 1e9
    except OSError:
        return 0.0


def pe_loop(work_q, done_q):
    """Satu PE: ambil giliran task, kerjakan satu chunk, kembalikan ke antrean."""
    while True:
        item = work_q.get()
        if item is None:
            return
        task_id, remaining = item
        n = min(CHUNK, remaining)
        wall, cpu = time.monotonic(), time.process_time()
        burn(n)
        # Batasi PE ke PE_SHARE CPU: chunk yang selesai terlalu cepat ditahan.
        need = (time.process_time() - cpu) / PE_SHARE - (time.monotonic() - wall)
        if need > 0:
            time.sleep(need)
        if remaining - n > 0:
            work_q.put((task_id, remaining - n))
        else:
            done_q.put((task_id, time.monotonic()))


# Proses PE dibuat sekali saat container start (bukan per batch), karena overhead
# fork akan sangat mahal di container dengan kuota CPU kecil (V1 = 0,1 CPU).
WORK_Q = None
DONE_Q = None


def start_pes():
    global WORK_Q, DONE_Q
    WORK_Q, DONE_Q = mp.Queue(), mp.Queue()
    for _ in range(PES):
        mp.Process(target=pe_loop, args=(WORK_Q, DONE_Q), daemon=True).start()


def run_batch(tasks):
    """Masukkan semua task ke antrean PE, lalu yield (id, waktu selesai) satu per satu."""
    for task in tasks:
        WORK_Q.put((task["id"], max(1, int(task["iterations"]))))
    for _ in tasks:
        yield DONE_Q.get()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._reply({"vm": VM_NAME, "pes": PES, "pe_share": PE_SHARE, "stream": True, "status": "ok"})
        else:
            self._reply({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/batch":
            self._reply({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        # HTTP/1.0 tanpa Content-Length: setiap baris langsung terkirim ke runner,
        # sehingga runner bisa menampilkan cloudlet yang selesai secara real-time.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        cpu_before = cgroup_cpu_seconds()
        for task_id, t in run_batch(request.get("tasks", [])):
            self._send_line({"id": task_id, "finish": t})
        self._send_line({"vm": VM_NAME, "cpu_s": cgroup_cpu_seconds() - cpu_before})

    def _send_line(self, payload):
        self.wfile.write((json.dumps(payload) + "\n").encode())
        self.wfile.flush()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    mp.set_start_method("fork")
    start_pes()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
