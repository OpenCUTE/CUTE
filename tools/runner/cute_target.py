"""Resolve config contracts, elaborated facts and SDK resource requirements."""
import hashlib
import itertools
import json
from pathlib import Path
import re

import jsonschema
import yaml

from cute_config_common import ConfigError, chipyard_contracts, configured_tcm, load_yaml, resolve_hwconfig
from cute_devicetree import cells as _cells, integer as _number, enabled as _enabled, reg as _reg, load_tree, walk, translate
from cute_isa import parse_isa, closure, extension, compare as _isa_issues


def _legacy_isa(text):
    xlen, versions = parse_isa(text)
    return xlen, sorted(versions)


def read_facts(dts, memmap, dtc):
    tree, reserved = load_tree(dts, dtc)
    nodes = list(walk(tree))
    cpus, cpu_handles, cpu_nodes = {}, {}, {}
    for path, node, parents in nodes:
        if node.get('device_type') != ['cpu']:
            continue
        registers = _reg(node, parents[-1])
        if len(registers) != 1:
            raise ConfigError('CPU must have one hart ID')
        hart = registers[0][0]
        if hart in cpus:
            raise ConfigError('duplicate hart ID')
        if 'riscv,isa-base' in node:
            xlen, versions = parse_isa(node['riscv,isa-base'][0])
            if 'riscv,isa-extensions' not in node:
                raise ConfigError('isa-base needs isa-extensions')
            versions.update(dict(extension(e) for e in node['riscv,isa-extensions']))
            versions = closure(versions)
            if 'riscv,isa' in node:
                old_xlen, old = parse_isa(node['riscv,isa'][0])
                if old_xlen != xlen or set(old) != set(versions):
                    raise ConfigError('conflicting legacy/split ISA properties')
                if any(old[k] is not None and versions[k] is not None and old[k] != versions[k] for k in old):
                    raise ConfigError('conflicting ISA versions in legacy/split properties')
        else:
            xlen, versions = parse_isa(node['riscv,isa'][0])
        exact = _number(node, 'opencute,vlen-bits') if 'opencute,vlen-bits' in node else None
        minimum = max([int(e[3:-1]) for e in versions if re.fullmatch(r'zvl[0-9]+b', e)], default=0)
        if exact is not None and (exact < minimum or exact & (exact-1)):
            raise ConfigError('exact VLEN contradicts ISA declaration')
        cpus[hart] = {'xlen':xlen, 'extensions':sorted(versions), 'extension_versions':versions,
                      'vlen_min_bits':minimum, 'vlen_bits':exact,
                      'elen_bits':_number(node,'opencute,elen-bits') if 'opencute,elen-bits' in node else None,
                      'contracts':[], 'trace_ports':[], 'source':path}
        cpu_nodes[hart]=node
        if 'phandle' in node:
            handle=_number(node,'phandle')
            if handle in cpu_handles:raise ConfigError('duplicate CPU phandle')
            cpu_handles[handle]=hart
    if not cpus:raise ConfigError('no enabled CPUs')
    mappings=json.loads(memmap.read_text()).get('mapping',[]) if memmap else []
    regions, devices, client_exports=[],[],[]
    for path,node,parents in nodes:
        if path.startswith('/reserved-memory/'):
            if 'reg' not in node:
                raise ConfigError('dynamic reserved-memory requires an explicit allocation before SDK build')
            spans=[]
            for start,size in _reg(node,parents[-1]):
                mapped=translate(start,size,parents)
                if mapped is None:raise ConfigError('reserved memory lacks parent mapping')
                spans.extend(mapped)
            reserved.extend(spans)
            continue
        compatible=node.get('compatible',[])
        if 'reg' in node and node.get('device_type') != ['cpu'] and parents:
            for start,size in _reg(node,parents[-1]):
                translated=translate(start,size,parents)
                if translated is None:continue
                for base,length in translated:
                    if length <= 0 or base+length > 1 << 64:raise ConfigError('invalid physical extent')
                    if node.get('device_type') == ['memory']:
                        records=[m for m in mappings if m.get('base')==[base] and m.get('size')==[length]]
                        if len(records)>1:raise ConfigError('ambiguous memory permissions')
                        if records and any(type(records[0].get(k)) is not list or len(records[0][k])!=1
                                           or type(records[0][k][0]) is not bool for k in ('r','w','x')):
                            raise ConfigError('invalid memmap permissions')
                        permissions=None if not records else [v for k,v in [('r','read'),('w','write'),('x','execute')]
                                                              if records[0][k]==[True]]
                        regions.append({'id':'shared.'+path+':'+hex(base),'kind':'ram','owner_hart':None,
                                        'bytes':length,'physical_base':base,'reserved':[],
                                        'views':[{'hart':h,'client':'scalar-data','base':base,'bytes':length,
                                                  'offset':0,'permissions':permissions} for h in cpus]})
                    else:
                        devices.append({'path':path,'compatible':compatible,'base':base,'bytes':length})
        if compatible in (['opencute,cute-contract-v1'],['opencute,saturn-contract-v1']):
            hart=_number(node,'opencute,hart-id')
            if hart not in cpus:raise ConfigError('contract owner does not exist')
            cpu=cpus[hart]
            cpu['contracts']=sorted(set(cpu['contracts']+node.get('opencute,contracts',[])))
            if 'opencute,encoding' in node:cpu['cute_encoding']=node['opencute,encoding'][0]
            ports=_cells(node['opencute,trace-ports'])
            if len(ports)%2:raise ConfigError('invalid trace port pairs')
            cpu['trace_ports'] += [[hart,ports[i],ports[i+1]] for i in range(0,len(ports),2)]
            beat=_number(node,'opencute,beat-bytes');period=_number(node,'opencute,progress-period')
            if cpu.get('beat_bytes',beat)!=beat or cpu.get('progress_period',period)!=period:
                raise ConfigError('incompatible trace interfaces')
            cpu.update(beat_bytes=beat,progress_period=period)
            if 'opencute,access-ranges' in node:
                values=_cells(node['opencute,access-ranges'])
                if len(values)%5:raise ConfigError('invalid client range tuples')
                for i in range(0,len(values),5):
                    base=(values[i]<<32)|values[i+1];length=(values[i+2]<<32)|values[i+3];flags=values[i+4]
                    client_exports.append({'hart':hart,'client':node['opencute,client'][0], 'base':base,'bytes':length,
                                           'permissions':[s for bit,s in [(1,'read'),(2,'write'),(4,'execute'),(8,'cacheable'),(16,'atomic')] if flags&bit]})
        if compatible != ['opencute,shuttle-local-memory-v1']:continue
        if any(k in node for k in ('reg','ranges','device_type')) or node.get('opencute,scope')!=['tile-private']:
            raise ConfigError('private TCM has global address semantics')
        owner=cpu_handles.get(_number(node,'opencute,owner'))
        if owner is None:raise ConfigError('unknown local memory owner')
        handle=_number(node,'phandle')
        if handle not in _cells(cpu_nodes[owner].get('opencute,local-memories',b'')):
            raise ConfigError('CPU does not reference local memory')
        region={'id':node['opencute,region-id'][0],'kind':'tcm','owner_hart':owner,
                'tile_id':_number(node,'opencute,tile-id'),'bytes':_number(node,'opencute,size-bytes',2),
                'internal_base':_number(node,'opencute,internal-base',2),'banks':_number(node,'opencute,banks'),
                'reserved':[],'views':[]}
        if region['bytes']<=0:raise ConfigError('empty private TCM')
        for view in node.values():
            if not isinstance(view,dict) or view.get('compatible')!=['opencute,local-memory-view-v1'] or not _enabled(view):continue
            if 'ranges' in view or view.get('opencute,address-view')!=['tilelink-advertised']:raise ConfigError('invalid local view')
            for window in view.values():
                if not isinstance(window,dict):continue
                if window.get('compatible')!=['opencute,local-memory-window-v1'] or _number(window,'opencute,region')!=handle:
                    raise ConfigError('invalid local window reference')
                offset=_number(window,'opencute,region-offset',2)
                for start,size in _reg(window,view):
                    if size<=0 or offset+size>region['bytes']:raise ConfigError('window exceeds RAM capacity')
                    if any(max(start,b)<min(start+size,b+s) for m in mappings for b,s in zip(m['base'],m['size'])):
                        raise ConfigError('private range leaked into global map')
                    region['views'].append({'hart':owner,'client':view['opencute,client'][0],'base':start,
                                            'bytes':size,'offset':offset,'permissions':window.get('opencute,permissions',[])})
        regions.append(region)
    if len({r['id'] for r in regions})!=len(regions):raise ConfigError('duplicate memory region ID')
    physical=sorted((r['physical_base'],r['bytes']) for r in regions if r['kind']=='ram')
    if any(a+n>b for (a,n),(b,_) in zip(physical,physical[1:])):raise ConfigError('overlapping shared RAM')
    for region in regions:
        if region['kind']=='ram':
            base=region['physical_base']
            for start,size in reserved:
                lo=max(start,base);hi=min(start+size,base+region['bytes'])
                if lo<hi:region['reserved'].append([lo-base,hi-base])
        for export in client_exports:
            if region['owner_hart'] not in (None,export['hart']):continue
            views=region['views'][:] if region['kind']=='tcm' else [{'base':region['physical_base'],'bytes':region['bytes'],'offset':0}]
            for view in views:
                lo=max(export['base'],view['base']);hi=min(export['base']+export['bytes'],view['base']+view['bytes'])
                if lo<hi:
                    new=dict(export,base=lo,bytes=hi-lo,offset=view['offset']+lo-view['base'])
                    if new not in region['views']:region['views'].append(new)
    disabled=['/'+name for name,node in tree.items() if isinstance(node,dict)
              and node.get('device_type')==['memory'] and not _enabled(node)]
    from cute_memory_map import read_address_map
    address_map, reservation_nodes = read_address_map(tree, mappings)
    return {'cpus':cpus,'regions':regions,'devices':devices,'reservations':reserved,'disabled_memory_nodes':disabled,
            'address_map':address_map, 'reservation_nodes':reservation_nodes}


