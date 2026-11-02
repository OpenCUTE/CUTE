"""MemoryMap v2: declared physical resources, real DTS exports and SDK views.

Reservations are allocation policy, not hardware access protection. MMIO/ROM
never enter the RAM buffer allocator. Fixed resources are checked, not invented.
"""
import json
from pathlib import Path
import re

from cute_config_common import ConfigError
from cute_devicetree import walk, enabled, reg, translate

PERMISSIONS = {'r': 'read', 'w': 'write', 'x': 'execute', 'c': 'cacheable', 'a': 'atomic'}
BINDINGS = {
    'external_ram': ('ram', '/memory', None),
    'boot_rom': ('rom', '/soc/rom', None),
    'uart': ('mmio', '/soc/serial', 4096),
    'clint': ('mmio', '/soc/clint', 65536),
    'plic': ('mmio', '/soc/interrupt-controller', 0x4000000),
    'prci_clock': ('mmio', '/soc/clock-gater', 4096),
    'prci_reset': ('mmio', '/soc/tile-reset-setter', 4096),
}


def extent(base, size):
    if base < 0 or size <= 0 or base + size > 1 << 64:
        raise ConfigError('invalid 64-bit address extent')
    return base, base + size


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def node_name(path):
    return re.sub(r'@[^/]+$', '', path)


def validate_layout(doc):
    if doc['version'] == 1:
        return
    ids, bindings, spans = set(), set(), []
    for region in doc['regions']:
        ident = region['id']
        if ident in ids:
            raise ConfigError('duplicate MemoryMap id: ' + ident)
        ids.add(ident)
        span = extent(int(region['base'], 0), region['size_bytes'])
        for other, name in spans:
            if overlaps(span, other):
                raise ConfigError(f'MemoryMap regions overlap: {name}, {ident}')
        spans.append((span, ident))
        if region['kind'] == 'rom' and 'write' in region['permissions']:
            raise ConfigError('ROM cannot have write permission')
        binding = region['implementation']
        if binding == 'fixed':
            continue
        kind, node, size = BINDINGS[binding]
        if binding in bindings:
            raise ConfigError('implementation binding must be unique: ' + binding)
        bindings.add(binding)
        if region['kind'] != kind or region['node'] != node or region['status'] != 'okay':
            raise ConfigError('invalid kind/node/status for implementation: ' + binding)
        if size is not None and region['size_bytes'] != size:
            raise ConfigError('hardware has a fixed window size: ' + binding)
        size = region['size_bytes']
        if span[0] % 4096 or size % 4096:
            raise ConfigError('generated windows must be page aligned')
        if binding != 'external_ram' and (size & (size-1) or span[0] % size):
            raise ConfigError('generated device requires a naturally aligned power-of-two window')
        if binding == 'boot_rom' and size > 0x7fffffff:
            raise ConfigError('BootROM size exceeds the hardware Int parameter')
    controls = {r['implementation']: r for r in doc['regions']}
    if 'clint' in controls and 'boot_rom' not in controls:
        raise ConfigError('configurable CLINT requires the MemoryMap boot_rom binding')
    if ('prci_clock' in controls) != ('prci_reset' in controls):
        raise ConfigError('PRCI clock/reset windows must be configured together')
    if 'prci_clock' in controls and int(controls['prci_reset']['base'], 0) != int(controls['prci_clock']['base'], 0) + 0x10000:
        raise ConfigError('PRCI reset window must be clock window + 0x10000')
    reserved = []
    ram = [extent(int(r['base'], 0), r['size_bytes']) for r in doc['regions']
           if r['kind'] == 'ram' and r['status'] == 'okay']
    for item in doc['reserved']:
        if item['id'] in ids:
            raise ConfigError('duplicate MemoryMap id: ' + item['id'])
        ids.add(item['id'])
        span = extent(int(item['base'], 0), item['size_bytes'])
        if span[0] % 4096 or item['size_bytes'] % 4096:
            raise ConfigError('reservations must be page aligned')
        if sum(a <= span[0] < span[1] <= b for a, b in ram) != 1:
            raise ConfigError('reservation must be contained in one enabled RAM region')
        if any(overlaps(span, other) for other in reserved):
            raise ConfigError('overlapping reservations')
        reserved.append(span)


