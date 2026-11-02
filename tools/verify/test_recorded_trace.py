#!/usr/bin/env python3
"""Damage a passing real RTL trace and require strict rejection of every case."""
import argparse
import json
from pathlib import Path
import subprocess


def record(line):
    if not line.startswith("CT,1,"):
        return None
    f = line.rstrip("\n").split(",")
    return f, int(f[4], 16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["trace", "manifest", "verifier", "out"]:
        parser.add_argument("--" + name, type=lambda v: Path(v).resolve(), required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    lines = args.trace.read_text().splitlines(keepends=True)
    records = [(i, *r) for i, line in enumerate(lines) if (r := record(line)) is not None]
    write_req = next(i for i, f, eid in records if eid == 18 and int(f[6], 16) == 0 and int(f[10], 16) in [0, 1])
    write_ack = next(i for i, f, eid in records if eid == 19 and int(f[6], 16) == 0 and int(f[10], 16) == 0)
    final_return = max(int(f[2], 16) for _, f, eid in records if eid == 21)
    second_mark = next(i for i, f, eid in records if eid == 20 and int(f[6], 16) == 2)
    last_reads = {i for i, f, eid in records if eid in [18, 19] and i > second_mark and
                  int(f[6], 16) == 1 and int(f[7], 16) == 0}
    final_progress = {i for i, f, eid in records if eid == 22 and int(f[6], 16) == 1 and
                      int(f[7], 16) == 0 and int(f[2], 16) >= final_return}
    if not last_reads or not final_progress:
        raise ValueError("expected the three-task INT8 system trace with final port watermarks")
    mutations = {}
    mutations["missing_ack"] = (lines[:write_ack] + lines[write_ack+1:], "INVALID")
    mutations["missing_read_request_response_pairs"] = ([line for i, line in enumerate(lines) if i not in last_reads], "INVALID")
    mutations["missing_final_port_watermark"] = ([line for i, line in enumerate(lines) if i not in final_progress], "INVALID")
    mutations["missing_run_footer"] = ([line for line in lines if not line.startswith("SV_RUN_END,")], "INVALID")
    for name, index, field, value, verdict in [
        ("denied_ack", write_ack, 13, "1", "FAIL"),
        ("wrong_write_data", write_req, 15, None, "FAIL"),
        ("malformed_trace", write_req, 15, "not_hex", "INVALID"),
    ]:
        changed = lines.copy()
        f = changed[index].rstrip("\n").split(",")
        f[field] = value if value is not None else f"{int(f[field], 16) ^ 1:x}"
        changed[index] = ",".join(f) + "\n"
        mutations[name] = (changed, verdict)
    results = []
    for name, (changed, expected) in mutations.items():
        trace = args.out / (name + ".log")
        trace.write_text("".join(changed))
        report = args.out / (name + ".json")
        with trace.open("rb") as source:
            result = subprocess.run([str(args.verifier), str(args.manifest), str(report)],
                                    stdin=source, capture_output=True, timeout=30)
        actual = json.loads(report.read_text())
        row = {"case": name, "expected": expected, "actual": actual["verdict"],
               "returncode": result.returncode, "detail": actual["detail"]}
        results.append(row)
        print(json.dumps(row), flush=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(r["expected"] == r["actual"] and r["returncode"] != 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
