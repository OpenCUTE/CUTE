# CuteConfig.scala Migration Report

Base directories:

- ChipyardConfig: `configs/chipyard_configs/`
- HWConfig: `configs/hwconfigs/`

## Converted

```text
CUTE32TopsSCP512Config
  chipyard: cute32tops_scp512.yaml
  hwconfig: cute32tops_scp512_dramsim48.yaml
CUTE16TopsSCP256Config
  chipyard: cute16tops_scp256.yaml
  hwconfig: cute16tops_scp256_dramsim48.yaml
CUTE8TopsSCP128Config
  chipyard: cute8tops_scp128.yaml
  hwconfig: cute8tops_scp128_dramsim48.yaml
CUTE4TopsSCP64Config
  chipyard: cute4tops_scp64.yaml
  hwconfig: cute4tops_scp64_dramsim48.yaml
CUTE2TopsSmallRocketConfig
  chipyard: cute2tops_small_rocket.yaml
  hwconfig: cute2tops_small_rocket_dramsim48.yaml
CUTE2TopsSmallBoomConfig
  chipyard: cute2tops_small_boom.yaml
  hwconfig: cute2tops_small_boom_dramsim48.yaml
CUTE16TopsSCP512Config
  chipyard: cute16tops_scp512.yaml
  hwconfig: cute16tops_scp512_dramsim48.yaml
CUTE8TopsSCP256Config
  chipyard: cute8tops_scp256.yaml
  hwconfig: cute8tops_scp256_dramsim48.yaml
CUTE4TopsSCP128Config
  chipyard: cute4tops_scp128.yaml
  hwconfig: cute4tops_scp128_dramsim48.yaml
CUTE2TopsSCP64Config
  chipyard: cute2tops_scp64.yaml
  hwconfig: cute2tops_scp64_dramsim32.yaml
CUTE8TopsSCP512Config
  chipyard: cute8tops_scp512.yaml
  hwconfig: cute8tops_scp512_dramsim48.yaml
CUTE4TopsSCP256Config
  chipyard: cute4tops_scp256.yaml
  hwconfig: cute4tops_scp256_dramsim48.yaml
CUTE2TopsSCP128Config
  chipyard: cute2tops_scp128.yaml
  hwconfig: cute2tops_scp128_dramsim48.yaml
CUTE1TopsSCP64Config
  chipyard: cute1tops_scp64.yaml
  hwconfig: cute1tops_scp64_dramsim48.yaml
CUTE4TopsSCP512Config
  chipyard: cute4tops_scp512.yaml
  hwconfig: cute4tops_scp512_dramsim48.yaml
CUTE2TopsSCP256Config
  chipyard: cute2tops_scp256.yaml
  hwconfig: cute2tops_scp256_dramsim48.yaml
CUTE1TopsSCP128Config
  chipyard: cute1tops_scp128.yaml
  hwconfig: cute1tops_scp128_dramsim48.yaml
CUTE05TopsSCP64Config
  chipyard: cute05tops_scp64.yaml
  hwconfig: cute05tops_scp64_dramsim48.yaml
CUTE4TopsShuttle512D512V512M512Sysbus512Membus1CoreConfig
  chipyard: cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core.yaml
  hwconfig: cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48.yaml
```

## Skipped

```text
CUTE4TopsSCP128Configdebug
  Missing configs/cute_configs/CUTE_4Tops_128SCP_debug.yaml.
CUTE4TopsShuttle512D512V512M512Sysbus512Membus1CoreConfigdebug
  Shuttle debug ROB/printf mixins are not in chipyard_config.schema.json.
CUTE2TopsShuttle512D512V512M256Sysbus64Membus1CoreConfig
  Shuttle debug ROB/printf mixins are not in chipyard_config.schema.json.
CUTEShuttle512D512V256M4CoreConfig
  Missing WithCuteCoustomParams/CUTE parameter preset.
```

## Missing Work

- Add schema/codegen support for Shuttle debug mixins.
- Add `CUTE_4Tops_128SCP_debug.yaml` or map it to a non-debug preset.
- Decide whether vector-only Shuttle configs without CUTE are in scope.
