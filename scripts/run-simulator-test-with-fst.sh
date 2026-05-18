#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "[Simulator-Test-step-1] Script absolute path: $SCRIPT_DIR"
echo "[Simulator-Test-step-1] CUTE root absolute path: $CUTE_ROOT_DIR"

# 从命令行参数获取 CONFIG 名称
CONFIG_NAME=${1:-CUTE2TopsSCP64Config}   # 如果没传参数，就用默认值
TEST_BINARY=${2:-$CUTE_ROOT_DIR/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv}
TEST_BINARY_NAME=$(basename "$TEST_BINARY")
TEST_BINARY_NAME_NOEXT="${TEST_BINARY_NAME%.riscv}"
TIME=$(date +"%Y%m%d_%H%M%S")
echo ""
echo "[Simulator-Test-step-2] Using Chipyard Generating Simulator with CONFIG=$CONFIG_NAME BINARY=$TEST_BINARY ..."
source "$CUTE_ROOT_DIR/chipyard/env.sh"
cd "$CUTE_ROOT_DIR/chipyard/sims/verilator"
make CONFIG=$CONFIG_NAME run-binary-debug-hex BINARY=$TEST_BINARY USE_FST=1 -j24
echo "[Simulator-Test-step-2] Simulator Test complete."

echo $CUTE_ROOT_DIR

echo "Debug Info at $CUTE_ROOT_DIR/build/chipyard/debug-logs/chipyard.harness.TestHarness.$CONFIG_NAME/$TEST_BINARY_NAME_NOEXT.out"

echo "UART log at $CUTE_ROOT_DIR/build/chipyard/debug-logs/chipyard.harness.TestHarness.$CONFIG_NAME/$TEST_BINARY_NAME_NOEXT.log"

echo "FST trace at $CUTE_ROOT_DIR/build/chipyard/debug-logs/chipyard.harness.TestHarness.$CONFIG_NAME/$TEST_BINARY_NAME_NOEXT.fst"