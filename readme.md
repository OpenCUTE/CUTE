# CUTE
CUTE is an CPU-centric and Ultra-utilized Tensor Engine project.

中文说明在此。

## Documentation

## Publications

[CUTE: A scalable CPU-centric and Ultra-utilized Tensor Engine for convolutions](https://www.sciencedirect.com/science/article/pii/S1383762124000432)

Paper PDF | IEEE Xplore | BibTeX | Presentation Slides | Presentation Video

## Architecture
![CUTE-arch](images/thiswork.png)
## Micro-Architecture
![CUTE-micro-arch](images/microarch.png)
## Sub-directories Overview
Some of the key directories are shown below.

```
.
├── src
│   └── main/scala         # design files
│       ├── CUTETOP.scala  # top module
├── cute-fpe               # mixed-precision PE project
│   ├── fpe                # RTL implementation of mixed-precision PE
│   └── ccode              # C code of gloden of float
├── cutetest               # C code implementation of different workloads project
│   ├── base_test          # basic conv/gemm test and basic software helper
│   ├── dramsim_config     # dramsim config for different dram bandwidth
│   ├── gemm_test          # different gemm test
│   ├── resnet50_test      # different resnet50 conv-vector fuse kernel test
│   └── transformer_test   # different bert&llama gemm-vector fuse kernel test
├── scripts                # scripts for agile development
├── CPU                    # List of CPUs with completed integration
│   ├── boom               # out-of-order superscalar core (BOOM)
│   ├── rocket             # in-order 1-issue core (Rocket)
│   └── shuttle            # in-order superscalar core (Shuttle)
```

## Prepare environment

"Before executing all subsequent steps, please complete the environment initialization first!"
```bash 
$ ./scripts/setup-env.sh
[CUTE-Setup-step-1] Script absolute path: .....

[CUTE-Setup-step-2] Updating CUTE git submodules.....
.....
[CUTE-Setup-step-2] CUTE git submodules updated.
.....

[CUTE-Setup-step-3] Setting up chipyard environment...
.....
[CUTE-Setup-step-3] Chipyard environment setup complete.

[CUTE-Setup-step-4] WIP : Additional setup steps will be added soon.
```


## Generate Verilog

## Generate CUTE-Test
```bash 
$ ./scripts/build_cute_test.sh
[CUTE-Setup-step-1] Script absolute path: .....

[CUTE-Setup-step-2] Updating CUTE git submodules.....
.....
[CUTE-Setup-step-2] CUTE git submodules updated.
.....

[CUTE-Setup-step-3] Setting up chipyard environment...
.....
[CUTE-Setup-step-3] Chipyard environment setup complete.

[CUTE-Setup-step-4] WIP : Additional setup steps will be added soon.
```


## Run Programs by Simulation

### Prepare environment

### Run with simulator

<!-- ### Run with fpga

### Run with EDA -->
