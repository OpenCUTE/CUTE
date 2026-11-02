# CUTE system-level verification (P0/T1)

The same SDK source is built as two bare-metal ELFs. The QEMU system model
exports every declared output at a software task checkpoint. Verilator emits
actual CUTE/RVV client requests and responses; the C++ verifier updates its
independent memory image only on successful store acknowledgements and compares
all task outputs at each checkpoint. No CPU output readback or simulated UART
is used for these checkpoints.

## Supported first profile

- One Shuttle/Saturn hart, RV64, VLEN/DLEN/MLEN 512, 64-byte client beats.
- `CUTE4TopsShuttle512D512V512M512Sysbus512Membus1CoreConfig`.
- CUTE signed INT8 × signed INT8 → wrapping INT32; deterministic QEMU execution.
- `tests/system/system_int8.c`: RVV prepares A/B, CUTE computes 128³ GEMM,
  RVV consumes its result. Three task checkpoints compare 163,840 bytes.
- `tests/system/system_tcm.c`: RVV writes and consumes one TCM cacheline;
  two checkpoints compare 128 bytes.
- TCM spec is in `cute-sdk/tests/system/platform.json`. Its backing base is
  `0x70000000`, but the current single-hart **RVV PMA-visible client window is
  `0x70200000`**. Generated macros use the client address. The QEMU Spike
  `cute-tcm=true` option maps that 2 MiB window.

This first checker uses hart-quiescent checkpoints. Fine-grained task waits
while unrelated operations on the same hart remain outstanding, additional
profiles/multicore, CUTE floating point, scalar write observation, and inspection
of internal scratchpads/vector registers are
later work. SG ports have observation hooks, but the first profile's unit-stride
tests do not constitute SG functional coverage.

## Build

Initialize the required pinned submodules. Activate a tool environment containing
the project's Java/SBT/firtool/Verilator tools, a bare-metal RV64 compiler with
`htif_nano.specs` and RVV intrinsics, CMake, C++17, Python with PyYAML/jsonschema,
and QEMU prerequisites (Meson, Ninja, pkg-config, GLib development files, zlib).
The QEMU Python may be newer than the runner's Python. Keep dependency-library
search paths consistent with the compiler environment.

```sh
python3 tools/runner/cute-system-build.py \
  --out /absolute/path/system-build \
  --cc /absolute/path/riscv-none-elf-gcc --jobs 16
```

Optional QEMU configure arguments are repeatable, for example
`--qemu-configure-arg=--extra-ldflags=...` for an isolated dependency prefix.
The builder checks generated APIs, creates deterministic inputs and platform
macros, compiles the SDK and verifier, runs verifier behavior tests, and builds
QEMU and RTL. RTL directories are keyed by hardware source contents, including
uncommitted files and initialized hardware submodules, profile, and tool versions.

`build-manifest.json` records paths, hashes and source contents; `build-commands.json`
and `logs/` record the actual commands and diagnostics. An existing simulator
filename is not sufficient evidence that the source is current.

The run entrypoint requires this build manifest, checks current sources and
artifact hashes, and saves an immutable copy in each run directory so a later
rebuild cannot change that run's provenance.

The Chipyard assembly rule disables reuse of an assembly output at a previous
path and verifies the requested JAR exists and is nonempty. This is necessary
when the source fingerprint moves a build into a new output directory.

## Run

Use artifact paths from `build-manifest.json` (the simulator is inside its
fingerprinted RTL directory):

```sh
python3 tools/runner/cute-system.py \
  --build-manifest /absolute/path/system-build/build-manifest.json \
  --simulator /absolute/path/to/simulator-system \
  --qemu /absolute/path/system-build/build/qemu/qemu-system-riscv64 \
  --verifier /absolute/path/system-build/build/verify/cute-system-verify \
  --rtl-elf /absolute/path/system-build/build/sdk/system/system_int8_verilator.riscv \
  --qemu-elf /absolute/path/system-build/build/sdk/system/system_int8_qemu.riscv \
  --fixtures /absolute/path/system-build/fixtures \
  --dram-config "$PWD/configs/memconfigs/dramsim2/dramsim2_ini_48GB_per_s" \
  --out /absolute/path/new-run --mode online --poll-seconds 60
```

For TCM use the two `system_tcm_*.riscv` binaries and
`--case cute-sdk/tests/system/tcm-case.json`. `--mode offline` runs the same C++
engine after simulation; online mode always replays the saved stream offline and
requires identical reports. Output directories must be new. S1 TSV transport
requires paths without whitespace.

The QEMU golden is checked against the independent Python integer oracle before
RTL runs. Both ELFs' symbols are independently resolved, so their addresses need
not match. The initial actual image comes from the RTL ELF's load segments and
explicit BSS initialization, never from QEMU output.