def resource_permissions(base, size, mappings):
    """Use physical manager metadata; a DTS reg alone does not prove access."""
    matches = []
    for mapping in mappings:
        if len(mapping.get('base', [])) != 1 or len(mapping.get('size', [])) != 1:
            raise ConfigError('invalid memmap extent')
        lo, hi = extent(mapping['base'][0], mapping['size'][0])
        if overlaps((base, base+size), (lo, hi)):
            if any(type(mapping.get(k)) is not list or len(mapping[k]) != 1 or type(mapping[k][0]) is not bool for k in ('r', 'w', 'x')):
                raise ConfigError('invalid memmap permissions')
            matches.append((max(lo, base), min(hi, base+size), mapping))
    if not matches:
        return None
    cursor = base
    values = None
    for lo, hi, mapping in sorted(matches, key=lambda x: x[0]):
        if lo != cursor:
            raise ConfigError('ambiguous or incomplete physical manager coverage')
        if any(type(mapping[k]) is not list or len(mapping[k]) != 1 or type(mapping[k][0]) is not bool
               for k in PERMISSIONS if k in mapping):
            raise ConfigError('invalid manager attribute')
        flags = {k: mapping[k][0] for k in PERMISSIONS if k in mapping}
        if values is not None and flags != values:
            raise ConfigError('resource crosses managers with different permissions')
        values = flags
        cursor = hi
    if cursor != base+size:
        raise ConfigError('incomplete physical manager coverage')
    return {'allowed': [PERMISSIONS[k] for k, v in values.items() if v],
            'known': [PERMISSIONS[k] for k in values]}


def read_address_map(tree, mappings):
    records, reservations = [], []
    for path, node, parents in walk(tree, include_disabled=True):
        active = all(enabled(n) for n in [*parents, node])
        if path.startswith('/reserved-memory/'):
            if not active:
                continue
            if 'reg' not in node:
                raise ConfigError('dynamic reserved-memory requires explicit allocation')
            if 'no-map' in node and 'reusable' in node:
                raise ConfigError('reserved-memory cannot be both no-map and reusable')
            for start, size in reg(node, parents[-1]):
                mapped = translate(start, size, parents)
                if mapped is None:
                    raise ConfigError('reservation lacks parent mapping')
                for base, length in mapped:
                    extent(base, length)
                    reservations.append({'path': path, 'base': base, 'bytes': length,
                                         'no_map': 'no-map' in node, 'reusable': 'reusable' in node,
                                         'id': node.get('opencute,reservation-id', [None])[0]})
            continue
        if 'reg' not in node or not parents or node.get('device_type') == ['cpu']:
            continue
        for start, size in reg(node, parents[-1]):
            spans = translate(start, size, parents)
            if spans is None:
                continue  # Includes private local-memory domains, handled separately.
            for base, length in spans:
                extent(base, length)
                compatible = node.get('compatible', [])
                kind = ('ram' if node.get('device_type') == ['memory'] else
                        'rom' if 'sifive,rom0' in compatible or 'mtd-rom' in compatible else 'mmio')
                perms = resource_permissions(base, length, mappings)
                records.append({'path': path, 'kind': kind, 'base': base, 'bytes': length,
                                'status': 'okay' if active else 'disabled', 'compatible': compatible,
                                'permissions': None if perms is None else perms['allowed'],
                                'known_permissions': [] if perms is None else perms['known']})
    ordered = sorted(records, key=lambda r: r['base'])
    if any(a['base']+a['bytes'] > b['base'] for a, b in zip(ordered, ordered[1:])):
        raise ConfigError('overlapping global RAM/ROM/MMIO resources')
    return records, reservations


