"""Independent NumPy references using previously calibrated task inputs.

This composes explicit numeric contracts: an approximate activation is checked
against mathematics, then integer quantization is checked exactly on its actual
input. It never takes the current output as its reference.
"""
from pathlib import Path
import numpy as np

def evaluate(expression, validated, fixtures: Path):
    arrays=[]
    for source in expression['inputs']:
        dtype=np.dtype(source['dtype']);shape=tuple(source['shape'])
        if dtype not in (np.dtype('int8'),np.dtype('<i4'),np.dtype('<f4'),np.dtype('<f2')):
            raise ValueError('unsupported stage-reference dtype')
        if not shape or any(not isinstance(n,int) or n<1 for n in shape):
            raise ValueError('invalid stage-reference shape')
        if 'task_seq' in source:
            identity=(source['hart'],source['task_seq'],source['symbol'])
            if identity not in validated:raise ValueError('reference depends on unvalidated/current/future task')
            raw=validated[identity].read_bytes()
        else:
            path=(fixtures/source['fixture']).resolve()
            if path.parent!=fixtures.resolve():raise ValueError('reference input outside fixture directory')
            raw=path.read_bytes()
        if len(raw)!=int(np.prod(shape))*dtype.itemsize:raise ValueError('reference input extent mismatch')
        arrays.append(np.frombuffer(raw,dtype=dtype).reshape(shape))
    op=expression['op']
    if op=='matmul_i8':
        a,b=arrays[:2];v=a.astype('int32')@b.astype('int32').T
        if len(arrays)==3:v=v+arrays[2]
        out=v.astype('<i4')
    elif op=='dequant':
        x,scale=arrays;out=(x.astype('float32')*(scale[:,None]*np.float32(expression['weight_scale']))).astype('<f4')
    elif op=='silu':
        x,=arrays;out=(x/(np.float32(1)+np.exp(-x))).astype('<f4')
    elif op=='multiply':
        x,y=arrays;out=(x*y).astype('<f4')
    elif op=='add':
        x,y=arrays;out=(x+y).astype('<f4')
    elif op in ('quant_scale','quant_i8'):
        x,=arrays;scale=np.abs(x).max(-1)/np.float32(127)
        if op=='quant_scale':out=scale.astype('<f4')
        else:
            inv=np.divide(np.float32(1),scale,out=np.zeros_like(scale),where=scale!=0)
            out=np.clip(np.rint(x*inv[:,None]),-128,127).astype('int8')
    else:raise ValueError('unsupported stage-reference operation: '+op)
    return out.tobytes()
