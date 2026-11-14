#!/bin/bash
# One-shot runner: (re)start dockerd with THIS shell's fresh proxy env,
# pull bases, build candidate images, run the bench. All in one exec call
# because the egress-proxy password rotates per exec invocation.
# Log: ~/workspace/lucid-container-tool-workshop/bench-run.log
set -x
cd ~/workspace/lucid-container-tool-workshop
pkill -x dockerd; sleep 3
nohup dockerd --iptables=false --bridge=none --userland-proxy=false > /tmp/dockerd.log 2>&1 &
for i in $(seq 1 20); do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info | grep -E "Server Version|Storage Driver|Cgroup Version"
echo "=== pull alpine (timed) ==="
time docker pull alpine:3.21
echo "=== pull wolfi-base (timed) ==="
time docker pull cgr.dev/chainguard/wolfi-base:latest
echo "=== build lucid-agent:alpine (timed) ==="
time docker build -t lucid-agent:alpine -f /tmp/Dockerfile.alpine /tmp
echo "=== build lucid-agent:wolfi (timed) ==="
time docker build -t lucid-agent:wolfi -f /tmp/Dockerfile.wolfi /tmp
echo "=== images ==="
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'
echo "=== bench ==="
python3 docker-bench.py
