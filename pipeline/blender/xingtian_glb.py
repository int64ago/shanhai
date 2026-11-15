"""Small GLB helpers for Xingtian's source-preserving skin/prop append pipeline."""
import copy
import json
from pathlib import Path
import struct

import numpy as np

WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
DTYPE = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
# glTF +Y up / +Z forward -> Blender +Z up / -Y forward.
C = np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]])


def load(path):
    data = Path(path).read_bytes()
    magic, version, size = struct.unpack_from('<III', data)
    assert magic == 0x46546C67 and version == 2 and size == len(data)
    offset, document, binary = 12, None, None
    while offset < len(data):
        length, kind = struct.unpack_from('<II', data, offset)
        chunk = data[offset+8:offset+8+length]
        if kind == 0x4E4F534A:
            document = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = bytearray(chunk)
        offset += 8+length
    assert document is not None and binary is not None
    return document, binary


def save(path, document, binary):
    document['buffers'] = [{'byteLength': len(binary)}]
    text = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()
    text += b' '*(-len(text) % 4)
    binary = bytes(binary)+b'\0'*(-len(binary) % 4)
    data = struct.pack('<III', 0x46546C67, 2, 28+len(text)+len(binary))
    data += struct.pack('<II', len(text), 0x4E4F534A)+text
    data += struct.pack('<II', len(binary), 0x004E4942)+binary
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def array(document, binary, index):
    a = document['accessors'][index]
    assert 'sparse' not in a
    view = document['bufferViews'][a['bufferView']]
    dtype = np.dtype(DTYPE[a['componentType']]); width = WIDTH[a['type']]
    return np.ndarray((a['count'], width), dtype=dtype, buffer=binary,
                      offset=view.get('byteOffset', 0)+a.get('byteOffset', 0),
                      strides=(view.get('byteStride', dtype.itemsize*width), dtype.itemsize)).copy()


def append(document, binary, values, kind, component=5126):
    values = np.ascontiguousarray(values, dtype=DTYPE[component])
    binary.extend(b'\0'*(-len(binary) % 4))
    view = len(document.setdefault('bufferViews', []))
    document['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': values.nbytes})
    binary.extend(values.tobytes())
    a = {'bufferView': view, 'componentType': component, 'type': kind, 'count': len(values)}
    if kind in {'SCALAR', 'VEC3'}:
        a.update(min=values.min(0).tolist(), max=values.max(0).tolist())
    document.setdefault('accessors', []).append(a)
    return len(document['accessors'])-1


def matrix(node):
    if 'matrix' in node:
        return np.array(node['matrix'], float).reshape(4, 4).T
    from mathutils import Quaternion
    result = np.eye(4)
    q = node.get('rotation', [0, 0, 0, 1])
    result[:3, :3] = np.array(Quaternion((q[3], *q[:3])).to_matrix())@np.diag(node.get('scale', [1, 1, 1]))
    result[:3, 3] = node.get('translation', [0, 0, 0])
    return result


def world_matrices(document):
    result = {}
    def visit(i, parent):
        result[i] = parent@matrix(document['nodes'][i])
        for child in document['nodes'][i].get('children', []):
            visit(child, result[i])
    for i in document['scenes'][document.get('scene', 0)]['nodes']:
        visit(i, np.eye(4))
    return result


def merge_static(document, binary, other, other_binary):
    """Append a local static prop GLB; original bytes and indices stay fixed."""
    assert not other.get('skins') and not other.get('animations')
    keys = ['bufferViews', 'accessors', 'images', 'samplers', 'textures', 'materials', 'meshes', 'nodes']
    offsets = {k: len(document.get(k, [])) for k in keys}
    binary.extend(b'\0'*(-len(binary) % 4)); base = len(binary); binary.extend(other_binary)
    for key in keys:
        for original in other.get(key, []):
            value = copy.deepcopy(original)
            if key == 'bufferViews':
                value['buffer'] = 0; value['byteOffset'] = value.get('byteOffset', 0)+base
            elif key == 'accessors':
                value['bufferView'] += offsets['bufferViews']
            elif key == 'images':
                assert 'uri' not in value
                value['bufferView'] += offsets['bufferViews']
            elif key == 'textures':
                for field, target in [('source', 'images'), ('sampler', 'samplers')]:
                    if field in value: value[field] += offsets[target]
            elif key == 'materials':
                def fix_texture(d):
                    if isinstance(d, dict):
                        for field, child in d.items():
                            if field.endswith('Texture') and isinstance(child, dict):
                                child['index'] += offsets['textures']
                            else: fix_texture(child)
                    elif isinstance(d, list):
                        for child in d: fix_texture(child)
                fix_texture(value)
            elif key == 'meshes':
                for primitive in value['primitives']:
                    primitive['attributes'] = {k: v+offsets['accessors'] for k, v in primitive['attributes'].items()}
                    if 'indices' in primitive: primitive['indices'] += offsets['accessors']
                    if 'material' in primitive: primitive['material'] += offsets['materials']
            elif key == 'nodes':
                if 'mesh' in value: value['mesh'] += offsets['meshes']
                if 'children' in value: value['children'] = [i+offsets['nodes'] for i in value['children']]
            document.setdefault(key, []).append(value)
    for key in ['extensionsUsed', 'extensionsRequired']:
        if key in other: document[key] = sorted(set(document.get(key, []))|set(other[key]))
    return [i+offsets['nodes'] for i in other['scenes'][other.get('scene', 0)]['nodes']]
