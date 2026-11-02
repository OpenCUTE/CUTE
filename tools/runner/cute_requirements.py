"""Resolve explicit software dependency requirements and reject contradictions."""
import copy
import hashlib
import json
from pathlib import Path

import jsonschema
from cute_config_common import ConfigError, load_yaml
from cute_isa import version, extension, closure


def resolve_requirements(path, root):
    schema=json.loads((root/'configs/schemas/sdk_requires.schema.json').read_text())
    visited,active,documents,sources=set(),set(),[],[]
    def visit(filename):
        filename=filename.resolve()
        if filename in active:raise ConfigError('cyclic requires dependency: '+str(filename))
        if filename in visited:return
        doc=load_yaml(filename)
        try:jsonschema.Draft7Validator(schema).validate(doc)
        except jsonschema.ValidationError as exc:raise ConfigError(str(filename)+': '+exc.message) from exc
        if len({m['id'] for m in doc.get('memory',[])})!=len(doc.get('memory',[])):
            raise ConfigError('duplicate buffer in '+str(filename))
        active.add(filename)
        for dependency in doc.get('depends_on',[]):visit(filename.parent/dependency)
        active.remove(filename);visited.add(filename);documents.append((filename,doc))
        sources.append({'path':str(filename),'sha256':hashlib.sha256(filename.read_bytes()).hexdigest()})
    path=path.resolve();visit(path)
    result={'version':1,'id':documents[-1][1]['id'],'hart':0,'isa':{'extensions':[]},'memory':[]}
    names=set();exact={};extensions=set();contracts=set();versions={};memory_ids=set();devices={}
    for filename,doc in documents:
        if doc['id'] in names:raise ConfigError('duplicate requires identity across files: '+doc['id'])
        names.add(doc['id'])
        for key in ['hart']:
            if key in doc:
                if key in exact and exact[key]!=doc[key]:raise ConfigError('conflicting '+key+' requirements')
                exact[key]=doc[key];result[key]=doc[key]
        isa=doc.get('isa',{})
        for key in ['xlen','vlen_bits']:
            if key in isa:
                if key in exact and exact[key]!=isa[key]:raise ConfigError('conflicting '+key+' requirements')
                exact[key]=isa[key];result['isa'][key]=isa[key]
        extensions.update(isa.get('extensions',[]));contracts.update(isa.get('custom_contracts',[]))
        result['isa']['vlen_min_bits']=max(result['isa'].get('vlen_min_bits',0),isa.get('vlen_min_bits',0))
        for ext_name,bounds in isa.get('versions',{}).items():
            merged=versions.setdefault(ext_name,{})
            for key in ('min','max'):
                if key in bounds:
                    value=version(bounds[key])
                    if key not in merged or (value>merged[key] if key=='min' else value<merged[key]):merged[key]=value
            if 'min' in merged and 'max' in merged and merged['min']>merged['max']:
                raise ConfigError('empty ISA version intersection: '+ext_name)
        for memory in doc.get('memory',[]):
            memory=copy.deepcopy(memory)
            if filename!=path:memory['id']=doc['id']+'.'+memory['id']
            if memory['id'] in memory_ids:raise ConfigError('ambiguous buffer requirement identity')
            memory_ids.add(memory['id']);result['memory'].append(memory)
        if len({d['id'] for d in doc.get('devices',[])}) != len(doc.get('devices',[])):
            raise ConfigError('duplicate device requirement in '+str(filename))
        for device in doc.get('devices',[]):
            merged=devices.setdefault(device['id'],dict(device,permissions=[],compatible=[],min_bytes=1))
            if merged['kind'] != device['kind']:
                raise ConfigError('conflicting device kind: '+device['id'])
            merged['permissions']=sorted(set(merged['permissions'])|set(device['permissions']))
            merged['compatible']=sorted(set(merged['compatible'])|set(device.get('compatible',[])))
            merged['min_bytes']=max(merged['min_bytes'],device.get('min_bytes',1))
    if 'xlen' not in result['isa']:raise ConfigError('resolved requires must specify xlen')
    if exact.get('vlen_bits',1<<64)<result['isa'].get('vlen_min_bits',0):raise ConfigError('incompatible vector length bounds')
    normalized=set()
    for token in extensions:
        name,bound=extension(token);normalized.add(name)
        if bound is not None:
            interval=versions.setdefault(name,{})
            interval['min']=max(interval.get('min',bound),bound)
            if 'max' in interval and interval['min']>interval['max']:
                raise ConfigError('empty ISA version intersection: '+name)
    result['isa']['extensions']=sorted(normalized);result['isa']['custom_contracts']=sorted(contracts)
    result['isa']['effective_extensions']=sorted(closure({name:None for name in normalized}))
    result['isa']['versions']={e:{k:f'{v[0]}.{v[1]}' for k,v in b.items()} for e,b in versions.items()}
    result['sources']=sources
    if devices:result['devices']=[devices[k] for k in sorted(devices)]
    return result
