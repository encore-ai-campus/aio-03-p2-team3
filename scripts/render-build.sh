#!/usr/bin/env bash
# Render의 Python 설치를 유지하고 같은 서비스에 포함할 React 산출물을 만든다.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv sync --locked
cd frontend
# NODE_ENV=production이어도 Vite 등 빌드 도구가 필요하다.
npm ci --include=dev
npm run build
test -s dist/index.html
