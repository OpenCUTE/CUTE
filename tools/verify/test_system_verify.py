#!/usr/bin/env python3
"""Behavior tests for races, completeness, generations and strict comparison."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EVENTS = {e["name"]: e for e in json.loads((ROOT / "trace/catalogs/cute_trace.json").read_text())["events"]}
TASKS = {t["name"]: t["id"] for t in json.loads((ROOT / "trace/catalogs/cute_trace.json").read_text())["tasks"]}
VERIFIER = None
DATA = bytes((i * 7 + 1) & 255 for i in range(64))
FULL = (1 << 64) - 1


def event(name, cycle, **values):
    e = EVENTS[name]
    fields = [values[f["name"]] for f in e["fields"]]
    return "CT,1," + ",".join(f"{v:x}" for v in [cycle, TASKS[e["task"]], e["id"], *fields]) + "\n"


def req(cycle, source, address, store=False, data=DATA, mask=FULL):
    return event("SystemMemory.request", cycle, hart=0, engine=1, port=1 if store else 0,
                 event_seq=0, source=source, opcode=1 if store else 4, address=address,
                 lg_size=6, width_bytes=64, mask=mask, data=int.from_bytes(data, "little"))


def resp(cycle, source, store=False, data=DATA, denied=0):
    return event("SystemMemory.response", cycle, hart=0, engine=1, port=1 if store else 0,
                 event_seq=0, source=source, opcode=0 if store else 1, lg_size=6, width_bytes=64,
                 denied=denied, corrupt=0, data=int.from_bytes(data, "little"))


def mark(cycle, seq=1, key=1):
    return (event("SystemCheckpoint.mark", cycle, hart=0, seq=seq, key=key) +
            event("SystemCheckpoint.returned", cycle, hart=0, seq=seq, key=key))


def baseline():
    return [req(1, 0, 0x1000), resp(2, 0), req(3, 0, 0x2000, True),
            resp(4, 0, True), mark(5), "SV_RUN_END,0\n"]


def add_sequences_and_progress(lines):
    counts = {0: 0, 1: 0}
    active = {0: 0, 1: 0}
    maximum_cycle = 0
    result = []
    for line in "".join(lines).splitlines(keepends=True):
        if line.startswith("CT,1,"):
            f = line.rstrip("\n").split(",")
            if len(f) >= 5 and f[2] != "wrong":
                maximum_cycle = max(maximum_cycle, int(f[2], 16))
                eid = int(f[4], 16)
                if eid in [18, 19]:
                    port = int(f[7], 16)
                    f[8] = f"{counts[port]:x}"
                    counts[port] += 1
                    active[port] += 1 if eid == 18 else -1
                    line = ",".join(f) + "\n"
        if line.startswith("SV_RUN_END,"):
            for port in [0, 1]:
                result.append(event("SystemMemory.progress", maximum_cycle + 1, hart=0,
                                    engine=1, port=port, next_seq=counts[port],
                                    outstanding=max(0, active[port])))
        result.append(line)
    return result


class VerifyBehavior(unittest.TestCase):
    def check(self, lines, verdict, outputs=None, prepared=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.bin").write_bytes(DATA)
            (root / "zero.bin").write_bytes(bytes(64))
            manifest = ["CUTE_VERIFY_V1", "PORT 0 1 0", "PORT 0 1 1",
                        f"INIT 1000 40 {root}/input.bin", f"INIT 2000 40 {root}/zero.bin"]
            for seq, data in (outputs or [(1, DATA)]):
                (root / f"golden-{seq}.bin").write_bytes(data)
                manifest.append(f"OUTPUT 0 {seq:x} {seq:x} 2000 40 {root}/golden-{seq}.bin output")
            (root / "manifest.tsv").write_text("\n".join(manifest) + "\n")
            result = subprocess.run([str(VERIFIER), str(root / "manifest.tsv"), str(root / "report.json")],
                                    input="".join(lines if prepared else add_sequences_and_progress(lines)),
                                    text=True, capture_output=True, timeout=10)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["verdict"], verdict, report)
            self.assertEqual(result.returncode == 0, verdict == "PASS", report)
            return report

    def test_complete_ack_and_read(self):
        self.check(baseline(), "PASS")

    def test_same_cycle_marker_printed_before_ack(self):
        self.check([req(1, 0, 0x1000), resp(2, 0), req(3, 0, 0x2000, True),
                    mark(4), resp(4, 0, True), "SV_RUN_END,0\n"], "PASS")

    def test_disjoint_masks_and_out_of_order_responses(self):
        even = sum(1 << i for i in range(0, 64, 2))
        odd = FULL ^ even
        self.check([req(1, 0, 0x1000), req(1, 1, 0x1000), resp(2, 1), resp(3, 0),
                    req(4, 0, 0x2000, True, mask=even), req(4, 1, 0x2000, True, mask=odd),
                    resp(5, 1, True), resp(6, 0, True), mark(7), "SV_RUN_END,0\n"], "PASS")

    def test_wrong_store_data(self):
        lines = baseline(); lines[2] = req(3, 0, 0x2000, True, bytes(64))
        self.check(lines, "FAIL")

    def test_wrong_read_data(self):
        lines = baseline(); lines[1] = resp(2, 0, data=bytes(64))
        self.check(lines, "FAIL")

    def test_missing_ack(self):
        lines = baseline(); del lines[3]
        self.check(lines, "FAIL")

    def test_orphan_ack(self):
        self.check([resp(1, 0), "SV_RUN_END,0\n"], "INVALID")

    def test_reused_source(self):
        self.check([req(1, 0, 0x1000), req(2, 0, 0x1000)], "INVALID")

    def test_denied_response(self):
        lines = baseline(); lines[3] = resp(4, 0, True, denied=1)
        self.check(lines, "FAIL")

    def test_reader_before_writer_ack(self):
        self.check([req(1, 0, 0x2000, True), req(2, 0, 0x2000), resp(3, 0, True)], "FAIL")

    def test_writer_before_reader_response(self):
        self.check([req(1, 0, 0x2000), req(2, 0, 0x2000, True), resp(3, 0, data=bytes(64))], "FAIL")

    def test_extra_store_outside_outputs(self):
        self.check([req(1, 0, 0x3000, True), resp(2, 0, True), req(3, 0, 0x1000),
                    resp(4, 0), req(5, 0, 0x2000, True), resp(6, 0, True),
                    mark(7), "SV_RUN_END,0\n"], "FAIL")

    def test_store_after_task_completion_without_new_output_version(self):
        self.check(baseline()[:-1] + [req(6, 0, 0x2000, True), resp(7, 0, True),
                                     "SV_RUN_END,0\n"], "FAIL")

    def test_traffic_after_final_watermark(self):
        lines = add_sequences_and_progress(baseline())
        request = req(7, 0, 0x1000).strip().split(',');request[8] = '2'
        response = resp(8, 0).strip().split(',');response[8] = '3'
        lines = lines[:-1] + [','.join(request)+'\n', ','.join(response)+'\n', lines[-1]]
        self.check(lines, "INVALID", prepared=True)

    def test_unknown_bytes_are_not_zero(self):
        self.check([req(1, 0, 0x3000), resp(2, 0, data=bytes(64)), mark(3)], "INVALID")

    def test_known_zero_output_still_needs_store_ack(self):
        self.check([req(1, 0, 0x1000), resp(2, 0), mark(3), "SV_RUN_END,0\n"],
                   "INVALID", [(1, bytes(64))])

    def test_new_buffer_version_requires_new_writes(self):
        self.check(baseline()[:-1] + [mark(6, 2, 2), "SV_RUN_END,0\n"],
                   "INVALID", [(1, DATA), (2, DATA)])

    def test_buffer_reuse_keeps_prior_comparison(self):
        second = bytes((v + 1) & 255 for v in DATA)
        self.check(baseline()[:-1] + [req(6, 0, 0x2000, True, second), resp(7, 0, True),
                                     mark(8, 2, 2), "SV_RUN_END,0\n"],
                   "PASS", [(1, DATA), (2, second)])

    def test_no_footer(self):
        self.check(baseline()[:-1], "INVALID")

    def test_partial_final_record(self):
        self.check(baseline()[:-1] + ["SV_RUN_END,0"], "INVALID")

    def test_malformed_record_not_skipped(self):
        self.check(["CT,1,wrong\n", *baseline()], "INVALID")

    def test_cycle_regression(self):
        self.check([req(4, 0, 0x1000), resp(3, 0)], "INVALID")

    def test_missing_marker_response(self):
        lines = baseline(); lines[4] = event("SystemCheckpoint.mark", 5, hart=0, seq=1, key=1)
        self.check(lines, "INVALID")

    def test_memory_before_marker_response(self):
        lines = baseline()[:4] + [event("SystemCheckpoint.mark", 5, hart=0, seq=1, key=1),
                                  req(6, 0, 0x1000), resp(7, 0), "SV_RUN_END,0\n"]
        self.check(lines, "FAIL")

    def test_lost_request_and_response_pair(self):
        lines = add_sequences_and_progress([
            req(1, 0, 0x1000), resp(2, 0), req(3, 0, 0x1000), resp(4, 0),
            req(5, 0, 0x2000, True), resp(6, 0, True), mark(7), "SV_RUN_END,0\n"])
        # Remove the final read pair while keeping earlier reads and every output.
        # Pairing and golden comparison alone would pass; the watermark must fail.
        lines = [line for line in lines if not (line.startswith("CT,1,") and
                 int(line.split(',')[4], 16) in [18, 19] and line.split(',')[7] == '0' and
                 int(line.split(',')[8], 16) >= 2)]
        self.check(lines, "INVALID", prepared=True)

    def test_missing_final_watermark(self):
        lines = add_sequences_and_progress(baseline())
        lines = [line for line in lines if not (line.startswith("CT,1,") and int(line.split(',')[4], 16) == 22)]
        self.check(lines, "INVALID", prepared=True)

    def test_event_sequence_gap(self):
        lines = add_sequences_and_progress(baseline())
        f = lines[0].split(',');f[8] = '5';lines[0] = ','.join(f)
        self.check(lines, "INVALID", prepared=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verifier", type=Path, required=True)
    args, rest = parser.parse_known_args()
    VERIFIER = args.verifier.resolve()
    unittest.main(argv=[__file__, *rest])
