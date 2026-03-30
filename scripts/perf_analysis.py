#!/usr/bin/env python3
"""
CUTE Performance Analysis Tool
用于分析仿真输出的性能数据，进行自顶向下的性能分析
"""

import re
import sys
import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional
import matplotlib.pyplot as plt
import numpy as np


@dataclass
class InstructionReport:
    """单条宏指令的性能报告"""
    inst_id: int
    total_cycles: int
    compute_cycles: int
    aload_cycles: int
    bload_cycles: int
    cload_cycles: int
    dstore_cycles: int
    aop_cycles: int
    stall_cycles: int
    parallel_active: int
    mmu_requests: int
    mmu_stall: int

    @property
    def compute_pct(self) -> float:
        return self.compute_cycles / self.total_cycles * 100 if self.total_cycles > 0 else 0

    @property
    def load_pct(self) -> float:
        load = self.aload_cycles + self.bload_cycles + self.cload_cycles
        return load / self.total_cycles * 100 if self.total_cycles > 0 else 0

    @property
    def store_pct(self) -> float:
        return self.dstore_cycles / self.total_cycles * 100 if self.total_cycles > 0 else 0

    @property
    def stall_pct(self) -> float:
        return self.stall_cycles / self.total_cycles * 100 if self.total_cycles > 0 else 0

    @property
    def parallel_pct(self) -> float:
        return self.parallel_active / self.total_cycles * 100 if self.total_cycles > 0 else 0

    @property
    def memory_bound_pct(self) -> float:
        """内存绑定度：Load + Store周期占比"""
        return (self.load_pct + self.store_pct)

    @property
    def compute_efficiency(self) -> float:
        """计算效率：实际计算时间 vs (计算+停顿)"""
        active = self.compute_cycles + self.stall_cycles
        return self.compute_cycles / active * 100 if active > 0 else 0


