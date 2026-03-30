/**
 * CUTE 矩阵乘法性能基准测试
 *
 * 用途: 测试CUTE加速器在矩阵乘法任务上的性能
 *
 * 编译:
 *   riscv64-unknown-elf-gcc -O3 -march=rv64gcb -o matmul_benchmark matmul_benchmark.c \
 *     -I../../software/cute-driver -L../../software/cute-driver -lcute
 *
 * 运行:
 *   ./matmul_benchmark <M> <N> <K>
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

// CUTE驱动接口（简化版本）
extern void cute_matmul_configure(
    void* A, void* B, void* C, void* D,
    uint64_t M, uint64_t N, uint64_t K,
    int data_type);

extern void cute_matmul_execute(void);
extern void cute_wait_completion(void);
extern uint64_t cute_get_cycle_count(void);

#define DATA_TYPE_FP16 1

// Tile大小配置（根据硬件调整）
#define TILE_M 64
#define TILE_N 64
#define TILE_K 64

/**
 * 矩阵分配（对齐到缓存行边界）
 */
void* allocate_matrix(size_t rows, size_t cols, size_t elem_size) {
    size_t total_size = rows * cols * elem_size;
    // 对齐到64字节边界
    void* ptr = NULL;
    posix_memalign(&ptr, 64, total_size);
    if (ptr == NULL) {
        fprintf(stderr, "内存分配失败\n");
        exit(1);
    }
    return ptr;
}

/**
 * 初始化矩阵（随机数据）
 */
void init_matrix(float* matrix, size_t rows, size_t cols, float min_val, float max_val) {
    for (size_t i = 0; i < rows * cols; i++) {
        matrix[i] = min_val + (float)rand() / (float)(RAND_MAX / (max_val - min_val));
    }
}

/**
 * 验证结果
 */
int verify_result(float* C, float* D, size_t M, size_t N, float epsilon) {
    for (size_t i = 0; i < M * N; i++) {
        if (fabs(C[i] - D[i]) > epsilon) {
            fprintf(stderr, "验证失败 @ [%zu]: C=%f, D=%f, diff=%f\n",
                    i, C[i], D[i], fabs(C[i] - D[i]));
            return 0;
        }
    }
    return 1;
}

/**
 * CPU参考实现（用于验证）
 */
void cpu_matmul(float* A, float* B, float* C, size_t M, size_t N, size_t K) {
    memset(C, 0, M * N * sizeof(float));

    for (size_t m = 0; m < M; m++) {
        for (size_t n = 0; n < N; n++) {
            for (size_t k = 0; k < K; k++) {
                C[m * N + n] += A[m * K + k] * B[k * N + n];
            }
        }
    }
}

/**
 * CUTE矩阵乘法（分块）
 */
void cute_matmul_tiled(float* A, float* B, float* C, float* D,
                       size_t M, size_t N, size_t K) {

    for (size_t m = 0; m < M; m += TILE_M) {
        for (size_t n = 0; n < N; n += TILE_N) {
            for (size_t k = 0; k < K; k += TILE_K) {
                // 当前tile的大小
                size_t cur_m = (m + TILE_M <= M) ? TILE_M : (M - m);
                size_t cur_n = (n + TILE_N <= N) ? TILE_N : (N - n);
                size_t cur_k = (k + TILE_K <= K) ? TILE_K : (K - k);

                // 计算子矩阵的地址
                float* A_tile = A + m * K + k;
                float* B_tile = B + k * N + n;
                float* C_tile = C + m * N + n;
                float* D_tile = D + m * N + n;

                // 配置并执行CUTE宏指令
                cute_matmul_configure(
                    A_tile, B_tile, C_tile, D_tile,
                    cur_m, cur_n, cur_k,
                    DATA_TYPE_FP16
                );

                cute_matmul_execute();
            }
        }
    }

    // 等待所有宏指令完成
    cute_wait_completion();
}

/**
 * 打印使用说明
 */
void print_usage(const char* prog_name) {
    fprintf(stderr, "用法: %s <M> <N> <K> [选项]\n", prog_name);
    fprintf(stderr, "\n参数:\n");
    fprintf(stderr, "  M       矩阵A的行数 (矩阵C的行数)\n");
    fprintf(stderr, "  N       矩阵B的列数 (矩阵C的列数)\n");
    fprintf(stderr, "  K       矩阵A的列数 (矩阵B的行数)\n");
    fprintf(stderr, "\n选项:\n");
    fprintf(stderr, "  --verify      启用结果验证\n");
    fprintf(stderr, "  --cpu-ref     运行CPU参考实现\n");
    fprintf(stderr, "  --iter <n>    重复运行n次 (默认: 1)\n");
    fprintf(stderr, "\n示例:\n");
    fprintf(stderr, "  %s 1024 1024 1024           # 运行1024x1024矩阵乘法\n", prog_name);
    fprintf(stderr, "  %s 512 512 2048 --verify   # 运行并验证结果\n", prog_name);
}