`report.json` contains PASS/FAIL and exact transaction/checkpoint counts, or an
explicit runner ERROR/TIMEOUT. Parse errors, unknown bytes, missing events and
incomplete runs are INVALID. All non-success states exit nonzero. Each run keeps
commands, artifact hashes, source fingerprints, task/output mappings, golden,
trace, simulator exit status, and online/offline reports. Online failure stops
only that run's process group. A successful host `SV_RUN_END,0` footer is required;
EOF by itself cannot make a run pass.

## Trace and synchronization contract

`trace/catalogs/cute_trace.json` remains the event definition source. Generate
Scala/Python and C++ event identity/arity with `tools/trace/gen_cute_trace.py`.

| Event | Meaning |
|---|---|
| `SystemMemory.request` | Actual A handshake: hart/engine/port/source, per-port event sequence, opcode, address, size, beat width, byte mask, data |
| `SystemMemory.response` | Actual D handshake: same identity and sequence stream, response opcode/size/data and denied/corrupt |
| `SystemMemory.progress` | Complete-cycle per-port event count and outstanding watermark, every 256 cycles |
| `SystemCheckpoint.mark` | RoCC TRACE_MARK accepted, with per-hart sequence and task key |
| `SystemCheckpoint.returned` | Corresponding RoCC return consumed by the CPU |

Enable using `+cute_sys_trace=1`. At the selected client boundaries each
transaction is one complete beat; unsupported shapes are rejected by the
verifier. CUTE uses engine 0/port 0; RVV uses engine 1, ports 0/1 for normal
read/write and 2+ for SG. Source lifetimes are tracked independently per port.

The SDK calls `cute_wait_task()` for relevant CUTE tasks, then the checkpoint
wrapper uses a pre-fence, TRACE_MARK with an explicit dependent result read,
and a post-fence. Current Shuttle/Saturn fence drains preceding vector activity.
The legacy CUTE busy query is not a completion guarantee.

Before exiting, call `cute_checkpoint_finish()`. Its 512-cycle CSR wait lets every
configured port emit a final watermark after the last checkpoint return. This
detects loss of an entire request/response pair, including a port's final pair;
pairing alone cannot detect that loss. A required port without a final watermark
is INVALID. This wait does not read output data or wait for host analysis.

The C++ engine checks unresolved same-byte read/write or write/write conflicts,
response pairing, returned read data, and marker acceptance/return ordering.
In this first profile, observed stores must stay within the declared task output
regions of unfinished task versions. Stores after completion require a newly
declared output version, and final port watermarks must cover the entire observed
request/response sequence. Additional writable workspaces must be described before extending the
profile to workloads that use them.
Every task output byte must have a new successful write acknowledgement, including
expected zero bytes. Reusing a buffer cannot overwrite the already compared
task version. Same-cycle records are grouped before evaluation; unproven
same-cycle conflicts are conservatively rejected.

## Verification and fault injection

```sh
python3 tools/verify/test_system_verify.py \
  --verifier /absolute/path/build/verify/cute-system-verify -v
python3 tools/trace/gen_cute_trace.py --check
python3 tools/runner/cute-gen-scala-config.py --check
```

Runtime `--ack-delay 3 --marker-delay 17` holds successful store acknowledgements
and marker responses to test ordering. Delays default to zero and are applied at
the actual handshakes, not by editing timestamps. Marker acceptance-to-return is
18 cycles with marker delay 17.

For RTL negative runs use `system_int8_fault1.riscv` (missing CUTE wait) or
`system_int8_fault2.riscv` (wrong vector output), while keeping the normal QEMU
ELF and its independently checked golden. These fault programs intentionally keep
running; online verification must report the mismatch/order failure and stop
them before the simulation cycle limit. Use a short polling interval for tests.
The differing ELF hashes are recorded intentionally for these negative cases.

`system_qemu_contract.riscv` is a separate QEMU-only test. It checks signed extrema,
bias modes, rectangular transpose and strides, wraparound accumulation, output
padding, a three-slot FIFO with ID reuse, and caught illegal-instruction failures
for overflow/unsupported operations. Its CPU result loads are confined to the
fast functional-model test; the RTL workflow still uses ack reconstruction.

## Model stage extension

BERT B1–B6 and LLaMA L1–L4 use the same verifier and checkpoint contract.
See [migration sources and numeric contract](../../cute-sdk/tests/models/README.md)
and [SDK verification docs](../../doc/sdk-doc/docs/testing/system-verification.md).
`cute-model-build.py` builds separate quick/original-shape profiles using a
source-verified S1 simulator/QEMU; `cute-model-run.py` runs a recorded stage suite.

Integer QEMU references remain exact. Floating mathematical calibration uses
explicit per-output tolerance, while RTL/QEMU comparison remains byte exact.
L4 supports independent NumPy operations on previously calibrated upstream task
outputs, so approximate SiLU values crossing quantization thresholds are checked
compositionally without allowing integer mismatches. Current/future dependencies
are rejected. Derived references and hashes are preserved in `calibration/`.
`test_model_oracle.py` covers these calibration boundaries.
