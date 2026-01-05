#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "[Setup-Rvv-toolchain-step-1] Script absolute path: $SCRIPT_DIR"
echo "[Setup-Rvv-toolchain-step-1] CUTE root absolute path: $CUTE_ROOT_DIR"

echo ""
echo "[Setup-Rvv-toolchain-step-2] Download the precompiled RISC-V Vector (RVV) toolchain..."
mkdir -p "$CUTE_ROOT_DIR/tool"
cd "$CUTE_ROOT_DIR/tool"
wget https://github.com/OpenCUTE/riscv-gnu-toolchain/releases/download/dac2026/rvvtoolchain.tar.xz
tar -xJvf rvvtoolchain.tar.xz
echo "[Setup-Rvv-toolchain-step-2] RVV toolchain download and extraction complete."
echo ""

echo "RVV toolchain is set up at: $CUTE_ROOT_DIR/tool/riscv"
