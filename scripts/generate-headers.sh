#!/bin/bash

# CUTE Header Generation Script
# Extract REAL parameters from Config classes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUTE_ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 显示帮助信息
show_help() {
    cat << EOF
╔═══════════════════════════════════════════════════════════════╗
║           CUTE Header Generation Script                       ║
║     Extract REAL parameters from Config classes               ║
╚═══════════════════════════════════════════════════════════════╝

USAGE:
    ./scripts/generate-headers.sh [OPTIONS] [CONFIG_NAME] [OUTPUT_DIR]

OPTIONS:
    -c, --clean     Clean build artifacts before generating
    -h, --help      Show this help message

ARGUMENTS:
    CONFIG_NAME    Config class name (default: chipyard.CUTE2TopsSCP64Config)
    OUTPUT_DIR     Output directory (default: cutetest/include)

AVAILABLE CONFIGURATIONS:
    chipyard.CUTE2TopsSCP64Config      2-Tops, 64x64x64 tensors
    chipyard.CUTE4TopsSCP64Config      4-Tops, 64x64x64 tensors
    chipyard.CUTE4TopsSCP128Config     4-Tops, 128x128x64 tensors
    chipyard.CUTE8TopsSCP256Config     8-Tops, 256x256x64 tensors
    ... (see chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala)

EXAMPLES:
    # Generate with default config
    ./scripts/generate-headers.sh

    # Generate for specific config with clean build
    ./scripts/generate-headers.sh --clean chipyard.CUTE4TopsSCP128Config

    # Generate to custom directory
    ./scripts/generate-headers.sh chipyard.CUTE2TopsSCP64Config /tmp/cute-headers

OUTPUT FILES:
    datatype.h.generated      Data type definitions and macros
    validation.h.generated    Hardware parameter constants from actual Config

EOF
}

# 解析命令行参数
CLEAN_BUILD=false
CONFIG_NAME=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--clean)
            CLEAN_BUILD=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            if [[ -z "$CONFIG_NAME" ]]; then
                CONFIG_NAME="$1"
            elif [[ -z "$OUTPUT_DIR" ]]; then
                OUTPUT_DIR="$1"
            else
                echo "Too many arguments"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 默认值
CONFIG_NAME=${CONFIG_NAME:-chipyard.CUTE2TopsSCP64Config}
OUTPUT_DIR=${OUTPUT_DIR:-$CUTE_ROOT_DIR/cutetest/include}

# 将 OUTPUT_DIR 转换为绝对路径（如果还不是绝对路径）
if [[ ! "$OUTPUT_DIR" = /* ]]; then
  OUTPUT_DIR="$CUTE_ROOT_DIR/$OUTPUT_DIR"
fi

echo "====================================="
echo "CUTE Header Generation Script"
echo "====================================="
echo "Config: $CONFIG_NAME"
echo "Output: $OUTPUT_DIR"
echo "Clean build: $CLEAN_BUILD"
echo ""

# 切换到 chipyard 目录以使用其构建环境
cd "$CUTE_ROOT_DIR/chipyard"

# 激活环境
source env.sh

# 清理旧的编译产物（如果请求）
if [ "$CLEAN_BUILD" = true ]; then
    echo "Cleaning build artifacts..."
    # 清理 cute 项目的类文件
    rm -f /root/opencute/CUTE/chipyard/generators/cute/target/scala-2.13/classes/cute/util/HeaderGenerator*.class
    # 清理 chipyard 项目的类文件（如果存在）
    rm -f chipyard/target/scala-2.13/classes/cute/util/HeaderGenerator*.class
    rm -f chipyard/target/scala-2.13/classes/chipyard/util/HeaderGenerator*.class

    # 清理 sbt 缓存
    sbt "cute/clean" "chipyard/clean" > /dev/null 2>&1 || true
fi

# 编译并运行 HeaderGenerator
# 使用 chipyard 项目，它依赖于 cute 并包含所有 Config 类
echo "Compiling cute project and generating headers..."
sbt "cute/compile" "project chipyard" "runMain cute.util.HeaderGenerator $OUTPUT_DIR $CONFIG_NAME"

echo ""
echo "====================================="
echo " Done!"
echo "====================================="
echo ""
echo "Generated files:"
ls -la "$OUTPUT_DIR"/*.generated 2>/dev/null || echo "  (No generated files found)"
echo ""
