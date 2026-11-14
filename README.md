# ARC-Container

The Linux container tool for the Lucid agent — a sandboxed Linux environment per agent session, so the agent's tools (including the shell tool) run inside the container instead of on the host.

**Status: design + research only.** The build is gated on the agent proving viable as a driving intelligence. Nothing here is installed, bundled, or wired into Lucid yet.

## The design

- One container per agent session, spun up when Agent mode starts, destroyed at session end (fits the guest wipe rule).
- The agent's existing tool registry gains a container backend — same tools, executed inside the container.
- Workspace-only mounts: only the active workspace folder, never home, keychain, or other profiles.
- Network off by default, on only through the Zed permission model (deny beats auto).
- CPU/memory capped (the Mac shootout decides the cap — 2 GB vs 3 GB of 8 GB).
- Runtime NOT decided: Docker Desktop, Lima/Colima, Podman machine, microVM via Virtualization.framework, macOS-native Seatbelt sandboxing, or no Linux container at all. Fastest wins, measured on the Mac.

## The image (centerpiece)

`lucid-agent:slim` — Wolfi base (~12 MB, glibc, 0–3 CVEs) + node 24 + python 3.13 + git + ripgrep, non-root user, `/work` only. Targets ≤200 MB on disk, ≤80 MB compressed pull. Wolfi over Alpine because Alpine's musl has no wheels for torch/duckdb/onnxruntime. Distroless is out (no shell — wrong shape for an agent sandbox).

The speed trick: a resident sidecar lives inside the warm container, so the agent never pays interpreter startup (node ~88 ms, python ~27 ms) per call.

## Docs

- [lucid-container-tool-workshop-2026-11-14.md](docs/lucid-container-tool-workshop-2026-11-14.md) — the full workshop: reference systems (ChatGPT / Claude / Grok), the image spec, measured numbers, speed targets, and the 7 open questions.

## Open questions

1. Runtime: Docker Desktop, Lima/Colima, Podman, microVM, Seatbelt, or no container — Mac shootout decides.
2. Image contents: data-science stack in `full`? Build tools in slim or only full? Which node/python versions?
3. Network default: off always, or allow-listed proxy on by default for installs?
4. Warm-up timing: container starts when Agent mode flips, or lazily on first tool call?
5. Guests: does the guest copilot get a container, or keep host file tools?
6. One container per session or per project?
7. VM memory cap: 2 GB or 3 GB of the 8 GB Mac?
