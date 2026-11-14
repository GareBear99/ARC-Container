"""Host-side baseline measurements for the Lucid container-tool workshop.
Run: python3 baseline.py
Measures (all on this VM, x86_64, 4 vCPU):
 1. fork/exec floor: /bin/true spawn latency (the absolute floor for any exec)
 2. python3 / node startup (interpreter cold start inside any image)
 3. bwrap minimal-sandbox spawn (namespace+mount cost, Claude-Code-style)
 4. host file I/O loop (the baseline the container bind-mount path is judged against)
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time


def timed(fn, n=100):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return {"n": n, "mean_ms": round(statistics.mean(ts), 3),
            "p50_ms": round(ts[len(ts) // 2], 3),
            "p95_ms": round(ts[int(len(ts) * 0.95)], 3),
            "min_ms": round(ts[0], 3), "max_ms": round(ts[-1], 3)}


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, check=True)


def main():
    out = {}
    out["fork_exec_true"] = timed(lambda: run(["/bin/true"]), n=200)
    out["python3_startup"] = timed(
        lambda: run([sys.executable, "-c", "pass"]), n=50)
    try:
        out["node_startup"] = timed(
            lambda: run(["node", "-e", ""]), n=50)
    except Exception as e:
        out["node_startup"] = {"error": str(e)}
    # bwrap minimal sandbox: new mount+pid+ipc+uts+net namespaces, host /usr
    # read-only, fresh /tmp. This is the namespace cost WITHOUT a container
    # image or daemon — the floor for any sandbox spawn.
    def bwrap_true():
        run(["bwrap", "--unshare-all", "--die-with-parent",
             "--ro-bind", "/usr", "/usr",
             "--ro-bind", "/lib", "/lib",
             "--ro-bind", "/lib64", "/lib64",
             "--proc", "/proc", "--dev", "/dev",
             "--tmpfs", "/tmp",
             "/bin/true"])
    try:
        out["bwrap_spawn"] = timed(bwrap_true, n=50)
    except Exception as e:
        out["bwrap_spawn"] = {"error": str(e)}

    # Host file I/O: 1000 x 1KB files write + read, then 10MB sequential.
    tmp = tempfile.mkdtemp(prefix="lucid-io-")
    def write_1k():
        for i in range(1000):
            with open(os.path.join(tmp, f"f{i}.txt"), "w") as f:
                f.write("x" * 1024)
    def read_1k():
        for i in range(1000):
            with open(os.path.join(tmp, f"f{i}.txt")) as f:
                f.read()
    out["host_write_1000x1KB"] = timed(write_1k, n=10)
    out["host_read_1000x1KB"] = timed(read_1k, n=10)
    big = os.path.join(tmp, "big.bin")
    def write_10mb():
        with open(big, "wb") as f:
            f.write(os.urandom(10 * 1024 * 1024))
    def read_10mb():
        with open(big, "rb") as f:
            f.read()
    out["host_write_10MB"] = timed(write_10mb, n=10)
    out["host_read_10MB"] = timed(read_10mb, n=10)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