class PerfAnalyzer:
    """性能分析器"""

    def __init__(self, log_file: str):
        self.log_file = log_file
        self.reports: List[InstructionReport] = []
        self.periodic_samples: List[Dict] = []

    def parse_logs(self):
        """解析仿真日志"""
        with open(self.log_file, 'r') as f:
            lines = f.readlines()

        # 解析每条指令完成的报告
        report_pattern = re.compile(
            r'CUTE Performance Report \(Inst #(\d+)\).*?\n'
            r'.*?Total Cycles: (\d+)\n'
            r'.*?Compute Cycles: (\d+)\n'
            r'.*?A-Load Cycles: (\d+)\n'
            r'.*?B-Load Cycles: (\d+)\n'
            r'.*?C-Load Cycles: (\d+)\n'
            r'.*?D-Store Cycles: (\d+)\n'
            r'.*?AOP Cycles: (\d+)\n'
            r'.*?Stall Cycles: (\d+)\n'
            r'.*?Parallel Active Cycles: (\d+)\n'
            r'.*?MMU Requests: (\d+)\n'
            r'.*?MMU Stall Cycles: (\d+)\n'
            r'.*?Completed Instructions: (\d+)\n',
            re.DOTALL
        )

        i = 0
        while i < len(lines):
            match = report_pattern.search('\n'.join(lines[i:min(i+30, len(lines))]))
            if match:
                report = InstructionReport(
                    inst_id=int(match.group(1)),
                    total_cycles=int(match.group(2)),
                    compute_cycles=int(match.group(3)),
                    aload_cycles=int(match.group(4)),
                    bload_cycles=int(match.group(5)),
                    cload_cycles=int(match.group(6)),
                    dstore_cycles=int(match.group(7)),
                    aop_cycles=int(match.group(8)),
                    stall_cycles=int(match.group(9)),
                    parallel_active=int(match.group(10)),
                    mmu_requests=int(match.group(11)),
                    mmu_stall=int(match.group(12))
                )
                self.reports.append(report)
                i += 20
            else:
                i += 1

        print(f"✓ 解析了 {len(self.reports)} 条指令报告")

    def analyze_level1_system(self):
        """Level 1: 系统级指标分析"""
        if not self.reports:
            print("❌ 没有可分析的数据")
            return

        print("\n" + "="*60)
        print("📊 Level 1: 系统级性能指标")
        print("="*60)

        total_cycles = sum(r.total_cycles for r in self.reports)
        total_insts = len(self.reports)
        avg_cycles_per_inst = total_cycles / total_insts

        print(f"总执行周期数: {total_cycles:,}")
        print(f"完成的宏指令数: {total_insts}")
        print(f"平均每条宏指令周期: {avg_cycles_per_inst:.1f}")

        # 计算总体阶段分布
        total_compute = sum(r.compute_cycles for r in self.reports)
        total_load = sum(r.aload_cycles + r.bload_cycles + r.cload_cycles for r in self.reports)
        total_store = sum(r.dstore_cycles for r in self.reports)
        total_stall = sum(r.stall_cycles for r in self.reports)

        print(f"\n阶段分布:")
        print(f"  计算阶段:     {total_compute:,} ({total_compute/total_cycles*100:.1f}%)")
        print(f"  加载阶段:     {total_load:,} ({total_load/total_cycles*100:.1f}%)")
        print(f"  存储阶段:     {total_store:,} ({total_store/total_cycles*100:.1f}%)")
        print(f"  停顿阶段:     {total_stall:,} ({total_stall/total_cycles*100:.1f}%)")

        # 内存带宽相关
        total_mmu_req = sum(r.mmu_requests for r in self.reports)
        print(f"\n内存访问:")
        print(f"  MMU总请求数:  {total_mmu_req:,}")
        print(f"  平均每指令:   {total_mmu_req/total_insts:.1f}")

    def analyze_level2_stages(self):
        """Level 2: 阶段级瓶颈分析"""
        if not self.reports:
            return

        print("\n" + "="*60)
        print("📊 Level 2: 阶段级瓶颈分析")
        print("="*60)

        print(f"\n{'指令ID':<10} {'总周期':<12} {'计算%':<10} {'加载%':<10} {'存储%':<10} {'停顿%':<10} {'并行%':<10}")
        print("-" * 70)

        for r in self.reports:
            print(f"{r.inst_id:<10} {r.total_cycles:<12} "
                  f"{r.compute_pct:<10.1f} {r.load_pct:<10.1f} "
                  f"{r.store_pct:<10.1f} {r.stall_pct:<10.1f} "
                  f"{r.parallel_pct:<10.1f}")

        # 找出瓶颈
        max_compute = max(self.reports, key=lambda r: r.compute_pct)
        max_load = max(self.reports, key=lambda r: r.load_pct)
        max_store = max(self.reports, key=lambda r: r.store_pct)
        max_stall = max(self.reports, key=lambda r: r.stall_pct)

        print(f"\n阶段瓶颈分析:")
        print(f"  计算最重:   指令 #{max_compute.inst_id} ({max_compute.compute_pct:.1f}%)")
        print(f"  加载最重:   指令 #{max_load.inst_id} ({max_load.load_pct:.1f}%)")
        print(f"  存储最重:   指令 #{max_store.inst_id} ({max_store.store_pct:.1f}%)")
        print(f"  停顿最长:   指令 #{max_stall.inst_id} ({max_stall.stall_pct:.1f}%)")

    def analyze_level3_components(self):
        """Level 3: 组件级瓶颈分析"""
        if not self.reports:
            return

        print("\n" + "="*60)
        print("📊 Level 3: 组件级瓶颈分析")
        print("="*60)

        print(f"\n{'指令ID':<10} {'A-Load%':<10} {'B-Load%':<10} {'C-Load%':<10} {'D-Store%':<10} {'AOP%':<10}")
        print("-" * 60)

        for r in self.reports:
            a_pct = r.aload_cycles / r.total_cycles * 100
            b_pct = r.bload_cycles / r.total_cycles * 100
            c_pct = r.cload_cycles / r.total_cycles * 100
            d_pct = r.dstore_cycles / r.total_cycles * 100
            aop_pct = r.aop_cycles / r.total_cycles * 100

            print(f"{r.inst_id:<10} {a_pct:<10.1f} {b_pct:<10.1f} "
                  f"{c_pct:<10.1f} {d_pct:<10.1f} {aop_pct:<10.1f}")

        # 通道不平衡分析
        total_a = sum(r.aload_cycles for r in self.reports)
        total_b = sum(r.bload_cycles for r in self.reports)
        total_c = sum(r.cload_cycles for r in self.reports)

        max_load = max(total_a, total_b, total_c)
        min_load = min(total_a, total_b, total_c)
        imbalance = (max_load - min_load) / max_load * 100 if max_load > 0 else 0

        print(f"\n通道负载平衡度:")
        print(f"  A通道加载: {total_a:,} 周期")
        print(f"  B通道加载: {total_b:,} 周期")
        print(f"  C通道加载: {total_c:,} 周期")
        print(f"  不平衡度:  {imbalance:.1f}% (越低越好)")

    def analyze_level4_metrics(self):
        """Level 4: 微架构指标分析"""
        if not self.reports:
            return

        print("\n" + "="*60)
        print("📊 Level 4: 微架构效率指标")
        print("="*60)

        print(f"\n{'指令ID':<10} {'计算效率%':<12} {'内存绑定%':<12} {'并行度%':<12}")
        print("-" * 50)

        for r in self.reports:
            print(f"{r.inst_id:<10} {r.compute_efficiency:<12.1f} "
                  f"{r.memory_bound_pct:<12.1f} {r.parallel_pct:<12.1f}")

        # 总体效率
        avg_eff = np.mean([r.compute_efficiency for r in self.reports])
        avg_mem = np.mean([r.memory_bound_pct for r in self.reports])
        avg_par = np.mean([r.parallel_pct for r in self.reports])

        print(f"\n总体效率:")
        print(f"  平均计算效率:     {avg_eff:.1f}%")
        print(f"  平均内存绑定度:   {avg_mem:.1f}%")
        print(f"  平均并行度:       {avg_par:.1f}%")

        # 瓶颈诊断
        print(f"\n💡 瓶颈诊断:")
        if avg_mem > 60:
            print("  ⚠️  系统存在严重的内存瓶颈")
            print("     建议：优化数据预取、增加带宽、优化数据布局")
        elif avg_eff < 70:
            print("  ⚠️  计算单元利用率低")
            print("     建议：优化指令调度、减少停顿")
        elif avg_par < 30:
            print("  ⚠️  并行度不足")
            print("     建议：优化微指令调度以提高并行度")
        else:
            print("  ✓ 系统运行良好")

    def plot_breakdown(self, output: str = "perf_breakdown.png"):
        """生成阶段分解图"""
        if not self.reports:
            return

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # 1. 阶段分解饼图
        total_compute = sum(r.compute_cycles for r in self.reports)
        total_load = sum(r.aload_cycles + r.bload_cycles + r.cload_cycles for r in self.reports)
        total_store = sum(r.dstore_cycles for r in self.reports)
        total_stall = sum(r.stall_cycles for r in self.reports)

        axes[0, 0].pie([total_compute, total_load, total_store, total_stall],
                       labels=['Compute', 'Load', 'Store', 'Stall'],
                       autopct='%1.1f%%', startangle=90)
        axes[0, 0].set_title('阶段分解 (总体)')

        # 2. 每条指令的周期柱状图
        inst_ids = [r.inst_id for r in self.reports]
        cycles = [r.total_cycles for r in self.reports]

        axes[0, 1].bar(inst_ids, cycles, color='steelblue')
        axes[0, 1].set_xlabel('指令ID')
        axes[0, 1].set_ylabel('周期数')
        axes[0, 1].set_title('每条宏指令的执行周期')
        axes[0, 1].axhline(y=np.mean(cycles), color='r', linestyle='--', label='平均值')
        axes[0, 1].legend()

        # 3. 各通道负载对比
        total_a = sum(r.aload_cycles for r in self.reports)
        total_b = sum(r.bload_cycles for r in self.reports)
        total_c = sum(r.cload_cycles for r in self.reports)

        axes[1, 0].bar(['A-Load', 'B-Load', 'C-Load'],
                      [total_a, total_b, total_c],
                      color=['#ff6b6b', '#4ecdc4', '#45b7d1'])
        axes[1, 0].set_ylabel('总周期数')
        axes[1, 0].set_title('各通道负载对比')

        # 4. 效率指标趋势
        effs = [r.compute_efficiency for r in self.reports]
        mem_bounds = [r.memory_bound_pct for r in self.reports]

        ax4 = axes[1, 1]
        ax4.plot(inst_ids, effs, 'o-', label='计算效率', color='green')
        ax4.set_xlabel('指令ID')
        ax4.set_ylabel('计算效率 (%)', color='green')
        ax4.tick_params(axis='y', labelcolor='green')

        ax4b = ax4.twinx()
        ax4b.plot(inst_ids, mem_bounds, 's-', label='内存绑定度', color='orange')
        ax4b.set_ylabel('内存绑定度 (%)', color='orange')
        ax4b.tick_params(axis='y', labelcolor='orange')

        axes[1, 1].set_title('效率指标趋势')

        plt.tight_layout()
        plt.savefig(output, dpi=150)
        print(f"\n✓ 图表已保存到 {output}")

    def generate_report(self, output: str = "perf_report.txt"):
        """生成文本报告"""
        with open(output, 'w') as f:
            original_stdout = sys.stdout
            sys.stdout = f

            self.analyze_level1_system()
            self.analyze_level2_stages()
            self.analyze_level3_components()
            self.analyze_level4_metrics()

            sys.stdout = original_stdout

        print(f"\n✓ 报告已保存到 {output}")


def main():
    parser = argparse.ArgumentParser(description='CUTE性能分析工具')
    parser.add_argument('log_file', help='仿真日志文件路径')
    parser.add_argument('--plot', action='store_true', help='生成性能图表')
    parser.add_argument('--report', help='输出文本报告到文件')
    parser.add_argument('--all', action='store_true', help='生成所有输出')

    args = parser.parse_args()

    analyzer = PerfAnalyzer(args.log_file)
    analyzer.parse_logs()

    # 始终输出到控制台
    analyzer.analyze_level1_system()
    analyzer.analyze_level2_stages()
    analyzer.analyze_level3_components()
    analyzer.analyze_level4_metrics()

    if args.plot or args.all:
        analyzer.plot_breakdown()

    if args.report or args.all:
        analyzer.generate_report(args.report or "perf_report.txt")


if __name__ == '__main__':
    main()
