// Incremental ack-based verifier. No QEMU result is used to update actual memory.
#include "cute_trace_events.hpp"
#include <algorithm>
#include <array>
#include <bitset>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <sstream>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

using U64 = std::uint64_t;
struct Problem : std::runtime_error {
    std::string verdict;
    Problem(std::string v, const std::string &m) : runtime_error(m), verdict(std::move(v)) {}
};
[[noreturn]] static void invalid(const std::string &m) { throw Problem("INVALID", m); }
[[noreturn]] static void fail(const std::string &m) { throw Problem("FAIL", m); }

static U64 number(const std::string &s, int base = 16) {
    U64 n = 0;
    if (s.empty()) invalid("empty integer");
    auto r = std::from_chars(s.data(), s.data() + s.size(), n, base);
    if (r.ec != std::errc() || r.ptr != s.data() + s.size()) invalid("invalid integer: " + s);
    return n;
}
static std::string hex(U64 n) { std::ostringstream s; s << std::hex << n; return s.str(); }
static std::vector<std::string> split(const std::string &line, char delimiter) {
    std::vector<std::string> fields;
    std::istringstream stream(line);
    std::string word;
    while (std::getline(stream, word, delimiter)) fields.push_back(word);
    if (!line.empty() && line.back() == delimiter) fields.emplace_back();
    return fields;
}
static std::vector<std::uint8_t> binary(const std::string &path, U64 size) {
    if (!size || size > 256ULL * 1024 * 1024) invalid("invalid region length");
    std::ifstream in(path, std::ios::binary);
    if (!in) invalid("cannot open region file: " + path);
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)), {});
    if (bytes.size() != size) invalid("region file length mismatch: " + path);
    return bytes;
}
static std::vector<std::uint8_t> data_bytes(std::string s, unsigned width) {
    if (!width || width > 64 || (width & (width - 1))) invalid("unsupported trace beat width");
    if (s.empty() || s.size() > width * 2) invalid("wrong trace payload width");
    if (s.size() & 1) s.insert(s.begin(), '0');
    std::vector<std::uint8_t> result(width);
    for (unsigned i = 0; i < s.size() / 2; ++i) {
        result[i] = number(s.substr(s.size() - 2 - 2 * i, 2));
    }
    return result;
}
static std::string quoted(const std::string &s) {
    std::string result = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { result += '\\'; result += c; }
        else if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else if (c < 32) result += '?';
        else result += c;
    }
    return result + '"';
}

struct Page {
    std::array<std::uint8_t, 4096> data{};
    std::bitset<4096> known, unverified_write;
};
class Memory {
    std::unordered_map<U64, Page> pages;
public:
    void write(U64 address, std::uint8_t byte, bool acknowledged) {
        auto &p = pages[address >> 12]; unsigned offset = address & 4095;
        p.data[offset] = byte; p.unverified_write.set(offset, acknowledged); p.known.set(offset);
    }
    std::uint8_t read(U64 address) const {
        auto p = pages.find(address >> 12);
        if (p == pages.end() || !p->second.known[address & 4095]) {
            invalid("unknown actual byte at 0x" + hex(address));
        }
        return p->second.data[address & 4095];
    }
    void require_new_write(U64 address) {
        auto p = pages.find(address >> 12);
        if (p == pages.end()) invalid("output byte has no successful store ack");
        auto &page = p->second; unsigned offset = address & 4095;
        if (!page.unverified_write[offset]) {
            invalid("output byte has no new successful store ack at 0x" + hex(address));
        }
        page.unverified_write.reset(offset);
    }
};

using Key = std::tuple<U64, U64, U64, U64>; // hart, engine, port, source
using Port = std::tuple<U64, U64, U64>;
using TaskKey = std::tuple<U64, U64, U64>;  // hart, sequence, software key
struct Region { U64 address, bytes; std::string name; std::vector<std::uint8_t> golden; };
struct Task { std::vector<Region> outputs; bool complete = false; };
struct Transaction {
    U64 address, mask, cycle;
    unsigned width, lg_size;
    bool store;
    std::vector<std::uint8_t> data;
};
struct Event { U64 cycle; unsigned id; std::vector<std::string> fields; };

class Verifier {
    Memory memory;
    std::map<Key, Transaction> pending;
    std::map<TaskKey, Task> tasks;
    std::map<U64, U64> sequence;
    std::map<U64, std::pair<U64, U64>> marker_pending;
    std::set<Port> ports;
    std::map<Port, U64> event_sequence, watermark_cycle, watermark_sequence;
    std::map<U64, U64> last_control_cycle;
    std::vector<Event> frame;
    U64 cycle = 0;
    bool have_cycle = false, ended = false;
public:
    U64 lines = 0, requests = 0, responses = 0, markers = 0, compared_bytes = 0;
    U64 reads = 0, writes = 0, max_pending = 0;

