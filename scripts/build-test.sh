#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "[CUTE-Test-Generate-step-1] Script absolute path: $SCRIPT_DIR"
echo "[CUTE-Test-Generate-step-1] CUTE root absolute path: $CUTE_ROOT_DIR"

echo ""
source "$CUTE_ROOT_DIR/chipyard/env.sh"
echo "[CUTE-Test-Generate-step-2] Generating CUTE test programs..."
cd "$CUTE_ROOT_DIR/cutetest"
echo ""

echo "[CUTE-Test-Generate-step-3] Generating CUTE base test programs..."
cd "$CUTE_ROOT_DIR/cutetest/base_test"
make clean
make -j24
echo "[CUTE-Test-Generate-step-3] CUTE base test programs generation complete."
echo ""

echo "[CUTE-Test-Generate-step-4] Generating CUTE GEMM benchmark test programs..."
cd "$CUTE_ROOT_DIR/cutetest/gemm_test"
make clean
make -j24
echo "[CUTE-Test-Generate-step-4] CUTE GEMM benchmark test programs generation complete."
echo ""

echo "[CUTE-Test-Generate-step-5] Generating CUTE ResNet50 benchmark test programs..."
cd "$CUTE_ROOT_DIR/cutetest/resnet50_test"
make clean
make -j24
echo "[CUTE-Test-Generate-step-5] CUTE ResNet50 benchmark test programs generation complete."
echo "" 

echo "[CUTE-Test-Generate-step-6] Generating CUTE Transformer benchmark test programs..."
cd "$CUTE_ROOT_DIR/cutetest/transformer_test"
echo "[CUTE-Test-Generate-step-6] Generating CUTE Transformer BERT benchmark test programs..."
cd "$CUTE_ROOT_DIR/cutetest/transformer_test/bert"
make clean
make -j24
echo "[CUTE-Test-Generate-step-6] CUTE Transformer BERT benchmark test programs generation complete."
echo ""

echo "[CUTE-Test-Generate-step-7] Generating CUTE Transformer LLaMA benchmark test programs..."
cd "$CUTE_ROOT_DIR/cutetest/transformer_test/llama"
make clean
make -j24
echo "[CUTE-Test-Generate-step-7] CUTE Transformer LLaMA benchmark test programs generation complete."
echo ""

echo "[CUTE-Test-Generate-step-8] Generating CUTE pk test programs..."
cd "$CUTE_ROOT_DIR/cutetest/pk_test"
make clean
make -j24
echo "[CUTE-Test-Generate-step-8] CUTE pk test programs generation complete."
echo ""

echo "[CUTE-Test-Generate-step-9] All CUTE test programs generation complete."
echo "All test programs are located at: $CUTE_ROOT_DIR/cutetest/"
