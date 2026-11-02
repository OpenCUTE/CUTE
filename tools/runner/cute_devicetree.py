"""DTB parsing and bus address translation for generated platform facts.

dtc handles DTS syntax/includes. This reader handles binary structure, reservation
entries and address cells rather than extracting addresses with text patterns.
"""
from pathlib import Path
import struct
import subprocess

from cute_config_common import ConfigError

STRINGS = {
    'compatible', 'model', 'status', 'device_type', 'riscv,isa', 'riscv,isa-base',
    'riscv,isa-extensions', 'reg-names', 'opencute,region-id', 'opencute,kind',
    'opencute,scope', 'opencute,address-view', 'opencute,client',
    'opencute,permissions', 'opencute,contracts', 'opencute,encoding', 'opencute,reservation-id',
}


def cells(value):
    if isinstance(value, bytes):
        if len(value) % 4:
            raise ConfigError('DT property is not a cell array')
        return list(struct.unpack('>'+'I'*(len(value)//4), value))
    if isinstance(value, list) and all(isinstance(v, list) for v in value):
        result = [x for group in value for x in group]
        if all(type(v) is int and 0 <= v < 2**32 for v in result):
            return result
    raise ConfigError('invalid DT cells')


def integer(node, key, width=1, default=None):
    if key not in node:
        if default is not None:
            return default
        raise ConfigError('missing DT property: '+key)
    values = cells(node[key])
    if len(values) != width:
        raise ConfigError('wrong cell count: '+key)
    return join(values)


def join(values):
    result = 0
    for value in values:
        result = (result << 32) | value
    return result


def enabled(node):
    return node.get('status', ['okay']) in (['okay'], ['ok'])


def reg(node, parent):
    ac = integer(parent, '#address-cells', default=2)
    sc = integer(parent, '#size-cells', default=1)
    if not 0 < ac <= 4 or not 0 <= sc <= 4:
        raise ConfigError('unsupported address cell width')
    values = cells(node['reg'])
    stride = ac+sc
    if not values or len(values) % stride:
        raise ConfigError('invalid reg tuple extent')
    return [(join(values[i:i+ac]), join(values[i+ac:i+stride]))
            for i in range(0, len(values), stride)]


def parse_dtb(data):
    if len(data) < 40:
        raise ConfigError('truncated DTB header')
    magic,total,off_struct,off_strings,off_reserve,version,last,boot,size_strings,size_struct = struct.unpack_from('>10I',data)
    if magic != 0xd00dfeed or total > len(data) or version < 17 or last > 17:
        raise ConfigError('unsupported DTB header')
    if any(offset < 40 or offset+size > total for offset,size in [(off_struct,size_struct),(off_strings,size_strings)]):
        raise ConfigError('DTB section outside file')
    strings = data[off_strings:off_strings+size_strings]
    reservations=[]; cursor=off_reserve
    while True:
        if cursor < 40 or cursor+16 > total:
            raise ConfigError('truncated DT reservation table')
        start,length=struct.unpack_from('>QQ',data,cursor);cursor+=16
        if not start and not length:break
        if length and start+length > 1 << 64:raise ConfigError('reservation overflow')
        reservations.append((start,length))
    cursor=off_struct;end=off_struct+size_struct;stack=[];root=None
    while cursor+4 <= end:
        token=struct.unpack_from('>I',data,cursor)[0];cursor+=4
        if token==1:
            terminator=data.find(b'\0',cursor,end)
            if terminator<0:raise ConfigError('unterminated DT node')
            name=data[cursor:terminator].decode();cursor=(terminator+4)&~3
            node={}
            if stack:
                if name in stack[-1]:raise ConfigError('duplicate DT node')
                stack[-1][name]=node
            else:
                if root is not None or name:raise ConfigError('invalid DT root')
                root=node
            stack.append(node)
        elif token==2:
            if not stack:raise ConfigError('unbalanced DT node')
            stack.pop()
        elif token==3:
            if not stack or cursor+8>end:raise ConfigError('invalid DT property')
            length,nameoff=struct.unpack_from('>II',data,cursor);cursor+=8
            terminal=strings.find(b'\0',nameoff)
            if terminal<0 or nameoff>=len(strings) or cursor+length>end:raise ConfigError('invalid DT property extent')
            name=strings[nameoff:terminal].decode();value=data[cursor:cursor+length];cursor=(cursor+length+3)&~3
            if name in stack[-1]:raise ConfigError('duplicate DT property')
            if name in STRINGS:
                if not value.endswith(b'\0'):raise ConfigError('unterminated DT string')
                value=[s.decode() for s in value[:-1].split(b'\0')]
            stack[-1][name]=value
        elif token==4:
            continue
        elif token==9:
            if stack or root is None:raise ConfigError('unbalanced DT end')
            return root,reservations
        else:
            raise ConfigError('unknown DT token')
    raise ConfigError('missing DT end token')


def load_tree(path, dtc):
    raw=Path(path).read_bytes()
    if raw[:4] != b'\xd0\x0d\xfe\xed':
        try:
            run=subprocess.run([dtc,'-I','dts','-O','dtb',str(path)],capture_output=True,check=True,timeout=30)
        except (OSError,subprocess.SubprocessError) as exc:
            raise ConfigError('dtc failed: '+str(exc)) from exc
        raw=run.stdout
    return parse_dtb(raw)


def walk(tree, include_disabled=False):
    def descend(node,path,ancestors):
        if not include_disabled and not enabled(node):return
        yield path,node,ancestors
        for name,child in node.items():
            if isinstance(child,dict):
                yield from descend(child,path.rstrip('/')+'/'+name,ancestors+[node])
    yield from descend(tree,'/',[])


def translate(start,size,ancestors,property_name='ranges'):
    """Translate child bus ranges to root physical space; split at range edges.

    Missing ranges is deliberately not an identity mapping. dma-ranges can be
    decoded by callers with the same routine, without inferring client reachability.
    """
    spans=[(start,size)]
    for level in range(len(ancestors)-1,0,-1):
        bus,parent=ancestors[level],ancestors[level-1]
        if property_name not in bus:return None
        values=cells(bus[property_name])
        if not values:continue
        ac=integer(bus,'#address-cells',default=2);pc=integer(parent,'#address-cells',default=2);sc=integer(bus,'#size-cells',default=1)
        stride=ac+pc+sc
        if not stride or len(values)%stride:raise ConfigError('invalid bus ranges')
        mappings=[(join(values[i:i+ac]),join(values[i+ac:i+ac+pc]),join(values[i+ac+pc:i+stride]))
                  for i in range(0,len(values),stride)]
        ordered=sorted(mappings)
        if any(a+n>b for (a,_,n),(b,_,_) in zip(ordered,ordered[1:])):raise ConfigError('ambiguous bus ranges')
        result=[]
        for base,length in spans:
            consumed=0
            for child,physical,extent in ordered:
                lo=max(base,child);hi=min(base+length,child+extent)
                if lo<hi:result.append((physical+lo-child,hi-lo));consumed+=hi-lo
            if consumed!=length:raise ConfigError('reg is not fully translated by ranges')
        spans=result
    return spans