    explicit Verifier(const std::string &path) {
        std::ifstream input(path); std::string line;
        if (!std::getline(input, line) || line != "CUTE_VERIFY_V1") invalid("bad verifier manifest header");
        while (std::getline(input, line)) {
            if (line.empty() || line[0] == '#') continue;
            std::istringstream row(line); std::vector<std::string> words;
            for (std::string word; row >> word;) words.push_back(word);
            if (words.empty()) continue;
            if (words[0] == "PORT" && words.size() == 4) {
                if (!ports.emplace(number(words[1]), number(words[2]), number(words[3])).second) {
                    invalid("duplicate required trace port");
                }
            } else if (words[0] == "INIT" && words.size() == 4) {
                U64 address = number(words[1]), size = number(words[2]);
                if (address + size < address) invalid("initial region address overflow");
                auto bytes = binary(words[3], size);
                for (U64 i = 0; i < size; ++i) memory.write(address + i, bytes[i], 0);
            } else if (words[0] == "OUTPUT" && words.size() == 8) {
                auto task = TaskKey(number(words[1]), number(words[2]), number(words[3]));
                U64 address = number(words[4]), size = number(words[5]);
                if (address + size < address) invalid("output address overflow");
                tasks[task].outputs.push_back({address, size, words[7], binary(words[6], size)});
            } else invalid("malformed verifier manifest record");
        }
        if (input.bad() || tasks.empty() || ports.empty()) invalid("empty/incomplete task or port manifest");
    }

