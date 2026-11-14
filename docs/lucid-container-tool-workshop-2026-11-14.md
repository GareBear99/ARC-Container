# Lucid Linux container tool — workshop (design + research)

Date: 2026-11-14. Status: DESIGN ONLY — no code, no builds, no installs, no Mac touch.
Goal (Gary): fastest and best in the world, working on an image of lightning fast light speeds.
The image is the centerpiece: minimal, instant, light.

## 0. What this is (grounded)

Lucid's agent (terminal Agent mode) already has a tool registry. Verified in
`~/workspace/lucid-terminal/src/lib/agentToolsImpl.ts`: **13 file tools**
(`read_file`, `read_currently_open_file`, `ls`, `file_glob_search`,
`grep_search`, `codebase_search`, `find_symbol`, `go_to_definition`,
`find_references`, `create_new_file`, `multi_edit`, `fix_diagnostics`,
`view_diff`). They run against the user's real filesystem/shell today, via a
`ctx.host` interface (`readFile`/`writeFile`/…).

Two deliberate gaps in that file, stated in the code itself:

- `run_terminal_command` was **deliberately NOT built** — "the terminal tool
  needs the terminal-security shape (Continue's `packages/terminal-security/`
  — shell parsing, privilege escalation, chaining) + a policy Gary has not
  set. A shell tool without that shape is a hole, not a tool."
- `fetch_url_content` / `search_web` excluded — "The loop is local only."
- `delete` / `rename` excluded — destructive; land with the review UI.

**The container tool is the missing shape.** The container is the isolation
boundary the shell tool was waiting for. The design below gives the registry
a container backend: the same tool calls, executed inside a per-session Linux
container instead of on the host — and it unlocks `run_terminal_command`,
because inside the container a shell command can only touch the mounted
workspace.

Permission model (Zed slice, verified in `agentPolicy.ts`): `decideToolPolicy`
runs before every tool call; per-tool overrides + path rules; **deny beats
auto**; absolute paths outside the workspace are never allowed. The container
adds three more gates on top: network, mount scope, resource caps.

Guest rule: guest sessions are blank slate, everything wiped on leave. A guest
agent session's container is destroyed on leave — same rule, now with a
filesystem to destroy.

Driving intelligence: local (LLMBuilder base). Tool calls cost 0 SP / 0
network when local. The container keeps that true: the sandbox is on the
same machine, so a tool call is local IPC, never a cloud round-trip.

