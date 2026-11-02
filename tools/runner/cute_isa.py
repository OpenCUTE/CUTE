"""RISC-V extension names, explicit version bounds and standard implications.

Unversioned hardware facts never prove a versioned requirement. Unrecognized
extensions still match by explicit identity; no fabricated version defaults.
"""
import re
from cute_config_common import ConfigError

# Dependencies relevant to the supported base/FP/vector targets. This is not an
# implementation claim; transitive extension semantics come from the ISA spec.
IMPLIES = {
    'g':['i','m','a','f','d','zicsr','zifencei'], 'd':['f'], 'f':['zicsr'],
    'm':['zmmul'], 'a':['zaamo','zalrsc'], 'c':['zca'],
    'b':['zba','zbb','zbs'], 'v':['zve64d','zvl128b'],
    'zve64d':['zve64f','d'], 'zve64f':['zve64x','zve32f','f'],
    'zve32f':['zve32x','f'], 'zve64x':['zve32x','zvl64b'],
    'zve32x':['zicsr','zvl32b'],
    'zvfh':['zvfhmin','zfhmin'], 'zvfhmin':['zve32f'], 'zfh':['zfhmin'], 'zfhmin':['f'],
}


def version(value):
    if isinstance(value,(list,tuple)) and len(value)==2:return tuple(value)
    m=re.fullmatch(r'(\d+)(?:[p.](\d+))?',str(value))
    if not m:raise ConfigError('invalid ISA version: '+str(value))
    return int(m[1]),int(m[2] or 0)


def extension(token):
    # Numeric extension names such as zvl512b/zve64d remain intact.
    m=re.fullmatch(r'([a-z][a-z0-9]*?)(\d+)p(\d+)',token)
    if m:return m[1],(int(m[2]),int(m[3]))
    if not re.fullmatch(r'[a-z][a-z0-9]*',token):raise ConfigError('invalid ISA extension: '+token)
    return token,None


def parse_isa(text):
    m=re.fullmatch(r'rv(32|64)([a-z0-9_]+)',text)
    if not m:raise ConfigError('invalid ISA string: '+text)
    rest=m[2];versions={}
    while rest and rest[0] not in 'zsx_':
        item=re.match(r'([a-z])(?:(\d+)(?:p(\d+))?)?',rest)
        if not item:raise ConfigError('invalid single-letter extension')
        name=item[1];v=(int(item[2]),int(item[3] or 0)) if item[2] else None
        if name in versions:raise ConfigError('duplicate ISA extension')
        versions[name]=v;rest=rest[len(item[0]):]
    for token in rest.lstrip('_').split('_'):
        if not token:continue
        name,v=extension(token)
        if name in versions:raise ConfigError('duplicate ISA extension')
        versions[name]=v
    if not set(versions)&{'i','e','g'}:raise ConfigError('ISA lacks base extension')
    return int(m[1]),closure(versions)


def closure(versions):
    result=dict(versions);pending=list(result)
    while pending:
        name=pending.pop()
        implied=list(IMPLIES.get(name,[]))
        if re.fullmatch(r'zvl\d+b',name):
            bits=int(name[3:-1])
            implied += [f'zvl{n}b' for n in [32,64,128,256,512,1024,2048,4096,8192,16384,32768,65536] if n<bits]
        for dep in implied:
            if dep not in result:result[dep]=None;pending.append(dep)
    if 'c' in result and 'd' in result:result.setdefault('zcd',None)
    return result


def compare(cpu,required,path):
    issues=[]
    def add(code,key,want,got):issues.append({'code':code,'path':path+'/'+key,'required':want,'actual':got})
    if cpu['xlen']!=required['xlen']:add('MISMATCH','xlen',required['xlen'],cpu['xlen'])
    got=closure(cpu.get('extension_versions',{e:None for e in cpu['extensions']}))
    for token in required.get('extensions',[]):
        name,v=extension(token)
        if name not in got:add('MISMATCH','extensions',name,sorted(got));continue
        if v is not None:
            if got[name] is None:add('INCOMPLETE','versions/'+name,v,None)
            elif tuple(got[name])<v:add('MISMATCH','versions/'+name,v,got[name])
    for name,bounds in required.get('versions',{}).items():
        if name not in got:add('MISMATCH','versions/'+name,bounds,None)
        elif got[name] is None:add('INCOMPLETE','versions/'+name,bounds,None)
        elif ('min' in bounds and tuple(got[name])<version(bounds['min'])) or ('max' in bounds and tuple(got[name])>version(bounds['max'])):
            add('MISMATCH','versions/'+name,bounds,got[name])
    exact=cpu.get('vlen_bits');lower=cpu.get('vlen_min_bits',0)
    if required.get('vlen_min_bits',0)>(exact or lower):
        add('MISMATCH' if exact is not None else 'INCOMPLETE','vlen_min_bits',required['vlen_min_bits'],exact or {'lower_bound':lower})
    if 'vlen_bits' in required:
        wanted=required['vlen_bits']
        if exact is None:add('MISMATCH' if lower>wanted else 'INCOMPLETE','vlen_bits',wanted,{'lower_bound':lower})
        elif exact!=wanted:add('MISMATCH','vlen_bits',wanted,exact)
    for contract in required.get('custom_contracts',[]):
        if contract not in cpu.get('contracts',[]):add('INCOMPLETE','custom_contracts',contract,cpu.get('contracts',[]))
    return issues
