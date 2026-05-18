#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[CUTE-Setup-step-1] Script absolute path: $SCRIPT_DIR"

# Script to set up the build environment for CUTE
echo ""
echo "[CUTE-Setup-step-2] Updating CUTE git submodules..."
git submodule update --init
echo "[CUTE-Setup-step-2] CUTE git submodules updated."
echo ""

echo ""
echo "[CUTE-Setup-step-3] Setting up chipyard environment..."
# 假设 chipyard 初始化脚本是 scripts/init-submodules.sh

cd "$SCRIPT_DIR/../chipyard"
bash "./build-setup.sh --skip-firesim --skip-marshal --skip-clean"
cd "$SCRIPT_DIR/.."

echo "[CUTE-Setup-step-3] Chipyard environment setup complete."
echo ""
# Additional setup steps can be added here
echo "[CUTE-Setup-step-4] WIP : Additional setup steps will be added soon."