    static Key key(const Event &e) {
        return {number(e.fields[0]), number(e.fields[1]), number(e.fields[2]), number(e.fields[4])};
    }
    static Port port(const Event &e) {
        return {number(e.fields[0]), number(e.fields[1]), number(e.fields[2])};
    }
    void count_event(const Event &e) {
        auto p = port(e);
        if (!ports.count(p)) invalid("event from undeclared memory port");
        if (number(e.fields[3]) != event_sequence[p]) invalid("memory event sequence gap/duplicate");
        ++event_sequence[p];
    }
    static bool overlaps(const Transaction &a, const Transaction &b) {
        U64 start = std::max(a.address, b.address);
        U64 end = std::min(a.address + a.width, b.address + b.width);
        for (U64 address = start; address < end; ++address) {
            if (((a.mask >> (address - a.address)) & 1) &&
                ((b.mask >> (address - b.address)) & 1)) return true;
        }
        return false;
    }
    void request(const Event &e) {
        count_event(e);
        const auto &f = e.fields; Key k = key(e);
        if (marker_pending.count(std::get<0>(k))) fail("memory request before checkpoint response consumed");
        if (pending.count(k)) invalid("source reused while outstanding at cycle " + hex(e.cycle));
        U64 opcode = number(f[5]), lg = number(f[7]), width = number(f[8]);
        U64 address = number(f[6]), mask = number(f[9]);
        if (opcode != 0 && opcode != 1 && opcode != 4) invalid("unsupported memory request opcode");
        if (!width || width > 64 || lg > 6) invalid("unsupported request dimensions");
        auto data = data_bytes(f[10], unsigned(width));
        // Current observed clients issue one full beat. Reject unsupported shapes.
        if (lg > 6 || (1U << lg) != width || address % width || address + width < address) {
            invalid("unsupported request size/alignment at cycle " + hex(e.cycle));
        }
        U64 full = width == 64 ? ~U64(0) : (U64(1) << width) - 1;
        if ((mask & ~full) || ((opcode == 0 || opcode == 4) && mask != full)) invalid("invalid request mask");
        Transaction tx{address, mask, e.cycle, unsigned(width), unsigned(lg), opcode != 4, std::move(data)};
        if (tx.store) {
            // S1 has no unobserved workspaces: every written byte must belong
            // to a declared output. Different tasks' disjoint outputs may coexist.
            for (unsigned i = 0; i < width; ++i) if ((mask >> i) & 1) {
                U64 byte = address + i;
                bool allowed = false;
                for (const auto &[task_key, task] : tasks) {
                    if (task.complete || std::get<0>(task_key) != std::get<0>(k)) continue;
                    for (const auto &region : task.outputs) {
                        if (byte >= region.address && byte - region.address < region.bytes) allowed = true;
                    }
                }
                if (!allowed) fail("store outside declared task outputs at 0x" + hex(byte));
            }
        }
        for (const auto &[other_key, other] : pending) {
            (void)other_key;
            if ((tx.store || other.store) && overlaps(tx, other)) {
                fail("overlapping in-flight memory transactions at address 0x" + hex(address) +
                     " cycle 0x" + hex(e.cycle));
            }
        }
        pending.emplace(k, std::move(tx));
        ++requests; if (opcode == 4) ++reads; else ++writes;
        max_pending = std::max<U64>(max_pending, pending.size());
    }
    void response(const Event &e) {
        count_event(e);
        auto k = key(e); auto it = pending.find(k);
        if (it == pending.end()) invalid("response without outstanding request at cycle " + hex(e.cycle));
        auto &tx = it->second; const auto &f = e.fields;
        if (number(f[8]) || number(f[9])) fail("denied/corrupt memory response at cycle " + hex(e.cycle));
        if (number(f[5]) != (tx.store ? 0 : 1) || number(f[6]) != tx.lg_size || number(f[7]) != tx.width) {
            invalid("response opcode/size does not match request");
        }
        auto data = data_bytes(f[10], tx.width);
        if (tx.store) {
            for (unsigned i = 0; i < tx.width; ++i) if ((tx.mask >> i) & 1) {
                memory.write(tx.address + i, tx.data[i], true);
            }
        } else {
            for (unsigned i = 0; i < tx.width; ++i) if ((tx.mask >> i) & 1) {
                auto expected = memory.read(tx.address + i);
                if (data[i] != expected) {
                    fail("read mismatch at 0x" + hex(tx.address + i) +
                         " expected=0x" + hex(expected) + " actual=0x" + hex(data[i]) +
                         " cycle=0x" + hex(e.cycle));
                }
            }
        }
        pending.erase(it); ++responses;
    }
    void mark(const Event &e) {
        U64 hart = number(e.fields[0]), seq = number(e.fields[1]), id = number(e.fields[2]);
        TaskKey k{hart, seq, id}; auto it = tasks.find(k);
        if (marker_pending.count(hart)) fail("new checkpoint before prior response consumed");
        if (seq != sequence[hart] + 1 || it == tasks.end() || it->second.complete) {
            invalid("unexpected/duplicate task checkpoint hart=" + hex(hart) + " seq=" + hex(seq));
        }
        // The S1 SDK contract drains this hart. Other harts need not be idle.
        for (const auto &[request_key, tx] : pending) {
            (void)tx;
            if (std::get<0>(request_key) == hart) fail("checkpoint before hart memory responses completed");
        }
        for (const auto &output : it->second.outputs) {
            for (U64 i = 0; i < output.bytes; ++i) {
                auto actual = memory.read(output.address + i);
                if (actual != output.golden[i]) {
                    fail("output mismatch task=" + hex(id) + " seq=" + hex(seq) +
                         " region=" + output.name + " offset=0x" + hex(i) +
                         " expected=0x" + hex(output.golden[i]) + " actual=0x" + hex(actual));
                }
                memory.require_new_write(output.address + i);
                ++compared_bytes;
            }
        }
        sequence[hart] = seq; it->second.complete = true; ++markers;
        last_control_cycle[hart] = e.cycle;
        marker_pending.emplace(hart, std::make_pair(seq, id));
        std::cout << "CHECKPOINT_PASS hart=" << hart << " seq=" << seq << " key=" << id << std::endl;
    }
    void returned(const Event &e) {
        U64 hart = number(e.fields[0]);
        auto it = marker_pending.find(hart);
        if (it == marker_pending.end() || it->second != std::make_pair(number(e.fields[1]), number(e.fields[2]))) {
            invalid("checkpoint return without matching accepted marker");
        }
        marker_pending.erase(it);
        last_control_cycle[hart] = e.cycle;
    }
    void progress(const Event &e) {
        auto p = port(e);
        if (!ports.count(p)) invalid("watermark from undeclared memory port");
        if (number(e.fields[3]) != event_sequence[p]) invalid("watermark detects missing memory events");
        U64 outstanding = 0;
        for (const auto &[k, tx] : pending) {
            (void)tx;
            if (Port(std::get<0>(k), std::get<1>(k), std::get<2>(k)) == p) ++outstanding;
        }
        if (number(e.fields[4]) != outstanding) invalid("watermark outstanding count mismatch");
        watermark_cycle[p] = e.cycle;
        watermark_sequence[p] = number(e.fields[3]);
    }
    void flush_frame() {
        // A frame is closed only when a later cycle or host RUN_END is received.
        // Requests precede responses conservatively: same-cycle unproven
        // read/write dependencies are rejected, never guessed from printf order.
        for (const auto &e : frame) if (e.id == cutetrace::SystemMemory_request) request(e);
        for (const auto &e : frame) if (e.id == cutetrace::SystemMemory_response) response(e);
        for (const auto &e : frame) if (e.id == cutetrace::SystemCheckpoint_mark) mark(e);
        for (const auto &e : frame) if (e.id == cutetrace::SystemCheckpoint_returned) returned(e);
        for (const auto &e : frame) if (e.id == cutetrace::SystemMemory_progress) progress(e);
        frame.clear();
    }
    void consume(const std::string &line) {
        ++lines;
        if (line.rfind("SV_RUN_END,", 0) == 0) {
            if (ended) invalid("duplicate run footer");
            if (line != "SV_RUN_END,0") fail("simulator did not exit successfully");
            flush_frame(); ended = true; return;
        }
        if (line.rfind("CT,", 0) != 0) return; // non-trace simulator diagnostics
        if (ended) invalid("trace after run footer");
        auto f = split(line, ',');
        if (f.size() < 5 || f[1] != "1") invalid("malformed/unsupported CT record");
        U64 c = number(f[2]), task = number(f[3]), id = number(f[4]);
        const cutetrace::Event *schema = nullptr;
        for (const auto &known : cutetrace::events) if (id == known.id) { schema = &known; break; }
        if (!schema || schema->task != task || schema->fields + 5 != f.size()) invalid("CT catalog identity/arity mismatch");
        for (std::size_t i = 5; i < f.size(); ++i) {
            if (f[i].empty() || f[i].find_first_not_of("0123456789abcdefABCDEF") != std::string::npos) {
                invalid("invalid CT hexadecimal field");
            }
        }
        if (id != cutetrace::SystemMemory_request && id != cutetrace::SystemMemory_response &&
            id != cutetrace::SystemCheckpoint_mark && id != cutetrace::SystemCheckpoint_returned &&
            id != cutetrace::SystemMemory_progress) return;
        if (have_cycle && c < cycle) invalid("system trace time regressed; check clock/reset mapping");
        if (have_cycle && c > cycle) flush_frame();
        cycle = c; have_cycle = true;
        frame.push_back({c, unsigned(id), std::vector<std::string>(f.begin() + 5, f.end())});
    }
    void finish() {
        if (!ended) invalid("missing successful host run footer (truncated/incomplete trace)");
        if (!pending.empty()) invalid("unacknowledged memory requests at end of run");
        if (!marker_pending.empty()) invalid("checkpoint response missing at end of run");
        for (const auto &p : ports) {
            auto watermark = watermark_cycle.find(p);
            if (watermark == watermark_cycle.end() ||
                watermark->second < last_control_cycle[std::get<0>(p)] ||
                watermark_sequence[p] != event_sequence[p]) {
                invalid("missing final memory-port watermark after last checkpoint return");
            }
        }
        for (const auto &[key, task] : tasks) {
            (void)key;
            if (!task.complete) invalid("missing required task checkpoint");
        }
        if (!requests || requests != responses || !writes || !reads) invalid("incomplete memory coverage");
    }
};