def check_layout(doc, facts):
    if doc['version'] == 1:
        return [], []
    validate_layout(doc)
    issues, matched, assigned = [], set(), []
    actual = facts['address_map']
    def issue(code, path, want, have):
        issues.append({'code': code, 'path': 'memory_map.'+path, 'required': want, 'actual': have})
    for r in doc['regions']:
        candidates = [(i, a) for i, a in enumerate(actual) if
                      (a['path'] == r['node'] or node_name(a['path']) == r['node']) and a['status'] == r['status']]
        exact = [(i, a) for i, a in candidates if a['base'] == int(r['base'], 0)]
        if exact:
            candidates = exact
        if len(candidates) != 1:
            issue('INCOMPLETE' if not candidates else 'MISMATCH', r['id'], 'one matching resource', len(candidates))
            continue
        index, a = candidates[0]
        if index in matched:
            issue('MISMATCH', r['id'], 'distinct resource', a['path'])
        matched.add(index)
        for key, want in [('kind', r['kind']), ('base', int(r['base'], 0)), ('bytes', r['size_bytes'])]:
            if a[key] != want:
                issue('MISMATCH', r['id']+'.'+key, want, a[key])
        if not set(r.get('compatible', [])) <= set(a['compatible']):
            issue('MISMATCH', r['id']+'.compatible', r['compatible'], a['compatible'])
        if a['permissions'] is None:
            issue('INCOMPLETE', r['id']+'.permissions', r['permissions'], None)
        elif set(a['known_permissions']) != set(PERMISSIONS.values()):
            issue('INCOMPLETE', r['id']+'.permissions', r['permissions'], a['known_permissions'])
        elif set(a['permissions']) != set(r['permissions']):
            issue('MISMATCH', r['id']+'.permissions', r['permissions'], a['permissions'])
        assigned.append(dict(a, id=r['id'], implementation=r['implementation']))
    if doc['coverage'] == 'complete':
        for i, a in enumerate(actual):
            if i not in matched:
                issue('MISMATCH', 'regions', 'all global resources declared', a['path'])
    expected = {(int(r['base'], 0), r['size_bytes'], r['no_map']) for r in doc['reserved']}
    observed = {(r['base'], r['bytes'], r['no_map']) for r in facts['reservation_nodes']}
    if expected != observed:
        issue('MISMATCH', 'reserved', sorted(expected), sorted(observed))
    for r in facts['reservation_nodes']:
        if r['reusable']:
            issue('MISMATCH', 'reserved', 'fixed non-reusable allocation exclusions', r)
        if r.get('id') is not None and not any(e['id'] == r['id'] and int(e['base'], 0) == r['base']
                                             and e['size_bytes'] == r['bytes'] for e in doc['reserved']):
            issue('MISMATCH', 'reserved.id', doc['reserved'], r)
    # Header reservations must also be accounted for, not silently omitted.
    if any((a, n) not in {(r[0], r[1]) for r in expected} for a, n in facts['reservations']):
        issue('MISMATCH', 'reserved', 'all reservations declared', facts['reservations'])
    return issues, assigned


def check_devices(facts, requires):
    issues = []
    for need in requires.get('devices', []):
        matches = [r for r in facts.get('configured_regions', []) if r['id'] == need['id']]
        if len(matches) != 1:
            issues.append({'code': 'INCOMPLETE', 'path': 'requires.devices.'+need['id'],
                           'actual': 'no unique configured address region'})
            continue
        r = matches[0]
        if (r['kind'] != need['kind'] or r['status'] != 'okay' or r['bytes'] < need.get('min_bytes', 1)
                or not set(need['permissions']) <= set(r['permissions'] or [])
                or not set(need.get('compatible', [])) <= set(r['compatible'])):
            issues.append({'code': 'MISMATCH', 'path': 'requires.devices.'+need['id'],
                           'required': need, 'actual': r})
    return issues


def write_sdk_map(directory, doc, facts, assigned):
    """Publish checked IDs and observed addresses for software; no MMIO allocation."""
    data = {'schema_version': 1, 'config_version': doc['version'],
            'coverage': doc.get('coverage', 'legacy-tcm'), 'regions': assigned or facts['address_map'],
            'reserved': doc.get('reserved', []),
            'private_memories': [r for r in facts['regions'] if r['kind'] == 'tcm']}
    (directory/'memory-map.json').write_text(json.dumps(data, indent=2)+'\n')
    lines = ['/* Generated from checked hardware facts. Do not edit. */',
             '#ifndef OPENCUTE_TARGET_MEMORY_H', '#define OPENCUTE_TARGET_MEMORY_H', '#include <stdint.h>']
    for r in assigned:
        prefix = 'CUTE_MEM_'+r['id'].upper()
        lines += [f'#define {prefix}_BASE UINT64_C(0x{r["base"]:x})',
                  f'#define {prefix}_BYTES UINT64_C(0x{r["bytes"]:x})',
                  f'#define {prefix}_ENABLED {int(r["status"] == "okay")}',
                  f'#define {prefix}_KIND_{r["kind"].upper()} 1']
    for r in doc.get('reserved', []):
        prefix = 'CUTE_RESERVED_'+r['id'].upper()
        lines += [f'#define {prefix}_BASE UINT64_C({r["base"]})',
                  f'#define {prefix}_BYTES UINT64_C({r["size_bytes"]})']
    lines += ['#endif', '']
    (directory/'target_memory.h').write_text('\n'.join(lines))