def _allocate(facts, requirement):
    """Bounded deterministic search over canonical RAM offsets, never aliases."""
    needs = requirement.get('memory', [])
    hart = requirement['hart']
    options, issues = [], []
    for need in needs:
        align = need['alignment']
        if align & (align-1):
            raise ConfigError('buffer alignment must be a power of two')
        choices, unknown = [], False
        candidates = [r for r in facts['regions'] if r['kind']==need['kind']
                      and (r['owner_hart'] is None if need['owner']=='shared' else r['owner_hart']==hart)]
        for region in candidates:
            if region['bytes'] < need['min_bytes']:
                continue
            lists = []
            for client in need['clients']:
                seen = [v for v in region['views'] if v['hart']==hart and v['client']==client]
                if not seen or any(v['permissions'] is None for v in seen):
                    unknown = True
                valid = [v for v in seen if v['permissions'] is not None and set(need['permissions'])<=set(v['permissions'])]
                # Multiple aliases of one canonical interval are alternatives.
                unique = {}
                for view in sorted(valid,key=lambda v:v['base']):
                    unique.setdefault((view['offset'],view['bytes']),view)
                lists.append(list(unique.values()))
            for views in itertools.product(*lists):
                start=max(v['offset'] for v in views);end=min(v['offset']+v['bytes'] for v in views)
                bias=views[0]['base']-views[0]['offset']
                if any((v['base']-v['offset']-bias)%align for v in views):
                    continue
                offset=((start+bias+align-1)//align)*align-bias
                if offset+need['min_bytes']<=end:
                    choices.append((region['id'],start,end,bias,views))
        if not choices:
            issues.append({'code':'INCOMPLETE' if unknown or not candidates else 'MISMATCH',
                           'path':'memory/'+need['id'],'required':need,
                           'actual':'no compatible exported region/client interval'})
        options.append(choices)
    if issues:
        return [],issues
    order=sorted(range(len(needs)),key=lambda i:(len(options[i]),-needs[i]['alignment'],-needs[i]['min_bytes']))
    occupied = {r['id']: [tuple(v) for v in r.get('reserved',[])] for r in facts['regions']}
    chosen, attempts = {}, [0]
    def search(depth):
        if depth==len(order):return True
        index=order[depth];need=needs[index];size=need['min_bytes'];align=need['alignment']
        for rid,start,end,bias,views in options[index]:
            used=sorted(occupied.get(rid,[]));gaps=[];cursor=start
            for low,high in used:
                if high<=start or low>=end:continue
                if cursor<low:gaps.append((cursor,min(low,end)))
                cursor=max(cursor,high)
            if cursor<end:gaps.append((cursor,end))
            for low,high in gaps:
                offset=((low+bias+align-1)//align)*align-bias
                if offset+size>high:continue
                attempts[0]+=1
                if attempts[0]>10000:return False
                occupied.setdefault(rid,[]).append((offset,offset+size))
                chosen[index]={'request':need['id'],'region_id':rid,'offset':offset,'bytes':size,
                               'addresses':{v['client']:v['base']+offset-v['offset'] for v in views}}
                if search(depth+1):return True
                occupied[rid].remove((offset,offset+size));chosen.pop(index)
        return False
    if not search(0):
        return [],[{'code':'INCOMPLETE','path':'memory','actual':'bounded allocation search found no simultaneous placement'}]
    return [chosen[i] for i in range(len(needs))],[]


def check_target(root, hwconfig, dts, memmap=None, requires=None, dtc='dtc'):
    try:
        resolved=resolve_hwconfig(root,Path.cwd(),hwconfig)
        contracts,paths=chipyard_contracts(root,resolved.chipyard)
        facts=read_facts(dts,memmap,dtc)
        issues=[]
        memory_map = contracts.get('memory_map')
        if memory_map:
            from cute_memory_map import check_layout
            layout_issues, assigned = check_layout(memory_map, facts)
            issues.extend(layout_issues)
            facts['configured_regions'] = assigned
        if len(facts['cpus'])!=resolved.chipyard['soc']['core']['count']:
            issues.append({'code':'MISMATCH','path':'soc.core.count','actual':len(facts['cpus'])})
        if 'isa_profile' not in contracts:
            issues.append({'code':'INCOMPLETE','path':'isa_profile','actual':'no explicit ISA profile'})
        else:
            profile = dict(contracts['isa_profile'], custom_contracts=[])
            for hart,cpu in facts['cpus'].items():
                issues.extend(_isa_issues(cpu,profile,'hart/'+str(hart)))
            exported = {c for cpu in facts['cpus'].values() for c in cpu.get('contracts',[])}
            missing = set(contracts['isa_profile'].get('custom_contracts',[])) - exported
            if missing:
                issues.append({'code':'INCOMPLETE','path':'isa_profile.custom_contracts','required':sorted(missing),'actual':sorted(exported)})
        configured=configured_tcm(root,resolved.chipyard)
        observed=[r for r in facts['regions'] if r['kind']=='tcm']
        if configured is None and observed:
            issues.append({'code':'MISMATCH','path':'memory_map.tcm','actual':'DTS exports TCM although config disables it'})
        if configured is not None:
            expected_owners = set(configured.get('owner_tiles', facts['cpus']))
            if {r['owner_hart'] for r in observed}!=expected_owners or len(observed)!=len(expected_owners):
                issues.append({'code':'INCOMPLETE' if not observed else 'MISMATCH','path':'memory_map.tcm.owners','actual':[r['owner_hart'] for r in observed]})
            for region in observed:
                for key,want in [('bytes',configured['size']),('banks',configured['banks']),('internal_base',int(configured['address'],0))]:
                    if region[key]!=want:
                        issues.append({'code':'MISMATCH','path':region['id']+'/'+key,'required':want,'actual':region[key]})
        bindings=[]
        if requires:
            from cute_requirements import resolve_requirements
            req=resolve_requirements(requires, root)
            hart=req['hart']
            if hart not in facts['cpus']:
                issues.append({'code':'MISMATCH','path':'requires.hart','actual':hart})
            else:
                issues.extend(_isa_issues(facts['cpus'][hart],req['isa'],'requires.isa'))
                bindings,allocation_issues=_allocate(facts,req);issues.extend(allocation_issues)
                from cute_memory_map import check_devices
                issues.extend(check_devices(facts, req))
        refs=[resolved.hwconfig_path,resolved.chipyard_path,*paths,dts]
        if memmap:refs.append(memmap)
        if requires:refs.extend(Path(item['path']) for item in req['sources'])
        sources=[{'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in refs]
        verdict='MISMATCH' if any(i['code']=='MISMATCH' for i in issues) else 'INCOMPLETE' if issues else 'MATCH'
        return {'verdict':verdict,'hwconfig':resolved.hwconfig_id,'issues':issues,'bindings':bindings,'facts':facts,
                'sources':sources,'scope':'Selected config/export and declared-resource checks only; not build provenance, QEMU coverage, ELF allocation or execution acceptance',
                'unchecked':['bus/cache performance','runtime behavior (requires execution tests)','QEMU and ELF checks are performed by the build/run pipeline']}
    except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError,jsonschema.ValidationError) as exc:
        raise ConfigError(str(exc)) from exc