int main(int argc, char **argv) {
    if (argc != 3) {
        std::cerr << "usage: cute-system-verify MANIFEST REPORT.json < trace.log\n";
        return 2;
    }
    std::string verdict = "INVALID", detail;
    U64 lines = 0, req = 0, resp = 0, marks = 0, compared = 0, reads = 0, writes = 0, maximum = 0;
    try {
        Verifier verifier(argv[1]);
        auto save_counts = [&] {
            lines = verifier.lines; req = verifier.requests; resp = verifier.responses;
            marks = verifier.markers; compared = verifier.compared_bytes;
            reads = verifier.reads; writes = verifier.writes; maximum = verifier.max_pending;
        };
        try {
            std::string line;
            while (std::getline(std::cin, line)) {
                if (std::cin.eof()) invalid("truncated final log record");
                verifier.consume(line);
            }
            if (std::cin.bad()) invalid("trace input I/O error");
            verifier.finish();
        } catch (...) { save_counts(); throw; }
        save_counts(); verdict = "PASS";
    } catch (const Problem &error) { verdict = error.verdict; detail = error.what(); }
      catch (const std::exception &error) { detail = error.what(); }
    std::ofstream report(argv[2]);
    if (!report) { std::cerr << "cannot write verifier report\n"; return 2; }
    report << "{\n  \"verdict\": " << quoted(verdict) << ",\n  \"detail\": " << quoted(detail)
           << ",\n  \"lines\": " << lines << ",\n  \"requests\": " << req
           << ",\n  \"responses\": " << resp << ",\n  \"checkpoints\": " << marks
           << ",\n  \"compared_bytes\": " << compared << ",\n  \"reads\": " << reads
           << ",\n  \"writes\": " << writes << ",\n  \"max_outstanding\": " << maximum << "\n}\n";
    report.close();
    if (!report) { std::cerr << "verifier report write failed\n"; return 2; }
    std::cerr << verdict << (detail.empty() ? "" : ": " + detail) << '\n';
    return verdict == "PASS" ? 0 : verdict == "FAIL" ? 1 : 2;
}
