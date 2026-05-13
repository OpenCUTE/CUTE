#!/usr/bin/env python3
"""CUTE Config Codegen — generate C headers and JSON from YAML manifests."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from cute_config_common import (
    ConfigError,
    chipyard_isa_version,
    chipyard_vector_version,
    compute_fingerprint,
    find_cute_root,
    load_yaml,
    manifest_path,
    resolve_arg_path,
)


@dataclass
class ResolvedConfig:
    chipyard: Dict[str, Any]
    chipyard_path: Path
    cute_config: Dict[str, Any]
    cute_config_path: Path
    isa: Dict[str, Any]
    isa_path: Path
    vector: Dict[str, Any]
    vector_path: Path


def _mask_hex(width: int) -> str:
    if width >= 64:
        return "0xFFFFFFFFFFFFFFFFUL"
    return "0x%XUL" % ((1 << width) - 1)


def _field_width(field: Dict[str, Any]) -> int:
    return field["hi"] - field["lo"] + 1


def _is_single_fullwidth(fields: Optional[List[Dict[str, Any]]]) -> bool:
    if not fields or len(fields) != 1:
        return False
    f = fields[0]
    return f["hi"] == 63 and f["lo"] == 0


def _c_macro_name(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch.upper())
        else:
            out.append("_")
    return "".join(out)


class ConfigGenerator:
    def __init__(self, root: Path, verbose: bool = False):
        self.root = root.resolve()
        self.cwd = Path.cwd().resolve()
        self.verbose = verbose

    def log(self, msg: str) -> None:
        if self.verbose:
            print("  - %s" % msg)

    # ── resolution ──

    def resolve_all(self, chipyard_id_or_path: str) -> ResolvedConfig:
        cy_path = resolve_arg_path(self.root, self.cwd, chipyard_id_or_path, "chipyard_config")
        self.log("load chipyard_config: %s" % cy_path)
        chipyard = load_yaml(cy_path)

        cute_id = chipyard.get("cute", {}).get("config", "")
        cc_path = manifest_path(self.root, "cute_config", cute_id)
        self.log("load cute_config: %s" % cc_path)
        cute_config = load_yaml(cc_path)

        isa_id = chipyard_isa_version(chipyard) or ""
        isa_path = manifest_path(self.root, "cute_isa_version", isa_id)
        self.log("load isa_version: %s" % isa_path)
        isa = load_yaml(isa_path)

        vec_id = chipyard_vector_version(chipyard) or ""
        vec_path = manifest_path(self.root, "vector_version", vec_id)
        self.log("load vector_version: %s" % vec_path)
        vector = load_yaml(vec_path)

        return ResolvedConfig(
            chipyard=chipyard, chipyard_path=cy_path,
            cute_config=cute_config, cute_config_path=cc_path,
            isa=isa, isa_path=isa_path,
            vector=vector, vector_path=vec_path,
        )

    def _all_paths(self, r: ResolvedConfig) -> List[Path]:
        return [r.chipyard_path, r.cute_config_path, r.isa_path, r.vector_path]

    def should_skip(self, r: ResolvedConfig, output_dir: Path, force: bool) -> bool:
        if force:
            return False
        fp_path = output_dir / "config_fingerprint.txt"
        if not fp_path.exists():
            return False
        stored = fp_path.read_text(encoding="utf-8").strip()
        current = compute_fingerprint(self._all_paths(r))
        return stored == current

    # ── product 1: instruction.h ──

    def _iter_instructions(self, isa: Dict[str, Any]):
        groups = isa.get("groups", {})
        for group_name in ("ygjk", "cute"):
            group = groups.get(group_name, {})
            if not isinstance(group, dict):
                continue
            offset = group.get("rocc_funct_offset", 0)
            for inst in group.get("instructions", []) or []:
                if isinstance(inst, dict):
                    yield group_name, offset, inst

    def generate_instruction_h(self, isa: Dict[str, Any], output_dir: Path) -> Path:
        out = output_dir / "instruction.h"
        lines: List[str] = []
        now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

        lines.append("/**")
        lines.append(" * Auto-generated from %s" % isa.get("id", "isa"))
        lines.append(" * DO NOT EDIT MANUALLY")
        lines.append(" * Generated at: %s" % now)
        lines.append(" */")
        lines.append("")
        lines.append("#ifndef CUTE_INSTRUCTION_H")
        lines.append("#define CUTE_INSTRUCTION_H")
        lines.append("")
        lines.append("#include <stdint.h>")
        lines.append("")

        # ISA overview
        rocc = isa.get("rocc", {})
        opcode = rocc.get("opcode", "0x0B")
        cute_offset = rocc.get("cute_internal_offset", 64)
        lines.append("// ========================================")
        lines.append("// ISA Overview")
        lines.append("// ========================================")
        lines.append("// RoCC opcode: %s (custom-0)" % opcode)
        lines.append("// YGJK group:  funct offset 0 (RoCC funct field direct)")
        lines.append("// CUTE group:  funct offset %s (RoCC funct field + %s)" % (cute_offset, cute_offset))
        lines.append("")

        # Software ABI / data layout requirements
        software = isa.get("software", {})
        data_layout = software.get("data_layout", {}) if isinstance(software, dict) else {}
        if isinstance(data_layout, dict) and data_layout:
            requirements = data_layout.get("requirements", [])
            if not isinstance(requirements, list):
                requirements = []
            default_align = data_layout.get("alignment_bytes")
            default_padding = data_layout.get("padding", "")
            lines.append("// ========================================")
            lines.append("// Software Data Layout Requirements")
            lines.append("// ========================================")
            if default_align is not None:
                lines.append("#define CUTE_SOFTWARE_DATA_ALIGNMENT_BYTES %sUL" % default_align)
            if default_padding == "zero":
                lines.append("#define CUTE_SOFTWARE_DATA_PADDING_ZERO 1")
            for req in requirements:
                if not isinstance(req, dict):
                    continue
                req_name = str(req.get("name", "requirement"))
                macro_prefix = "CUTE_SOFTWARE_%s" % _c_macro_name(req_name)
                align = req.get("alignment_bytes", default_align)
                padding = req.get("padding", default_padding)
                applies_to = req.get("applies_to", [])
                if not isinstance(applies_to, list):
                    applies_to = []
                desc = str(req.get("description", ""))
                if align is not None:
                    lines.append("#define %s_ALIGNMENT_BYTES %sUL" % (macro_prefix, align))
                if padding == "zero":
                    lines.append("#define %s_PADDING_ZERO 1" % macro_prefix)
                lines.append("// %s" % req_name)
                if applies_to:
                    lines.append("// Applies to: %s" % ", ".join(str(value) for value in applies_to))
                if desc:
                    lines.append("// %s" % desc)
            lines.append("")

        # Inline YGJK primitives (only the subset used by wrapper functions)
        lines.append("// ========================================")
        lines.append("// RoCC Instruction Encoding Primitives")
        lines.append("// ========================================")
        lines.append("")
        lines.append("#define _CUTE_CUSTOM0  0x0B")
        lines.append("")
        lines.append("#define _CUTE_GET_VALUE1(x) #x")
        lines.append("#define _CUTE_GET_VALUE(x) _CUTE_GET_VALUE1(x)")
        lines.append("")
        lines.append("#define _CUTE_ENC(opcode,rd,xs2,xs1,xd,rs1,rs2,funct7) \\")
        lines.append("    opcode                      | \\")
        lines.append("    (rd     <<(7))              | \\")
        lines.append("    (xs2    <<(7+5))            | \\")
        lines.append("    (xs1    <<(7+5+1))          | \\")
        lines.append("    (xd     <<(7+5+1+1))        | \\")
        lines.append("    (rs1    <<(7+5+1+1+1))      | \\")
        lines.append("    (rs2    <<(7+5+1+1+1+5))    | \\")
        lines.append("    (funct7 <<(7+5+1+1+1+5+5))")
        lines.append("")
        lines.append("#define YGJK_INS_RRR(rd, rs1, rs2, funct) \\")
        lines.append("{                                           \\")
        lines.append("    __asm__ __volatile__ (                   \\")
        lines.append("        \"sd t0, -24(sp)\\n\\t\"              \\")
        lines.append("        \"sd t1, -16(sp)\\n\\t\"              \\")
        lines.append("        \"sd t2,  -8(sp)\\n\\t\"              \\")
        lines.append("        \"add t1, zero, %1\\n\\t\"            \\")
        lines.append("        \"add t2, zero, %2\\n\\t\"            \\")
        lines.append("        \".word \" _CUTE_GET_VALUE(_CUTE_ENC(_CUTE_CUSTOM0,5,1,1,1,6,7,funct)) \"\\n\\t\" \\")
        lines.append("        \"add %0, zero, t0\\n\\t\"            \\")
        lines.append("        \"ld t0, -24(sp)\\n\\t\"              \\")
        lines.append("        \"ld t1, -16(sp)\\n\\t\"              \\")
        lines.append("        \"ld t2,  -8(sp)\\n\\t\"              \\")
        lines.append("        :\"=r\"(rd)                           \\")
        lines.append("        :\"r\" (rs1) , \"r\" (rs2)            \\")
        lines.append("        :\"t0\",\"t1\",\"t2\",\"memory\"           \\")
        lines.append("        );                                   \\")
        lines.append("}")
        lines.append("")

        # (b) funct codes
        lines.append("// ========================================")
        lines.append("// Instruction Function Codes")
        lines.append("// ========================================")
        lines.append("// YGK/RoCC Interface Instructions (funct 1-8): direct values")
        lines.append("// CUTE Internal Instructions (funct + 64): need to add 64")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            rocc_funct = inst.get("rocc_funct", inst.get("funct", 0))
            macro = "CUTE_INST_FUNCT_%s" % name
            desc = inst.get("description", "")
            comment = desc if gname == "ygjk" else "[+64] %s" % desc
            lines.append("#define %-45s %s  // %s" % (macro, rocc_funct, comment))
        lines.append("")

        # (c) field definitions
        lines.append("// ========================================")
        lines.append("// Instruction Field Definitions")
        lines.append("// ========================================")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            funct = inst.get("funct", 0)
            desc = inst.get("description", "")
            lines.append("// Instruction: %s (funct = %s)" % (name, funct))
            lines.append("// %s" % desc)
            fields_dict = inst.get("fields", {})
            if not isinstance(fields_dict, dict):
                fields_dict = {}
            for cfg_key in ("cfgData1", "cfgData2"):
                cfg_fields = fields_dict.get(cfg_key, [])
                if cfg_fields:
                    lines.append("// %s fields:" % cfg_key)
                    for f in cfg_fields:
                        fname = f["name"]
                        w = _field_width(f)
                        macro_base = "CUTE_INST_%s_%s_%s" % (name, cfg_key.upper(), fname)
                        lines.append("#define %-60s %s" % (macro_base + "_HI", f["hi"]))
                        lines.append("#define %-60s %s  // %s" % (macro_base + "_LO", f["lo"], f.get("description", "")))
                        if "max_value" in f:
                            lines.append("#define %-60s %sUL  // 软件填值不应超过此值" % (macro_base + "_MAX_VALUE", f["max_value"]))
                        lines.append("#define %-60s %s" % (macro_base + "_WIDTH", w))
            lines.append("")

        # (d) extract macros
        lines.append("// ========================================")
        lines.append("// Field Extraction Macros")
        lines.append("// ========================================")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            fields_dict = inst.get("fields", {})
            if not isinstance(fields_dict, dict):
                fields_dict = {}
            for cfg_key in ("cfgData1", "cfgData2"):
                cfg_fields = fields_dict.get(cfg_key, [])
                if cfg_fields:
                    param = cfg_key.lower()
                    lines.append("// Extract fields for %s (%s)" % (name, cfg_key))
                    for f in cfg_fields:
                        w = _field_width(f)
                        mask = _mask_hex(w)
                        macro = "CUTE_GET_%s_%s_%s(%s)" % (name, cfg_key.upper(), f["name"], param)
                        lines.append("#define %s (((%s) >> %s) & %s)" % (macro, param, f["lo"], mask))
                    lines.append("")

        # (e) assembly macros
        lines.append("// ========================================")
        lines.append("// Field Assembly Macros")
        lines.append("// ========================================")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            fields_dict = inst.get("fields", {})
            if not isinstance(fields_dict, dict):
                fields_dict = {}
            for cfg_key in ("cfgData1", "cfgData2"):
                cfg_fields = fields_dict.get(cfg_key, [])
                if not cfg_fields:
                    continue
                params = ", ".join(f["name"].lower() for f in cfg_fields)
                macro_name = "CUTE_ASSEMBLY_%s_%s(%s)" % (name, cfg_key.upper(), params)
                lines.append("// Assemble %s for %s" % (cfg_key, name))
                # fields sorted by hi descending
                sorted_fields = sorted(cfg_fields, key=lambda f: f["hi"], reverse=True)
                parts = []
                for f in sorted_fields:
                    w = _field_width(f)
                    mask = _mask_hex(w)
                    parts.append("((((uint64_t)(%s)) & %s) << %s)" % (f["name"].lower(), mask, f["lo"]))
                lines.append("#define %s ( \\" % macro_name)
                for i, part in enumerate(parts):
                    is_last = i == len(parts) - 1
                    suffix = ")" if is_last else " | \\"
                    lines.append("  %s%s" % (part, suffix))
                lines.append("")

        # (f) documentation
        lines.append("/*")
        lines.append(" * ========================================")
        lines.append(" * Instruction Set Documentation")
        lines.append(" * ========================================")
        lines.append(" */")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            funct = inst.get("funct", 0)
            rocc_funct = inst.get("rocc_funct", funct)
            desc = inst.get("description", "")
            ret_desc = inst.get("return_description", "")
            inst_type = "YGK/RoCC Interface" if gname == "ygjk" else "CUTE Internal"
            funct_note = str(funct) if gname == "ygjk" else "%s + %s = %s" % (funct, offset, rocc_funct)
            lines.append("/*")
            lines.append(" * Instruction: %s" % name)
            lines.append(" * Type: %s" % inst_type)
            lines.append(" * Funct: %s" % funct_note)
            lines.append(" * Description: %s" % desc)
            lines.append(" * Return: %s" % ret_desc)
            lines.append(" *")
            fields_dict = inst.get("fields", {})
            if not isinstance(fields_dict, dict):
                fields_dict = {}
            for cfg_key in ("cfgData1", "cfgData2"):
                cfg_fields = fields_dict.get(cfg_key, [])
                if cfg_fields:
                    lines.append(" * %s:" % cfg_key)
                    for f in cfg_fields:
                        lines.append(" *   [%s:%s] %s - %s" % (f["hi"], f["lo"], f["name"], f.get("description", "")))
                else:
                    lines.append(" * %s: Not used" % cfg_key)
            lines.append(" */")
            lines.append("")

        # (g) wrapper functions
        lines.append("// ========================================")
        lines.append("// Auto-Generated Wrapper Functions")
        lines.append("// ========================================")
        lines.append("")
        for gname, offset, inst in self._iter_instructions(isa):
            name = inst.get("name", "")
            desc = inst.get("description", "")
            ret_desc = inst.get("return_description", "")
            funct_macro = "CUTE_INST_FUNCT_%s" % name
            func_name = "CUTE_%s" % name

            fields_dict = inst.get("fields", {})
            if not isinstance(fields_dict, dict):
                fields_dict = {}
            d1 = fields_dict.get("cfgData1", [])
            d2 = fields_dict.get("cfgData2", [])

            all_fields = d1 + d2
            if all_fields:
                param_list = ", ".join("uint64_t %s" % f["name"].lower() for f in all_fields)
            else:
                param_list = "void"

            lines.append("// %s" % desc)
            lines.append("// 返回值: %s" % ret_desc)
            lines.append("uint64_t %s(%s)" % (func_name, param_list))
            lines.append("{")

            d1_packed = len(d1) > 1 or (len(d1) == 1 and not _is_single_fullwidth(d1))
            d2_packed = len(d2) > 1 or (len(d2) == 1 and not _is_single_fullwidth(d2))

            if d1_packed:
                args1 = ", ".join(f["name"].lower() for f in d1)
                lines.append("    uint64_t cfgData1 = CUTE_ASSEMBLY_%s_CFGDATA1(%s);" % (name, args1))
            if d2_packed:
                args2 = ", ".join(f["name"].lower() for f in d2)
                lines.append("    uint64_t cfgData2 = CUTE_ASSEMBLY_%s_CFGDATA2(%s);" % (name, args2))

            if d1_packed:
                rs1 = "cfgData1"
            elif d1:
                rs1 = d1[0]["name"].lower()
            else:
                rs1 = "0"

            if d2_packed:
                rs2 = "cfgData2"
            elif d2:
                rs2 = d2[0]["name"].lower()
            else:
                rs2 = "0"

            lines.append("    uint64_t res1=0;")
            lines.append("    YGJK_INS_RRR(res1, %s, %s, %s);" % (rs1, rs2, funct_macro))
            lines.append("    return res1;")
            lines.append("}")
            lines.append("")

        lines.append("")
        lines.append("#endif // CUTE_INSTRUCTION_H")
        out.write_text("\n".join(lines), encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    # ── product 2: isa.json ──

    def generate_isa_json(self, isa: Dict[str, Any], output_dir: Path) -> Path:
        out = output_dir / "isa.json"
        with out.open("w", encoding="utf-8") as fh:
            json.dump(isa, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        self.log("generated: %s" % out)
        return out

    # ── product 3: cute_fpe.h ──

    def generate_cute_fpe_h(self, isa: Dict[str, Any], output_dir: Path) -> Path:
        out = output_dir / "cute_fpe.h"
        lines: List[str] = []
        now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

        enums = isa.get("enums", {})
        edt = enums.get("ElementDataType", {})
        values = edt.get("values", [])

        lines.append("/**")
        lines.append(" * Auto-generated from %s enums.ElementDataType" % isa.get("id", "isa"))
        lines.append(" * DO NOT EDIT MANUALLY")
        lines.append(" * Generated at: %s" % now)
        lines.append(" */")
        lines.append("")
        lines.append("#ifndef CUTE_FPE_H")
        lines.append("#define CUTE_FPE_H")
        lines.append("")

        # enum defines
        lines.append("// Element Type Definitions")
        for v in values:
            name = v.get("name", "")
            val = v.get("value", 0)
            desc = v.get("description", "")
            lines.append("#define CUTE%s %s  // %s" % (name, val, desc))
        if values:
            lines.append("")
            lines.append("#define CUTE_MAX_ELEMENT_TYPE %s" % values[-1].get("value", 0))
        lines.append("")

        # A bitwidth
        lines.append("// Data Type A Bit Width Queries")
        lines.append("#define CUTE_GET_ADATA_BITWIDTH(elem_type) \\")
        for v in values:
            bits = v.get("a_bits", 8)
            lines.append("    ((elem_type) == %s ? %s : \\" % (v["value"], bits))
        lines.append("    32" + ")" * len(values))
        lines.append("")

        # B bitwidth
        lines.append("// Data Type B Bit Width Queries")
        lines.append("#define CUTE_GET_BDATA_BITWIDTH(elem_type) \\")
        for v in values:
            bits = v.get("b_bits", 8)
            lines.append("    ((elem_type) == %s ? %s : \\" % (v["value"], bits))
        lines.append("    32" + ")" * len(values))
        lines.append("")

        # name strings
        lines.append("// Data Type Name Strings")
        lines.append("#define CUTE_DATATYPE_NAME(elem_type) \\")
        for v in values:
            raw_name = v.get("name", "")
            display = raw_name.replace("DataType", "", 1)
            display = display.replace("F32", "FP32") if display.endswith("F32") else display
            lines.append("    ((elem_type) == %s ? \"%s\" : \\" % (v["value"], display))
        lines.append("    \"Unknown\"" + ")" * len(values))
        lines.append("")

        # stride macros
        lines.append("// Stride Calculation Macros")
        lines.append("#define CUTE_CALC_M_STRIDE(elem_type, k) \\")
        lines.append("    ((k) * CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
        lines.append("")
        lines.append("#define CUTE_CALC_N_STRIDE(elem_type, k) \\")
        lines.append("    ((k) * CUTE_GET_BDATA_BITWIDTH(elem_type) / 8)")
        lines.append("")
        lines.append("#define CUTE_CALC_K_STRIDE_A(elem_type) \\")
        lines.append("    (CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
        lines.append("")
        lines.append("#define CUTE_CALC_K_STRIDE_B(elem_type) \\")
        lines.append("    (CUTE_GET_BDATA_BITWIDTH(elem_type) / 8)")
        lines.append("")

        lines.append("#endif // CUTE_FPE_H")
        out.write_text("\n".join(lines), encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    # ── product 4: cute_config.h ──

    def generate_cute_config_h(self, r: ResolvedConfig, output_dir: Path) -> Path:
        out = output_dir / "cute_config.h"
        cc = r.cute_config
        cy = r.chipyard
        lines: List[str] = []
        now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

        lines.append("/**")
        lines.append(" * Auto-generated from CuteConfig + ChipyardConfig")
        lines.append(" * DO NOT EDIT MANUALLY")
        lines.append(" * Generated at: %s" % now)
        lines.append(" */")
        lines.append("")
        lines.append("#ifndef CUTE_CONFIG_H")
        lines.append("#define CUTE_CONFIG_H")
        lines.append("")
        lines.append("#include <stdint.h>")
        lines.append("#include <stdbool.h>")
        lines.append("")
        lines.append("// ChipyardConfig: %s" % cy.get("id", ""))
        lines.append("// CuteConfig: %s" % cc.get("id", ""))

        # CUTE accelerator
        reduce_wb = cc.get("ReduceWidthByte", 0)
        result_wb = cc.get("ResultWidthByte", 0)

        lines.append("")
        lines.append("// === CUTE Accelerator (from cute_config) ===")
        lines.append("#define CUTE_TENSOR_M             %s" % cc.get("Tensor_M"))
        lines.append("#define CUTE_TENSOR_N             %s" % cc.get("Tensor_N"))
        lines.append("#define CUTE_TENSOR_K             %s" % cc.get("Tensor_K"))
        lines.append("#define CUTE_MATRIX_M             %s" % cc.get("Matrix_M"))
        lines.append("#define CUTE_MATRIX_N             %s" % cc.get("Matrix_N"))
        lines.append("#define CUTE_REDUCE_WIDTH_BYTE    %s" % reduce_wb)
        lines.append("#define CUTE_REDUCE_WIDTH         %s    // reduce_width_byte * 8" % (reduce_wb * 8))
        lines.append("#define CUTE_RESULT_WIDTH_BYTE    %s" % result_wb)
        lines.append("#define CUTE_RESULT_WIDTH         %s     // result_width_byte * 8" % (result_wb * 8))
        lines.append("#define CUTE_RESULT_FIFO_DEPTH    %s" % cc.get("ResultFIFODepth"))
        lines.append("#define CUTE_OUTSIDE_DATA_WIDTH   %s" % cc.get("outsideDataWidth"))
        lines.append("#define CUTE_MMU_ADDR_WIDTH       %s" % cc.get("MMUAddrWidth"))
        lines.append("#define CUTE_LLC_SOURCE_MAX_NUM   %s" % cc.get("LLCSourceMaxNum"))
        if reduce_wb:
            lines.append("#define CUTE_REDUCE_GROUP_SIZE    %s" % (cc.get("Tensor_K", 0) // reduce_wb))

        # Tensor task
        if any(key in cc for key in (
            "ApplicationMaxTensorSize",
            "Convolution_Input_Height_Weight_Dim_Max",
            "KernelSizeMax",
            "StrideSizeMax",
        )):
            lines.append("")
            lines.append("// === Tensor Task (from cute_config) ===")
            lines.append("#define CUTE_APPLICATION_MAX_TENSOR_SIZE %s" % cc.get("ApplicationMaxTensorSize"))
            lines.append("#define CUTE_CONV_INPUT_MAX      %s" % cc.get("Convolution_Input_Height_Weight_Dim_Max"))
            lines.append("#define CUTE_CONV_KERNEL_SIZE_MAX %s" % cc.get("KernelSizeMax"))
            lines.append("#define CUTE_CONV_STRIDE_SIZE_MAX %s" % cc.get("StrideSizeMax"))

        # MMU
        mmu = cc.get("MMUParams", {})
        if mmu:
            lines.append("")
            lines.append("// === MMU (from cute_config.MMUParams) ===")
            lines.append("#define CUTE_MMU_VPN_BITS         %s" % mmu.get("vpnBits"))
            lines.append("#define CUTE_MMU_PPN_BITS         %s" % mmu.get("ppnBits"))
            lines.append("#define CUTE_MMU_PGIDX_BITS       %s" % mmu.get("pgIdxBits"))
            lines.append("#define CUTE_MMU_VADDR_BITS       %s" % mmu.get("vaddrBits"))
            lines.append("#define CUTE_MMU_PADDR_BITS       %s" % mmu.get("paddrBits"))
            lines.append("#define CUTE_MMU_CORE_PADDR_BITS  %s" % mmu.get("corePAddrBits"))

        # FPE
        fpe = cc.get("FPEparams", {})
        if fpe:
            lines.append("")
            lines.append("// === FPE (from cute_config.FPEparams) ===")
            lines.append("#define CUTE_FPE_MIN_GROUP_SIZE   %s" % fpe.get("MinGroupSize"))
            lines.append("#define CUTE_FPE_MIN_DATA_TYPE_WIDTH %s" % fpe.get("MinDataTypeWidth"))

        # SoC
        soc = cy.get("soc", {})
        core = soc.get("core", {})
        bus = soc.get("bus", {})
        cache = soc.get("cache", {})
        if soc:
            lines.append("")
            lines.append("// === SoC (from chipyard_config.soc) ===")
            lines.append("#define CUTE_SOC_CORE_KIND        \"%s\"" % core.get("kind", ""))
            lines.append("#define CUTE_SOC_CORE_COUNT       %s" % core.get("count"))
            lines.append("#define CUTE_SOC_SYSTEM_BUS_BITS  %s" % bus.get("system_bits"))
            lines.append("#define CUTE_SOC_MEMORY_BUS_BITS  %s" % bus.get("memory_bits"))
            if cache:
                if "inclusive_kb" in cache:
                    lines.append("#define CUTE_SOC_CACHE_INCLUSIVE_KB %s" % cache["inclusive_kb"])
                if "banks" in cache:
                    lines.append("#define CUTE_SOC_CACHE_BANKS     %s" % cache["banks"])

        # TCM (conditional)
        vec_id = chipyard_vector_version(cy) or "none"
        if core.get("kind") == "shuttle" and vec_id != "none":
            lines.append("")
            lines.append("// === TCM (shuttle + vector) ===")
            lines.append("#define CUTE_TCM_SUPPORTED 1")

        lines.append("#endif // CUTE_CONFIG_H")
        out.write_text("\n".join(lines), encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    # ── product 5: fingerprint ──

    def generate_fingerprint(self, r: ResolvedConfig, output_dir: Path) -> Path:
        out = output_dir / "config_fingerprint.txt"
        fp = compute_fingerprint(self._all_paths(r))
        out.write_text(fp + "\n", encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    # ── orchestrator ──

    def run(self, chipyard_id_or_path: str, output_dir: Optional[Path], force: bool) -> int:
        r = self.resolve_all(chipyard_id_or_path)
        cy_id = r.chipyard.get("id", "unknown")

        if output_dir is None:
            output_dir = self.root / "build" / "chipyard_configs" / cy_id / "generated"

        if self.should_skip(r, output_dir, force):
            print("[SKIP] %s — fingerprint unchanged" % cy_id)
            return 0

        output_dir.mkdir(parents=True, exist_ok=True)
        print("[GEN] %s -> %s" % (cy_id, output_dir))

        self.generate_instruction_h(r.isa, output_dir)
        self.generate_isa_json(r.isa, output_dir)
        self.generate_cute_fpe_h(r.isa, output_dir)
        self.generate_cute_config_h(r, output_dir)
        self.generate_fingerprint(r, output_dir)

        print("[OK] 5 products generated")
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CUTE Config Codegen — generate headers from YAML")
    p.add_argument("--chipyard-config", required=True,
                   help="ChipyardConfig id or path (e.g., cute4tops_scp128)")
    p.add_argument("--output", default=None,
                   help="Output directory (default: build/chipyard_configs/<id>/generated/)")
    p.add_argument("--root", default=None,
                   help="CUTE root directory (default: auto-detect)")
    p.add_argument("--force", action="store_true",
                   help="Regenerate even if fingerprint unchanged")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show detailed steps")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        output = Path(args.output) if args.output else None
        gen = ConfigGenerator(root, verbose=args.verbose)
        return gen.run(args.chipyard_config, output, args.force)
    except ConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
