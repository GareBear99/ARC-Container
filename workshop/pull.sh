#!/bin/bash
# Pull the candidate bases and build the two Lucid agent candidate images.
set -e
docker pull alpine:3.21
docker pull cgr.dev/chainguard/wolfi-base:latest

cat > /tmp/Dockerfile.alpine <<'EOF'
FROM alpine:3.21
RUN apk add --no-cache nodejs npm python3 git ripgrep ca-certificates tzdata \
 && adduser -D -u 10001 agent
USER agent
WORKDIR /work
EOF

cat > /tmp/Dockerfile.wolfi <<'EOF'
FROM cgr.dev/chainguard/wolfi-base:latest
RUN apk add --no-cache nodejs npm python3 git ripgrep ca-certificates tzdata
USER 10001
WORKDIR /work
EOF

docker build -t lucid-agent:alpine -f /tmp/Dockerfile.alpine /tmp
docker build -t lucid-agent:wolfi -f /tmp/Dockerfile.wolfi /tmp
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'
