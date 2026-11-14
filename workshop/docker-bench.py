"""Docker measurements for the Lucid container-tool workshop.
Run AFTER dockerd is up: python3 docker-bench.py
Assumes images already pulled (see pull.sh) or pulls them itself.
Reports: image sizes, cold-start (docker run --rm true), exec latency
(docker exec into a warm container), file I/O inside the container,
bind-mount I/O, and the same under --memory=512m --cpus=1 caps.
"""
import json
import statistics
import subprocess
import sys
import time


def sh(cmd, check=True):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, check=check)


def timed(fn, n):
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


def image_size(img):
    r = sh(["docker", "images", "--format", "{{.Size}}", img])
    return r.stdout.strip()


def main():
    out = {}
    out["images"] = {}
    for img in ["alpine:3.21", "cgr.dev/chainguard/wolfi-base:latest",
                "lucid-agent:alpine", "lucid-agent:wolfi"]:
        try:
            out["images"][img] = image_size(img)
        except subprocess.CalledProcessError as e:
            out["images"][img] = f"missing: {e.stderr.strip()[:80]}"

    # Cold start: create + start + exit, image already present.
    for img in ["alpine:3.21", "lucid-agent:alpine", "lucid-agent:wolfi"]:
        try:
            out[f"cold_start_{img}"] = timed(
                lambda i=img: sh(["docker", "run", "--rm", "--network=none",
                                  i, "true"]), n=20)
        except subprocess.CalledProcessError as e:
            out[f"cold_start_{img}"] = {"error": e.stderr.strip()[:200]}

    # Warm exec latency: one long-lived container, docker exec true x100.
    for img, name in [("alpine:3.21", "warm-alpine"),
                      ("lucid-agent:alpine", "warm-lucid-alpine"),
                      ("lucid-agent:wolfi", "warm-lucid-wolfi")]:
        try:
            sh(["docker", "run", "-d", "--rm", "--network=none",
                "--name", name, img, "sleep", "infinity"])
            out[f"exec_{img}"] = timed(
                lambda n=name: sh(["docker", "exec", n, "true"]), n=100)
        except subprocess.CalledProcessError as e:
            out[f"exec_{img}"] = {"error": e.stderr.strip()[:200]}
        finally:
            sh(["docker", "stop", name], check=False)

    # File I/O inside the warm container (python bench, copied in).
    # Uses the lucid-agent:alpine image (has python3) if present.
    io_script = (
        "import os,time,statistics\n"
        "d='/tmp/iobench'; os.makedirs(d, exist_ok=True)\n"
        "t0=time.perf_counter()\n"
        "for i in range(1000):\n"
        "    open(f'{d}/f{i}.txt','w').write('x'*1024)\n"
        "w=(time.perf_counter()-t0)*1000\n"
        "t0=time.perf_counter()\n"
        "for i in range(1000):\n"
        "    open(f'{d}/f{i}.txt').read()\n"
        "r=(time.perf_counter()-t0)*1000\n"
        "print(f'write1000={w:.1f}ms read1000={r:.1f}ms')\n")
    try:
        sh(["docker", "run", "-d", "--rm", "--network=none", "--name",
            "iobench", "lucid-agent:alpine", "sleep", "infinity"])
        sh(["docker", "exec", "iobench", "sh", "-c",
            f"cat > /tmp/iobench.py <<'PY'\n{io_script}PY"])
        r = sh(["docker", "exec", "iobench", "python3", "/tmp/iobench.py"])
        out["container_io_tmpfs"] = r.stdout.strip()
    except subprocess.CalledProcessError as e:
        out["container_io_tmpfs"] = f"error: {e.stderr.strip()[:200]}"
    finally:
        sh(["docker", "stop", "iobench"], check=False)

    # Bind-mount I/O: host dir mounted at /work, same script.
    try:
        subprocess.run(["mkdir", "-p", "/tmp/hostbench"], check=True)
        sh(["docker", "run", "-d", "--rm", "--network=none", "--name",
            "iobind", "-v", "/tmp/hostbench:/work",
            "lucid-agent:alpine", "sleep", "infinity"])
        io_bind = io_script.replace("d='/tmp/iobench'", "d='/work'")
        sh(["docker", "exec", "iobind", "sh", "-c",
            f"cat > /tmp/iobench.py <<'PY'\n{io_bind}PY"])
        r = sh(["docker", "exec", "iobind", "python3", "/tmp/iobench.py"])
        out["container_io_bindmount"] = r.stdout.strip()
    except subprocess.CalledProcessError as e:
        out["container_io_bindmount"] = f"error: {e.stderr.strip()[:200]}"
    finally:
        sh(["docker", "stop", "iobind"], check=False)

    # Capped run (the 8 GB Mac budget, simulated): 512 MB + 1 CPU.
    try:
        out["cold_start_capped_512m_1cpu"] = timed(
            lambda: sh(["docker", "run", "--rm", "--network=none",
                        "--memory=512m", "--cpus=1",
                        "lucid-agent:alpine", "true"]), n=20)
        sh(["docker", "run", "-d", "--rm", "--network=none", "--name",
            "warm-capped", "--memory=512m", "--cpus=1",
            "lucid-agent:alpine", "sleep", "infinity"])
        out["exec_capped_512m_1cpu"] = timed(
            lambda: sh(["docker", "exec", "warm-capped", "true"]), n=100)
    except subprocess.CalledProcessError as e:
        out["capped"] = {"error": e.stderr.strip()[:200]}
    finally:
        sh(["docker", "stop", "warm-capped"], check=False)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