Target machine (Gary's Mac): Intel x86_64 Core i5-8500B, 8 GB RAM, macOS.
The runtime is OPEN — not decided, not Docker by default. Candidates:
Docker Desktop, Lima/Colima, Podman machine, a microVM via Apple's
Virtualization.framework, macOS-native sandboxing (sandbox-exec/Seatbelt),
or no Linux container at all. Docker Desktop is the heaviest option on an
8 GB Intel Mac, so it has something to prove, not a head start. Fastest
wins, justified with measurements on Gary's Mac (§2d, §5b). Whatever the
runtime, the hard constraints are the same: the machine has 8 GB, and the
mount path (how the workspace reaches the sandbox) is where the latency
lives.

## 1. How Claude, ChatGPT, and Grok do it now

Sources: web search 2026-11-14 (see §7 for URLs). All three converge on the
same shape: one sandboxed Linux environment per session, a small tool surface,
workspace-only filesystem, network off by default, resource limits, destroyed
(or checkpointed) at session end. They differ in where the sandbox lives and
how much of the machine the agent can touch.

### 1a. ChatGPT — code interpreter / Advanced Data Analysis (OpenAI)

- Sandbox container on OpenAI's side, per conversation/thread. Python
  (stateful Jupyter/REPL); since Jan 2026 also Bash and Node.js, and
  `pip install` / `npm install` work through an OpenAI proxy; a separate
  `container.download` tool fetches a file from a URL into the container.
- No general outbound network. Preinstalled: pandas, numpy, matplotlib,
  scipy, scikit-learn, Pillow, openpyxl, PyPDF2, etc.
- Files the user uploads land at `/mnt/data/` inside the sandbox (upload
  step, 10 files / 512 MB each max). Files live for the session, then are
  garbage collected. CPU only, no GPU.
- Lifetime: API container expires after 20 minutes unused; the ChatGPT env
  expires after 13 hours of inactivity. API pricing: $0.03 per session
  (1 hour of activity within a thread).

### 1b. Claude — code execution tool + Cowork + Claude Code sandbox

- **API code execution tool** (server tool, Anthropic hosts the runtime):
  `code_execution_20250825` (baseline: bash + file ops),
  `code_execution_20260120` (adds REPL state persistence + programmatic
  tool calling from inside the sandbox), `code_execution_20260521` (same
  runtime, tool description surfaces a 90-second wall-clock limit per
  Python cell). Sandbox: Linux x86_64, Python 3.11, **1 CPU, 5 GiB RAM,
  5 GiB disk**. No internet, no runtime package installs. Preloaded:
  pandas, numpy, scipy, scikit-learn, statsmodels, matplotlib, seaborn,
  openpyxl, pypdf, sympy, mpmath + CLI tools ripgrep, fd, sqlite, 7zip.
  Lifetime: checkpointed after ~5 min idle; restorable by container ID for
  30 days. Billing: free when the request also uses the web tools,
  otherwise by execution time (5-min minimum per session; 1,550 free
  hours/org/month, then $0.05/hour/container).
- **Claude Cowork** (Oct 2026): moved from a local VM (Apple
  Virtualization.framework on macOS, Hyper-V on Windows, per-session user
  isolation, egress filtering, syscall restrictions) to cloud sandboxes —
  per-session, destroyed at end, no access to private / link-local / cloud
  metadata addresses by default, all outbound traffic through a mandatory
  proxy the sandbox cannot reconfigure, only allow-listed destinations.
  Local files/browser go over an Anthropic-brokered connection to the
  desktop app.
- **Claude Code local sandbox** (`/sandbox`): Seatbelt on macOS,
  bubblewrap + socat on Linux/WSL2. Shell commands can write only in the
  project + a temp dir; every connection goes through a local proxy with an
  allow-list. BUT: the file tools (Read/Edit/Write) run OUTSIDE the
  sandbox, and by default the sandbox can still read `~/.ssh` and
  `~/.aws/credentials`. `sandbox.failIfUnavailable` makes it refuse to
  run unsandboxed. Anthropic's own summary: "Sandboxing reduces risk but
  is not a complete isolation boundary."

### 1c. Grok — code execution + Grok Build CLI (xAI)

- **Grok 4 code execution**: stateful Python 3.12.3 REPL in a containerized
  environment (overlayfs, 9p mounts, xAI "Hades" container tools;
  fingerprint consistent with Kubernetes / Cloud Run / Firecracker-style
  VM). No internet except a Polygon Finance proxy; no `pip install`.
  Preinstalled: numpy, scipy, pandas, matplotlib, sympy, torch, rdkit,
  biopython, astropy, qutip, PuLP, statsmodels, networkx, pygame, chess.
  Per-conversation isolated sandbox (filesystem + REPL).
- **Grok 4.3 Beta**: persistent remote sandbox, working dir
  `/home/workdir/artifacts`, internet disabled, `pip`/`npm`/`go`/`cargo`
  available and pre-configured to function without external internet.
- **Grok Build CLI** (local agent, Apache-2.0): tools run locally by
  default; sandbox is OPT-IN (Landlock on Linux, Seatbelt on macOS) with
  profiles `workspace` / `read-only` / `strict`; permission modes Ask /
  Auto / Always-approve, allow + deny rules, **deny always wins**; git
  worktrees isolate parallel sessions; subagents are independent child
  sessions.

### 1d. Comparison — and where Lucid beats them

| | ChatGPT (OpenAI) | Claude (Anthropic) | Grok (xAI) | **Lucid (proposed)** |
|---|---|---|---|---|
| Where it runs | OpenAI cloud container | Anthropic cloud container / Cowork cloud sandbox | xAI cloud container ("Hades") | **On the user's own Mac (local VM or macOS-native sandbox — runtime open, §2d)** |
| Per-session isolation | Per thread; expires 20 min idle / 13 h | Per session; checkpoint 5 min idle, restorable 30 d | Per conversation | **Per agent session; destroyed at session end (guest rule)** |
| Tool surface | Python REPL + Bash + Node; `container.download` | Bash + file ops; REPL state; programmatic tool calls from inside | Python 3.12 REPL; file ops in 4.3 sandbox | **The existing 13 file tools + `run_terminal_command` (unlocked by the container)** |
| Filesystem | Uploads to `/mnt/data/`; 10 files / 512 MB cap | Files API upload; 5 GiB workspace | `/home/workdir/artifacts` | **The project folder itself, bind-mounted — no upload step, no file cap** |
| Network | Off (pip/npm via proxy; download tool) | Off; Cowork: mandatory proxy, allow-list only | Off (Polygon proxy only) | **Off by default; allow-listed host proxy only via the permission model** |
| Limits | CPU only; session caps | 1 CPU / 5 GiB RAM / 5 GiB disk; 90 s per cell | Container limits (unpublished) | **512 MB–1 GB RAM, 1–2 CPU per container; VM capped at 2–3 GB on 8 GB Mac** |
| Cost / latency | $0.03/session; cloud round-trip per call | $0.05/hour after allowance; cloud round-trip | Cloud round-trip | **0 SP, 0 network, 0 dollars — local IPC on the same machine** |
| Brain | Cloud model | Cloud model | Cloud model | **Local driving intelligence (LLMBuilder base)** |

**Where Lucid wins, honestly:**

1. **No cloud hop.** Every one of the three pays a network round-trip per
   tool call, plus a session fee or an hourly meter. Ours is local IPC on
   the same machine: the tool call never leaves the Mac.
2. **Warm, not rented.** Their sandboxes expire on a vendor schedule
   (20 min idle, 5 min checkpoint, 13 h). Ours is warm for exactly the
   agent session and dies with it — the lifecycle matches the work, not a
   billing clock.
3. **No upload step.** They make the model work on copies of files the
   user uploaded into the sandbox. Ours mounts the project itself — the
   agent edits the real files, in place, with the same review UI (Zed
   Keep/Reject) on top.
4. **The brain is local too.** Their sandboxes are fast, but the model
   driving them is a cloud API call away. Our driving intelligence is
   already on the machine, so the whole loop — think, call, execute, read
   — is local.
5. **The permission model is already ours.** Deny-beats-auto, path rules,
   per-tool overrides — the container adds gates to a model that exists,
   instead of bolting a sandbox onto a prompt.

**Where Lucid is behind, honestly:** the three have hardened multi-tenant
infrastructure, egress proxies, syscall filters, and years of sandbox
escaping attempts behind them. A local container is only as good as
the daemon, the mount discipline, and the caps around it. Our edge is
speed and locality, not a stronger isolation proof. The design below
compensates with the narrowest possible mount (one folder), no network by
default, non-root user, and destroy-on-leave — but it does not claim
cloud-grade multi-tenant isolation, because it isn't that.

## 2. The image (the centerpiece)

### 2a. Candidate bases — measured sizes (published, Sep 2026)

Measured by jacar.es (Docker 29.5.2, same Go + Flask apps on each base,
Sep 2026); DHI numbers from Docker's hardened-image catalog:

| Base | Compressed (static Go app) | Compressed (Flask app) | C library | Shell? | CVE posture (Trivy) |
|---|---|---|---|---|---|
| `scratch` | 0 MB | — (no runtime) | none | no | — |
| `distroless/static` | 3.1 MB | — | glibc | **no** | ~0 |
| `chainguard/static` | 3.3 MB | — | glibc | no | ~0 |
| `alpine:3.24` | 6.7 MB | 24.2 MB | **musl** | yes (`sh`) | 0–3 |
| `wolfi-base` | 11.9 MB | 36.2 MB | glibc | optional | 0–3 |
| `distroless/python3` | — | 28.4 MB | glibc | **no** | ~5 |
| `dhi.io/python:3.12` | — | ~25 MB | glibc | no | 0 typical |
| `debian:slim` | 32.7 MB | 49.8 MB | glibc | yes | 50–204 |
| `node:24-alpine` | — | ~160 MB | musl | yes | 0–5 |
| `node:24-slim` | — | ~250 MB | glibc | yes | 20–40 |
| `node:24` (full) | — | ~1.1 GB | glibc | yes | 80–150+ |

**The musl trap (measured, not theoretical):** on Alpine, Python 3.14 +
torch 2.14 / duckdb 1.5.6 / onnxruntime 1.30 have NO musllinux wheels —
duckdb tries to compile and fails. Alpine is the smallest number on the
page and the wrong base for anything that compiles native extensions.
The agent runs user projects; user projects compile native extensions.
Alpine is out as the default for that reason alone.

**Distroless is out for the opposite reason:** no shell, no package
manager. An agent sandbox that cannot run a shell is not an agent
sandbox — it is a serving image. Distroless is the wrong shape here.

**Recommendation: Wolfi.** glibc (no musl trap), ~12 MB base, 0–3 CVEs,
`apk` available, Chainguard rebuilds daily, signed packages. Pin by
digest (Chainguard's free catalog only serves `latest` tags). Alpine is
the fallback if Wolfi's rolling tags ever bite — same `apk` workflow,
same Dockerfile shape, one-line base swap.

### 2b. The image spec — `lucid-agent:slim` (default)

```
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:<pinned>
RUN apk add --no-cache \
      nodejs npm \        # Lucid's runtime; the agent's tools are TS/Node
      python3 \           # scripts, data work, the second runtime
      git \               # the agent diffs, branches, and reads history
      ripgrep \           # grep_search / codebase_search, native speed
      ca-certificates tzdata
RUN adduser -D -u 10001 agent
USER agent
WORKDIR /work
```

Contents, and only these: node 24 + npm, python 3.13, git, ripgrep,
CA certs, tzdata, a non-root user, `/work`. No package manager at
runtime? Keep `apk` present — the agent installs project dependencies
through it, but only when the permission model allows network, and only
into the workspace. No compilers in the slim image (no gcc/make — a
project that needs to compile native code gets the `full` image or a
project layer; the slim image stays slim).

**Size targets (targets, NOT results — the builds below will confirm):**
slim ≤ 200 MB on disk, ≤ 80 MB compressed pull. `lucid-agent:full`
(opt-in per project: the data-science stack — pandas, numpy, matplotlib
— plus build tools) ≤ 600 MB on disk. Layer strategy, ordered by change
frequency (least-changing at the bottom, so pulls stay incremental):
base OS → runtimes (node + python) → tools (git, rg, certs) → Lucid
sidecar (the resident daemon, §3 — changes most, top layer). Four to
five layers total.

### 2c. Pre-warm / warm pool

- The runtime (VM or sandbox backend) starts **once** — at Lucid launch
  (or first agent use), not per session. VM start times differ wildly by
  runtime (see §2d); either way the cost is amortized across the whole
  Lucid session, never per agent session. If the winning runtime is
  macOS-native sandboxing, there is no VM start at all — that is part of
  why it is in the shootout.
- The image is pulled **once**, on first install (or on Lucid first
  run), and cached. Pull is the only network the image ever needs.
- One warm container per agent session, started when Agent mode flips
  (or lazily on the first agent tool call — open question, §6), kept
  warm for the session, destroyed at session end. One container, not a
  pool: on an 8 GB Mac a pool of idle containers is waste.
- **The resident sidecar is the speed trick.** A tiny daemon lives
  inside the warm container (top layer, §3). Tool calls go to the
  sidecar over the exec channel instead of spawning a fresh interpreter
  per call — because measured node startup is ~88 ms and python ~27 ms
  (§4), and spawning per call would pay that on every tool call. The
  sidecar holds the interpreters warm; an exec becomes IPC, not a
  process spawn.
- Lazy loading (eStargz / SOCI / Nydus): real and large — SOCI cuts a
  1.3 GB image pull from 20 s to ~2.8 s (7.4×), and lazy cold start is
  size-independent (~17 s regardless of 2–140 GB). But: it needs a
  snapshotter the Mac runtimes do not ship by default, and pull is
  76% of container start time only for BIG images — ours is ≤200 MB,
  where a plain pull is already seconds. Verdict: **not for v1**.
  Revisit if the `full` image grows past ~500 MB. The win for us is the
  warm container, not the lazy pull.

### 2d. The runtime is OPEN (course correction, 2026-11-14)

Gary asked "why are we using docker". Answer: we aren't — Docker was
named only as one familiar way to get a Linux VM on a Mac. It is NOT
decided and NOT the default. The runtime is fully open, and Docker
Desktop is the heaviest option on an 8 GB Intel Mac, so it has something
to prove, not a head start. **Fastest wins, justified with measurements
on Gary's Mac.**

| Runtime | What it is | VM? | Idle RAM (published) | Start (published) | Notes for Lucid |
|---|---|---|---|---|---|
| Docker Desktop | Docker Engine + GUI in a HyperKit VM (Intel) | yes | 2–4 GB | 10–45 s | Most familiar; heaviest; the one to beat |
| Lima / Colima | QEMU (+HyperKit accel) Linux VM + Docker-compatible CLI | yes | ~500 MB | 3–15 s | Open source; `colima start --cpu 2 --memory 2`; smallest VM footprint |
| Podman machine | QEMU VM + Podman (daemonless, rootless) | yes | ~500 MB (est.) | ~5–15 s (est.) | Same VM shape as Lima; different CLI; rootless by design |
| MicroVM (Virtualization.framework) | Minimal Linux VM via Apple's framework (OrbStack-style; vfkit/krunkit) | yes, tiny | ~200–500 MB (est.) | ~1–2 s (Apple-Silicon-measured; Intel unmeasured) | The lightest VM shape; Intel numbers unmeasured — must be measured, not assumed |
| macOS-native sandbox (Seatbelt / sandbox-exec) | OS-level boundary, no VM, no Linux | **no** | **0 MB** | **~0 s** | What Claude Code uses on macOS; the fastest possible; weakest isolation (reads of `~/.ssh` possible by default; file tools run outside it; the agent runs macOS binaries, not Linux) |
| No container at all | The agent's tools run on the host, gated only by the permission model | no | 0 MB | 0 s | The status quo (what the registry does today). The container exists to beat this on safety; if a runtime cannot beat it on speed, it loses. |

Decision criteria (measured on Gary's Mac, §5b): cold start, exec
latency (p95), memory at idle / warm / executing, disk, mount I/O — and
one hard gate: it must run on Intel and fit in 8 GB with Lucid + the
model running. The winner is the fastest that passes the gate. If the
native sandbox wins on speed but fails the isolation bar Gary sets, that
is his call (§6) — speed decides among the runtimes that pass, not
instead of the bar.

What the Docker attempt on this VM proved (see §4b): the daemon runs
and pulls work, but no container can start in this nested VM (overlay
mount blocked, cgroup controllers absent). So Docker has no measured
numbers from this workshop at all — another reason it gets no head start.

## 3. Architecture

### 3a. Lifecycle (one container per agent session)

```
idle → starting → warm → executing → destroyed
          ↑_________|          (destroyed at session end, always;
                                guest: destroyed on leave, no exceptions)
```

- **starting:** the runtime starts one container with the session's caps
  + mounts + no network. Image already cached (or, for the native
  sandbox, there is no image — the sandbox just starts).
- **warm:** the sidecar is up and answering a health check. The agent
  loop can call tools.
- **executing:** each tool call is one exec into the warm container
  (or one message to the sidecar). The loop's existing receipts
  (`ToolCallRecord`) carry the result.
- **destroyed:** the runtime destroys the container at session end. The container's
  writable layer is deleted with it — nothing the agent did inside the
  container survives except what it wrote into the mounted workspace,
  which is exactly the point (edits land in the project, via Keep/Reject
  review, like every other agent edit).

### 3b. Tool surface — plugs into the existing registry

The registry does not change. The `ctx.host` interface gains a container
backend: `readFile`/`writeFile`/glob/grep/search/symbols/diff run inside
the container against the mounted workspace, and the new
`run_terminal_command` runs inside it too. The tool pass
(`decideToolPolicy` → execute → receipt) is unchanged; the container is
where "execute" happens, not a new pass.

| Tool | In-container behavior |
|---|---|
| `read_file`, `read_currently_open_file`, `ls`, `file_glob_search`, `grep_search`, `codebase_search`, `find_symbol`, `go_to_definition`, `find_references` | Read-only against `/work` (the mounted workspace). No host paths. |
| `create_new_file`, `multi_edit`, `fix_diagnostics`, `view_diff` | Write into `/work` only; every write still goes through Keep/Reject review in the feed. |
| `run_terminal_command` (NEW, unlocked by the container) | Shell inside the container, cwd `/work`, via the sidecar. Shell parsing + privilege rules from the terminal-security shape; chaining allowed only inside the container. |
| Lifecycle (NEW, not model-facing) | `sandbox.start` / `sandbox.stop` / `sandbox.status` — host-side only, never exposed to the model. |

### 3c. Mounts — the narrowest possible

- **One bind mount:** the active workspace folder → `/work`, read-write.
  That is the only host path the container ever sees.
- **Never mounted:** home (`~`), `~/.ssh`, `~/.aws`, the keychain,
  other profiles' folders, the Lucid app data, `/Users/gary` itself.
  The container cannot read the user's credentials because they are not
  in its filesystem. (Claude's sandbox leaves `~/.ssh` readable by
  default — ours does not, because we mount one folder, not the home
  directory with a write fence.)
- `/tmp` inside the container is a `tmpfs` (gone with the container).
- Everything else in the image is read-only by default
  (`--read-only` + tmpfs for the writable spots the runtimes need).

### 3d. Network — off by default

- Container starts with `--network=none`. No DNS, no egress.
- If the permission model allows network for a tool (per-tool `auto`,
  never by default), traffic goes through a **host-side allow-listed
  proxy** — the same shape as Claude Cowork's mandatory proxy: the
  container cannot reconfigure or bypass it, only allow-listed
  destinations are reachable. The proxy lives on the host, not in the
  container.
- Package installs (`apk` / `pip` / `npm`) only work through that
  proxy, only when allowed, only into the workspace.

### 3e. Caps — the 8 GB Mac budget

| Resource | Container cap | VM cap (whole runtime) |
|---|---|---|
| Memory | 512 MB default, 1 GB max per session | 2 GB for the whole runtime backend — leaves ~6 GB for macOS + Lucid + the agent (exact split depends on the winning runtime, §2d) |
| CPU | 1 vCPU default, 2 max | 2 vCPU (of the i5's 6 cores) |
| Disk (writable layer) | 1 GB max (writable-layer cap, expressed per-runtime) | image cache pruned: one slim + one full max |
| Processes | 256 max (per-runtime pid limit) | — |
| Time | per-exec timeout (default 120 s; the loop already caps reflections at 3) | — |

Rationale: the Mac has 8 GB total and Lucid + the model + the OS need
most of it. The container is a sandbox for running commands, not a
build farm. A runaway `npm install` or test suite inside 512 MB fails
fast and visibly instead of eating the machine.

### 3f. Observability — what the agent did

- Every exec is already a `ToolCallRecord` in the agent loop (tool name,
  args, result, duration). The container adds: exit code, stdout/stderr
  truncation, and the container ID. No new log system — the loop's
  receipts ARE the audit trail.
- The feed shows container output as tool results, same as host tools.
- Container logs are kept for the session and destroyed
  with it. Nothing about the container persists past the session — the
  guest rule and the session rule are the same rule.

## 4. Measurements (this VM, 2026-11-14)

Machine: Linux x86_64, 4 vCPU, ~8 GB RAM, 7 GB free disk. No container
runtime was installed at the start of this workshop; static Docker 29.1.3
binaries were installed on this VM to measure with (VM only — never on
Gary's Mac). See §4b for what happened.

### 4a. Host baselines (measured)

| Measurement | mean | p50 | p95 |
|---|---|---|---|
| fork/exec `/bin/true` (n=200) | 0.87 ms | 0.84 ms | 1.21 ms |
| `python3 -c pass` startup (n=50) | 26.8 ms | 26.2 ms | 31.4 ms |
| `node -e ''` startup (n=50) | 87.7 ms | 85.0 ms | 98.5 ms |
| host write 1000×1 KB files | 16.5 ms | 16.1 ms | 18.6 ms |
| host read 1000×1 KB files | 14.7 ms | 14.2 ms | 18.3 ms |
| host write 10 MB | 37.7 ms | 37.3 ms | 41.9 ms |
| host read 10 MB | 1.2 ms | 1.3 ms | 1.5 ms |

Two things fall out of this table. First, **node startup (~88 ms) is the
tax on every tool call that spawns a fresh interpreter** — which is why
the design keeps a resident sidecar instead of spawning per call.
Second, the fork/exec floor is under 1 ms, so any exec latency above a
few milliseconds is daemon + namespace overhead, not process spawn.

`bwrap` (the Claude-Code-style lightweight sandbox) could NOT be
measured here: `bwrap --unshare-all` fails with `Can't mount proc on
/newroot/proc: Operation not permitted` — this VM restricts nested
namespace mounts. That is an environment limit, not a result about
bwrap. The Mac measurement plan (§5) covers it.

### 4b. Docker numbers — what actually happened (this VM)

Docker was installed to measure it (static binaries 29.1.3; VM only).
The daemon runs (overlayfs, cgroup v2). Results:

- `alpine:3.21` pulled in **9.8 s**; on-disk size **13.1 MB** (measured
  via `docker images`) — the only container number this workshop
  produced.
- `wolfi-base`: all layers downloaded in ~13 s, but extraction FAILED —
  `failed to mount ... fstype: overlay ... err: invalid argument`.
  Nested overlayfs mounts are blocked in this environment.
- The candidate image builds never ran: the build script's Dockerfiles
  were never written (my script bug — the pull step exited first), and
  the builds would have needed container execution anyway.
- Cold start, exec latency, container file I/O: **NOT MEASURED — no
  container can start on this VM.** Every `docker run` / `docker exec`
  fails at the overlay mount. `bwrap` fails the same way (proc mount
  not permitted, §4a).
- `docker info` warnings: **no memory/swap/cpu-cfs/cpuset/io limits** —
  the cgroup controllers are not delegated in this VM, so resource caps
  cannot be enforced or measured here either.
- The egress proxy password rotates per exec call; the daemon needed a
  restart with fresh proxy env before pulls worked (earlier TLS
  handshake timeouts were stale proxy credentials, not a registry
  problem).

Consequence: **there are no Docker runtime numbers from this workshop.**
The runtime shootout (§2d) is decided on Gary's Mac (§5b), where the
VMs and the sandbox actually run. Docker enters that shootout as one
candidate among six, with the heaviest published footprint.

## 5. Speed story — where every millisecond goes

### 5a. Latency budget — one tool call, warm session

Latency budget for one agent tool call, warm session (targets — to be
confirmed by the Mac shootout, §5b):

| Leg | Cost | Notes |
|---|---|---|
| Tool pass (policy + brain) | ~0 ms local | Already local; the container adds one gate check, not a hop |
| Exec into the warm container | **target <50 ms p95** (Linux); <100 ms p95 (Mac, VM hop) | An exec is a daemon round-trip + namespace attach (or a fork, for the native sandbox). This is THE number. |
| Interpreter startup | **0 ms** | The sidecar holds node + python warm. Spawning per call would add 27–88 ms (§4a) — the sidecar deletes it. |
| File read/write in `/work` | ~host I/O (§4a) + mount overhead | Bind mount on Linux is near-native; on the Mac the mount (virtiofs/9p) is the known slow leg — measure on the Mac, §5b. |
| Cold start (once per session) | **target <1 s** (Linux, cached image); <3 s (Mac, warm VM) | Container create + start from a cached ≤200 MB image. Paid once per session, never per call. |
| Image pull (once, ever) | **target <60 s** | ≤80 MB compressed on a normal connection; 0 s after (cached). |
| Runtime start (once per Lucid launch) | 0 s (native sandbox) to 10–45 s (Docker Desktop); the shootout (§2d) measures each | Amortized across the whole Lucid session; never per agent session. |

**What makes ours fastest:** the warm container + the resident sidecar +
local IPC + no cloud hop + a ≤200 MB image. The three reference systems
all pay a network round-trip and a cold-start-or-checkpoint per call or
per session; we pay a local exec. The image being small is what makes
the cold start cheap; the sidecar is what makes every call after the
first cheap.

### 5b. Mac measurement plan — the runtime shootout (for Gary's machine — NOT run yet)

The VM numbers above are Linux numbers, and the Docker numbers do not
exist at all (§4b). The Mac is where the runtime is decided. Plan, run
on the Intel Mac mini when the build lands — same measurements, every
candidate, head to head:

1. Candidates: Docker Desktop, Colima (`colima start --cpu 2 --memory 2
   --disk 20`), Podman machine, OrbStack/microVM (Virtualization.framework),
   macOS-native Seatbelt sandbox, and no-container (host tools — the
   baseline everything must beat on speed).
2. For each VM runtime: VM start time (cold), VM RSS at idle, pull time +
   on-disk size for `lucid-agent:slim`.
3. Cold start: container start ×20 (or sandbox spawn ×20 for Seatbelt).
4. Warm exec: exec into a warm container ×100 (mean/p95); for Seatbelt,
   the equivalent is a sandboxed fork+exec.
5. Bind-mount I/O: the same 1000×1 KB + 10 MB loops over the mounted
   workspace vs the same loops on the host. This is the number that
   decides whether the mount is fast enough.
6. Node/python startup inside the sandbox, sidecar on vs off — the
   difference is the sidecar's value, in milliseconds.
7. Memory: runtime RSS at idle + one warm container + one executing
   container, against the 8 GB total. The winner must leave room for
   Lucid + the model.

The winner is the fastest that passes the isolation bar and the 8 GB
gate. If two are within noise of each other, the lighter one wins.

## 6. Open questions for Gary (his calls — not decided here)

1. **Runtime:** Docker Desktop, Lima/Colima, Podman machine, a microVM
   via Virtualization.framework, macOS-native Seatbelt sandboxing, or no
   Linux container at all? Docker Desktop is the heaviest option on the
   8 GB Intel Mac and has something to prove, not a head start. Fastest
   wins on the Mac shootout (§5b). If the native sandbox wins on speed
   but you want the Linux boundary anyway, that is your call.
2. **Image contents — what's in, what's out:** slim = node + python +
   git + ripgrep only. Does the `full` image get the data-science stack
   (pandas/numpy/matplotlib)? Build tools (gcc/make) in slim or only in
   full? Which node/python versions?
3. **Network default:** off, always — or an allow-listed proxy on by
   default for package installs? (The design says off; the proxy is the
   escape hatch, gated by the permission model.)
4. **Warm-up timing:** does the container start when Agent mode flips,
   or lazily on the first agent tool call? (Eager = first call is fast;
   lazy = no cost until the agent actually acts.)
5. **Guests:** the agent is refused in guest (terminal-only), but the
   Files-tab copilot agent IS allowed on guest. Does the guest copilot
   get a container, or does it keep running host file tools?
6. **One container per session, or per project?** (Per session is the
   design; per project would let two sessions share a warm container
   and the image cache — but sharing breaks the destroy-on-leave rule.)
7. **VM memory cap:** 2 GB for the whole Linux VM on the 8 GB Mac, or
   3 GB? (2 GB leaves more for Lucid + the model; 3 GB gives the
   container more headroom.)

## 7. Sources

- ChatGPT code interpreter / Advanced Data Analysis:
  https://meetzest.com/blog/chatgpt-code-interpreter,
  https://www.respan.ai/articles/openai-code-interpreter-guide,
  https://www.coursera.org/articles/chatgpt-code-interpreter
- Claude code execution tool + Cowork + Claude Code sandbox:
  https://www.claude3p.com/articles/api-tool-code-execution,
  https://aisuitex.com/claude-code-execution-tool-guide/,
  https://redreamality.com/blog/claude-cowork-cloud-sandbox-where-agents-run/,
  https://www.formal.ai/blog/claude-code-sandbox/,
  https://www.its-tahir.com/blog/claude-code-sandbox
- Grok sandbox + Grok Build CLI:
  https://github.com/lspiguel/ai-tooling/blob/HEAD/docs/agents/grok-infrastructure-tools-and-capabilities.md,
  https://innfactory.ai/en/ai-harness/grok-cli/,
  https://www.safetycard.dev/github.com/xai-org/grok-build
- Base image sizes (measured Sep 2026):
  https://jacar.es/en/wolfi-vs-alpine-vs-distroless-docker-base-images-measured/,
  https://www.bloodraven.in/writing/the-curious-case-of-docker-hardend-images/,
  https://www.kjaniec.dev/blog/google-distroless-images-guide
- Lazy loading (eStargz / SOCI / Nydus):
  https://arxiv.org/pdf/2608.19412v1 (SOCI, 7.4–9.3× pull),
  https://www.hackingnote.com/en/containerd/snapshotter/
- Mac runtimes (idle RAM / startup):
  https://sumguy.com/colima-vs-orbstack-vs-docker-desktop/,
  https://devalice.jaceclub.com/mac/docker-setup,
  https://dev.to/ashabhussan/switching-from-docker-desktop-to-colima-on-macos-1dm8
- Lucid code (verified in the VM copy 2026-11-14):
  `src/lib/agentToolsImpl.ts` (13 tools; `run_terminal_command`
  deliberately not built), `src/lib/agentPolicy.ts`
  (`decideToolPolicy`, deny beats auto), `src/lib/agentLoop.ts`
  (tool pass + receipts).
- Measurements: `~/workspace/lucid-container-tool-workshop/baseline.py`
  (host baselines), `docker-bench.py` (Docker numbers, §4b),
  `pull.sh` (candidate image builds).
