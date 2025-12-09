#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "[Verilog-Generate-step-1] Script absolute path: $SCRIPT_DIR"
echo "[Verilog-Generate-step-1] CUTE root absolute path: $CUTE_ROOT_DIR"

# 从命令行参数获取 CONFIG 名称
CONFIG_NAME=${1:-CUTE2TopsSCP64Config}   # 如果没传参数，就用默认值

echo ""
echo "[Verilog-Generate-step-2] Using Chipyard Generating Verilog files with CONFIG=$CONFIG_NAME ..."
source "$CUTE_ROOT_DIR/chipyard/env.sh"
cd "$CUTE_ROOT_DIR/chipyard/sims/verilator"
make verilog CONFIG=$CONFIG_NAME -j24
echo "[Verilog-Generate-step-2] Verilog files generation complete."
echo "all files are located at: $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/"
echo "all soc verilog files are shown in the $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/chipyard.harness.TestHarness.$CONFIG_NAME.all.f"
echo "all verilog files are located at: $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/gen-collateral"