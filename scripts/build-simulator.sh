#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "[Simulator-Generate-step-1] Script absolute path: $SCRIPT_DIR"
echo "[Simulator-Generate-step-1] CUTE root absolute path: $CUTE_ROOT_DIR"

# 从命令行参数获取 CONFIG 名称
CONFIG_NAME=${1:-CUTE2TopsSCP64Config}   # 如果没传参数，就用默认值
TIME=$(date +"%Y%m%d_%H%M%S")
echo ""
echo "[Simulator-Generate-step-2] Using Chipyard Generating Simulator with CONFIG=$CONFIG_NAME ..."
source "$CUTE_ROOT_DIR/chipyard/env.sh"
cd "$CUTE_ROOT_DIR/chipyard/sims/verilator"
make CONFIG=$CONFIG_NAME -j24
echo "[Simulator-Generate-step-2] Simulator files generation complete."
echo "all files are located at: $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/"
echo "all soc verilog files are shown in the $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/chipyard.harness.TestHarness.$CONFIG_NAME.all.f"
echo "all verilog files are located at: $CUTE_ROOT_DIR/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG_NAME/gen-collateral"

NEW_BIN="$CUTE_ROOT_DIR/chipyard/sims/verilator/simulator-chipyard.harness-$CONFIG_NAME"
TARGET_BIN="$CUTE_ROOT_DIR/build/chipyard/simulator-$CONFIG_NAME-$TIME"
LATEST_BIN=$(ls -t "$CUTE_ROOT_DIR"/build/chipyard/simulator-"$CONFIG_NAME"-* 2>/dev/null | head -n1)

# 如果已有旧版本，先比较
if [[ -n "$LATEST_BIN" && -f "$LATEST_BIN" ]]; then
    if cmp -s "$NEW_BIN" "$LATEST_BIN"; then
        echo "[Simulator-Generate-step-3] New binary is identical to latest one ($LATEST_BIN). Skip copying."
        exit 0
    fi
else
    NEW_BIN="$CUTE_ROOT_DIR/chipyard/sims/verilator/simulator-chipyard.harness-$CONFIG_NAME"
TARGET_BIN="$CUTE_ROOT_DIR/build/chipyard/simulator-$CONFIG_NAME-$TIME"
LATEST_BIN=$(ls -t "$CUTE_ROOT_DIR"/build/chipyard/simulator-"$CONFIG_NAME"-* 2>/dev/null | head -n1)

# 如果已有旧版本，先比较
if [[ -n "$LATEST_BIN" && -f "$LATEST_BIN" ]]; then
    if cmp -s "$NEW_BIN" "$LATEST_BIN"; then
        echo "[Simulator-Generate-step-3] New binary is identical to latest one ($LATEST_BIN). Skip copying."
        exit 0
    fi
fi
    # 如果不同或没有旧版本，就复制
    cp "$NEW_BIN" "$TARGET_BIN"
    echo "[Simulator-Generate-step-3] New simulator binary copied to: $TARGET_BIN"
fi

