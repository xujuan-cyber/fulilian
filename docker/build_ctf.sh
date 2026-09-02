#!/bin/bash
# 构建 CTF 沙箱工具链镜像
# 用法: ./build_ctf.sh [tag]
# 默认 tag: fulilian-ctf-sandbox:latest

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${1:-fulilian-ctf-sandbox:latest}"

echo "=== Building CTF sandbox image: ${TAG} ==="
echo "Source: ${SCRIPT_DIR}"

docker build \
    -t "${TAG}" \
    -f "${SCRIPT_DIR}/Dockerfile.ctf" \
    "${SCRIPT_DIR}"

echo "=== Build complete: ${TAG} ==="
echo ""
echo "Quick test:"
echo "  docker run --rm ${TAG} checksec --help"
echo "  docker run --rm ${TAG} python3 -c \"import pwntools; print('pwntools OK')\""