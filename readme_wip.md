# CUTE WIP README

CUTE is a CPU-centric and Ultra-utilized Tensor Engine project. This WIP README
is the repository-level entry point for developers who want to understand the
tree layout, the config-first workflow, simulator execution, trace tooling, and
the CUTE SDK direction.

Chinese version: `readme_wip.zh.md`.

For the current public design document, see
[CUTE Design Doc](https://opencute.github.io/CUTE-Design-Doc/).

## Repository Overview

Some of the key directories are shown below.

```text
.
├── src
│   └── main/scala         # design files
│       ├── CUTETOP.scala  # top module
├── configs                # declarative manifests for CUTE, Chipyard, HW targets
│   ├── cute_configs       # CUTE accelerator parameter presets
│   ├── chipyard_configs   # SoC + CUTE composition manifests
│   ├── hwconfigs          # runnable target manifests
│   ├── cute_isa_versions  # CUTE/YGJK ISA and datatype definitions
│   ├── vector_versions    # vector extension capability manifests
│   └── schemas            # JSON schemas and parameter dictionaries
├── trace                  # CUTE trace catalog, generated APIs, decoder data
│   ├── catalogs           # trace catalog truth source
│   ├── cutetrace          # Scala trace runtime and generated typed API
│   └── python             # Python parser, decoder, and render library
├── cute-sdk               # full-stack software SDK for CUTE programs and verification
│   ├── cuteisa            # generated ISA artifacts
│   ├── cuteqemu           # functional simulator direction
│   ├── nvwa               # golden generation direction
│   ├── memverify          # memory comparison direction
│   └── cutelib            # layered CUTE software libraries
├── cute-fpe               # mixed-precision PE project
│   ├── fpe                # RTL implementation of mixed-precision PE
│   └── ccode              # C code of golden of float
├── cutetest               # C code implementation of different workloads project
│   ├── base_test          # basic conv/gemm test and basic software helper
│   ├── dramsim_config     # dramsim config for different dram bandwidth
│   ├── gemm_test          # different gemm test
│   ├── resnet50_test      # different resnet50 conv-vector fuse kernel test
│   └── transformer_test   # different bert&llama gemm-vector fuse kernel test
├── tools                  # host-side Python tools for config, build, run, trace
│   ├── runner             # config check/codegen/build/run tools
│   └── trace              # trace check/codegen/decode CLI tools
├── scripts                # scripts for agile development
├── chipyard               # agile Chisel-based SoC framework
├── CPU                    # List of CPUs with completed integration
│   ├── boom               # out-of-order superscalar core (BOOM)
│   ├── rocket             # in-order 1-issue core (Rocket)
│   └── shuttle            # in-order superscalar core (Shuttle)
└── doc                    # design and SDK documentation
```

## Where To Read Next

The root README should stay short. The active systems each have their own
working notes:

- Config manifests: `configs/README.md`
  CuteConfig, ChipyardConfig, HWConfig, ISA, vector, memory, and schema checks.
- Runner tools: `tools/README.md`
  `cute-check-config.py`, `cute-build.py`, `cute-run.py`, and Scala config
  generators.
- Trace system: `trace/README.md`
  Trace catalog, Scala/Python generated APIs, and compact trace decode flow.
- Trace format: `trace/format_spec.md`
  Compact line format and field encoding.
- CUTE SDK: `cute-sdk/readme.md`
  cuteisa, cuteqemu, nvwa, memverify, and cutelib.
- Deep Chipyard/config development:
  `doc/sdk-doc/chipyard-config-development.md`
  How YAML, Scala Config, Chipyard, simulator, and run flows connect.

## Prepare Environment

Before executing all subsequent steps, complete the environment initialization
first.

```bash
./scripts/setup-env.sh
```

The script updates submodules and prepares the Chipyard environment. If a later
command fails with a missing Chipyard tool or environment variable, rerun this
step and check `chipyard/env.sh`.

## Config-First Workflow

The current direction is: **Config YAML is the truth source**.

At a high level:

```text
configs/
  ├── cute_configs/*.yaml
  ├── chipyard_configs/*.yaml
  ├── hwconfigs/*.yaml
  ├── cute_isa_versions/*.yaml
  └── vector_versions/*.yaml
        │
        ├─→ Scala config generation/check
        ├─→ C header / ISA JSON generation
        ├─→ Verilator simulator build
        └─→ simulator run + trace decode
```

Validate all config inputs:

```bash
python3 tools/runner/cute-check-config.py --scan
python3 tools/runner/cute-check-config.py --hwconfig --all
python3 tools/runner/cute-check-config.py --chipyard-config --all
```

Generate C headers and ISA JSON for one runnable target:

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step genfiles
```

Generate files for every HWConfig:

```bash
python3 tools/runner/cute-build.py \
  --all \
  --step genfiles
```

`--all` scans `configs/hwconfigs/*.yaml` and deduplicates by
`chipyard_config`, because generated files and simulators are stored under the
Chipyard config id.

## Scala And Chipyard Config Generation

CUTE has two Scala-facing config paths:

```text
configs/cute_configs/*.yaml
  └─→ src/main/scala/HardwareConfig.scala

configs/cute_isa_versions/*.yaml
  └─→ src/main/scala/InstConfig.scala

configs/chipyard_configs/*.yaml
  └─→ chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
```

Check whether generated Scala files match the YAML truth source:

```bash
python3 tools/runner/cute-gen-scala-config.py --check
```

Update `HardwareConfig.scala` and `InstConfig.scala`:

```bash
python3 tools/runner/cute-gen-scala-config.py --update
```

Check or update Chipyard `CuteConfig.scala`:

```bash
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala \
  --check
```

For the deeper model of these files and how to add new targets, read
`doc/sdk-doc/chipyard-config-development.md`.

## Build Simulator

Build a Verilator simulator from an HWConfig:

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step simulator
```

Generate files and build the simulator in one command:

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step all
```

Simulator artifacts are archived under:

```text
build/chipyard_configs/<chipyard_config_id>/simulator-verilator
```

After simulator build, the tool prints the matched Chipyard Scala config class
and the absolute `CuteConfig.scala:<line>` location so editors such as VS Code
can jump directly to the class.

## Build CUTE Tests

Use the existing test scripts to build bare-metal RISC-V binaries:

```bash
./scripts/setup-get-rvv-toolchain.sh
./scripts/build_cute_test.sh
```

The current test tree includes base tests, GEMM tests, ResNet50 kernels, and
Transformer kernels under `cutetest/`.

## Run Programs By Simulation

Run a compiled test binary with an HWConfig:

```bash
python3 tools/runner/cute-run.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

Use `--quiet` to hide runner status lines such as `[CMD]` while keeping
simulator stdout visible:

```bash
python3 tools/runner/cute-run.py \
  --quiet \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

Default outputs are under:

```text
build/chipyard_runs/<hwconfig>/<test>/
├── hwconfig.yaml
├── run.log     # simulator stdout
└── run.out     # simulator stderr
```

## Trace Workflow

CUTETrace is catalog-driven. The catalog is the truth source for Scala trace
emit APIs, Python decoder data, and stable generated metadata.

```bash
# 1. Check trace catalog and filters
python3 tools/trace/check_cute_trace.py

# 2. Regenerate Scala/Python trace artifacts
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated

# 3. Decode a simulator log
python3 tools/trace/decode_cute_trace.py \
  --log build/chipyard_runs/<hwconfig>/<test>/run.log \
  --mode jsonl \
  -o out.jsonl
```

Read `trace/README.md` first, then follow the focused documents under
`doc/sdk-doc/cute-trace-*.md` for catalog, parser, decoder, render, and CLI
details.

## CUTE SDK Workflow

`cute-sdk/` is the software stack direction for CUTE program development and
verification.

```text
configs/cute_isa_versions/*.yaml
  └─→ cute-sdk/cuteisa/<isa_version>/
        ├── instruction.h
        └── isa.json

cutelib development
  ├── cuteqemu functional simulation
  ├── Verilator simulation + trace decode
  └── FPGA demo readback
        └─→ memverify bit-level comparison against golden data
```

The main SDK concepts are documented in `cute-sdk/readme.md`:

- `cuteisa`: shared ISA artifacts.
- `cuteqemu`: functional simulator direction.
- `nvwa`: golden generation direction.
- `memverify`: memory comparison direction.
- `cutelib`: runtime/tensor/layer/fusion/model libraries.

## Legacy Script Flow

Some scripts remain useful for direct Chipyard-style workflows:

```bash
./scripts/build-verilog.sh CUTE2TopsSCP64Config
./scripts/build-simulator.sh CUTE2TopsSCP64Config
./scripts/run-simulator-test.sh \
  CUTE2TopsSCP64Config \
  /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

For new work, prefer the HWConfig-driven runner tools because they preserve the
link between YAML manifests, generated files, simulator artifacts, run logs, and
trace decode inputs.