/**
 * 主函数
 */
int main(int argc, char** argv) {
    if (argc < 4) {
        print_usage(argv[0]);
        return 1;
    }

    // 解析参数
    size_t M = atoi(argv[1]);
    size_t N = atoi(argv[2]);
    size_t K = atoi(argv[3]);

    int enable_verify = 0;
    int run_cpu_ref = 0;
    int iterations = 1;

    // 解析选项
    for (int i = 4; i < argc; i++) {
        if (strcmp(argv[i], "--verify") == 0) {
            enable_verify = 1;
        } else if (strcmp(argv[i], "--cpu-ref") == 0) {
            run_cpu_ref = 1;
        } else if (strcmp(argv[i], "--iter") == 0) {
            iterations = atoi(argv[++i]);
        }
    }

    printf("==============================================\n");
    printf("CUTE 矩阵乘法性能基准测试\n");
    printf("==============================================\n");
    printf("矩阵大小: %zu x %zu x %zu\n", M, N, K);
    printf("数据类型: FP16\n");
    printf("Tile大小: %zu x %zu x %zu\n", TILE_M, TILE_N, TILE_K);
    printf("迭代次数: %d\n", iterations);
    printf("验证: %s\n", enable_verify ? "启用" : "禁用");
    printf("CPU参考: %s\n", run_cpu_ref ? "启用" : "禁用");
    printf("==============================================\n\n");

    // 分配矩阵
    printf("分配矩阵...\n");
    float* A = (float*)allocate_matrix(M, K, sizeof(float));
    float* B = (float*)allocate_matrix(K, N, sizeof(float));
    float* C = (float*)allocate_matrix(M, N, sizeof(float));  // CUTE结果
    float* D = (float*)allocate_matrix(M, N, sizeof(float));  // CUTE累积结果

    // 初始化矩阵
    printf("初始化矩阵（随机数据）...\n");
    srand(42);  // 固定种子以便复现
    init_matrix(A, M, K, -1.0f, 1.0f);
    init_matrix(B, K, N, -1.0f, 1.0f);
    memset(C, 0, M * N * sizeof(float));
    memset(D, 0, M * N * sizeof(float));

    // 运行CUTE矩阵乘法
    printf("\n运行CUTE矩阵乘法...\n");
    uint64_t start_cycles = cute_get_cycle_count();

    for (int iter = 0; iter < iterations; iter++) {
        cute_matmul_tiled(A, B, C, D, M, N, K);
    }

    uint64_t end_cycles = cute_get_cycle_count();
    uint64_t total_cycles = end_cycles - start_cycles;

    printf("完成！\n\n");
    printf("==============================================\n");
    printf("性能结果\n");
    printf("==============================================\n");
    printf("总周期数: %lu\n", total_cycles);
    printf("平均每周期: %lu\n", total_cycles / iterations);
    printf("总操作数: %.2f GOPS\n", (double)M * N * K * 2 * iterations / 1e9);
    printf("吞吐量: %.2f GOPS/cycle\n",
           (double)M * N * K * 2 * iterations / total_cycles);
    printf("==============================================\n\n");

    // CPU参考实现（可选）
    if (run_cpu_ref) {
        printf("运行CPU参考实现...\n");
        float* C_ref = (float*)allocate_matrix(M, N, sizeof(float));

        uint64_t cpu_start = cute_get_cycle_count();
        cpu_matmul(A, B, C_ref, M, N, K);
        uint64_t cpu_end = cute_get_cycle_count();

        printf("CPU周期数: %lu\n", cpu_end - cpu_start);
        printf("加速比: %.2fx\n", (double)(cpu_end - cpu_start) / total_cycles);

        // 验证
        if (enable_verify) {
            if (verify_result(C_ref, C, M, N, 1e-3)) {
                printf("✓ CUTE结果验证通过\n");
            } else {
                printf("✗ CUTE结果验证失败\n");
            }
        }

        free(C_ref);
    }

    // 清理
    free(A);
    free(B);
    free(C);
    free(D);

    return 0;
}
