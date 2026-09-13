"""Conservative schema-bound CarParams identity; no runtime/control imports.

V1 accepts bounded single-segment messages only. It ignores pointer relocation
and unreachable ZERO allocation words, not unknown fields or payload bits.
The complete wire tree must be reproducible from the pinned schema's field tree.
This is a versioned fingerprint, not the general Cap'n Proto canonical encoding.
"""
from __future__ import annotations

import hashlib
import math
import struct

from .provenance import ValidationError, canonical_hash, check_sha, require


SCHEMA_NODE_ID = 10117678668049983962


def validate_proof(proof):
  require(isinstance(proof, dict) and set(proof) == {'canonical_sha256', 'raw_sha256', 'schema_sha256',
          'schema_node_id', 'version', 'unused_zero_words', 'size_bytes'}, 'CarParams proof fields incomplete/unknown')
  for key in ('canonical_sha256', 'raw_sha256', 'schema_sha256'): check_sha(proof[key])
  require(type(proof['version']) is int and proof['version'] == 1 and
          type(proof['schema_node_id']) is int and proof['schema_node_id'] == SCHEMA_NODE_ID, 'CarParams proof schema/version invalid')
  size, unused = proof['size_bytes'], proof['unused_zero_words']
  require(type(size) is int and 16 <= size <= 1_048_576 and size % 8 == 0, 'CarParams proof size invalid')
  require(isinstance(unused, list) and all(type(i) is int and 0 < i < (size-8)//8 for i in unused) and
          unused == sorted(set(unused)), 'CarParams proof unused-word indices invalid')
  return proof


def wire_tree(raw):
  require(isinstance(raw, bytes) and 16 <= len(raw) <= 1_048_576 and len(raw) % 8 == 0, "invalid CarParams byte length")
  segments, words = struct.unpack_from('<II', raw)
  require(segments == 0 and len(raw) == 8 + words * 8, "unsupported CarParams framing/segments/trailing bytes")
  data = raw[8:]
  used = set()
  remaining_nodes = 32768

  def visit(count=1):
    nonlocal remaining_nodes
    remaining_nodes -= count
    require(remaining_nodes >= 0, "CarParams object traversal limit")

  def claim(start, count):
    require(0 <= start <= words and 0 <= count <= words - start, "CarParams pointer out of bounds")
    span = set(range(start, start + count))
    require(not used.intersection(span), "CarParams overlapping/cyclic objects")
    used.update(span)

  def word(index):
    require(0 <= index < words, "CarParams pointer outside segment")
    return struct.unpack_from('<Q', data, index * 8)[0]

  def body(start, nd, np, depth):
    visit()
    return ['struct', data[start*8:(start+nd)*8].hex(),
            [pointer(start + nd + i, depth + 1) for i in range(np)]]

  def pointer(index, depth):
    visit()
    require(depth <= 64, "CarParams pointer nesting limit")
    value = word(index)
    if value == 0:
      return ['null']
    kind = value & 3
    require(kind in (0, 1), "unsupported CarParams far/capability pointer")
    offset = (value >> 2) & 0x3fffffff
    if offset & 0x20000000:
      offset -= 0x40000000
    start = index + 1 + offset
    if kind == 0:
      nd, np = (value >> 32) & 0xffff, value >> 48
      claim(start, nd + np)
      return body(start, nd, np, depth)
    size, count = (value >> 32) & 7, value >> 35
    require(count <= 131072, "CarParams list traversal limit")
    if size == 7:
      claim(start, count + 1)
      tag = word(start)
      require(tag & 3 == 0, "invalid CarParams composite tag")
      number, nd, np = (tag >> 2) & 0x3fffffff, (tag >> 32) & 0xffff, tag >> 48
      require(number <= 131072 and number * (nd + np) == count, "invalid CarParams composite extent")
      require(number <= remaining_nodes, "CarParams composite amplification limit")
      return ['composite', [body(start + 1 + i*(nd+np), nd, np, depth) for i in range(number)], nd, np]
    if size == 6:
      claim(start, count)
      return ['pointers', [pointer(start+i, depth+1) for i in range(count)]]
    bits = (0, 1, 8, 16, 32, 64)[size] * count
    nwords = (bits + 63) // 64
    claim(start, nwords)
    payload = data[start*8:(start+nwords)*8]
    require(not bits or int.from_bytes(payload, 'little') >> bits == 0, "nonzero CarParams list padding")
    return ['list', size, count, payload.hex()]

  claim(0, 1)
  tree = pointer(0, 0)
  require(tree[0] == 'struct', "CarParams root is not a struct")
  unused = sorted(set(range(words)) - used)
  require(all(word(i) == 0 for i in unused), "unknown nonzero unreachable CarParams data")
  return tree, unused


def fingerprint(raw, expected_schema_sha256):
  """Prove schema coverage before hashing all known AND structural semantics."""
  from pathlib import Path
  import capnp
  from opendbc.car.structs import car

  # Builder allocation is not the fingerprint; the structural tree is. Pin the
  # decoder ABI and exact schema rather than assuming schema IDs are versions.
  require(capnp.__version__ == '2.1.0', "unsupported CarParams decoder version")
  import opendbc.car.structs as structs
  schema_path = Path(structs.__file__).with_name('car.capnp')
  schema_sha = hashlib.sha256(schema_path.read_bytes()).hexdigest()
  require(schema_sha == expected_schema_sha256, "CarParams schema incompatible")
  original, unused = wire_tree(raw)
  try:
    with car.CarParams.from_bytes(raw, traversal_limit_in_words=131072, nesting_limit=64) as reader:
      fields = reader.to_dict()
      def finite(value):
        if isinstance(value, float):
          require(math.isfinite(value), "nonfinite CarParams field")
        elif isinstance(value, dict):
          for child in value.values(): finite(child)
        elif isinstance(value, (tuple, list)):
          for child in value: finite(child)
      finite(fields)
      def preserve_presence(obj, decoded):
        # to_dict materializes a default-valued nested struct even for a null
        # pointer inside a group. Keep pointer presence, not merely its values.
        for name in list(decoded):
          field = obj.schema.fields[name].proto
          if field.which() == 'slot' and field.slot.type.which() in ('struct', 'list', 'text', 'data') and not obj._has(name):
            del decoded[name]
            continue
          child = getattr(obj, name)
          if isinstance(decoded[name], dict):
            preserve_presence(child, decoded[name])
          elif isinstance(decoded[name], list):
            for item, tree in zip(child, decoded[name]):
              if isinstance(tree, dict): preserve_presence(item, tree)
      preserve_presence(reader, fields)
      rebuilt = car.CarParams.new_message(**fields).to_bytes()
      # Rebuilding only schema-visible fields exposes unknown fields/bits,
      # padding, union payload and pointer-presence differences: never drop them.
      known, _ = wire_tree(rebuilt)
      require(original == known, "unknown/unclassified CarParams fields or encoding")
      copied = reader.as_builder().to_bytes()
      require(wire_tree(copied)[0] == original, "CarParams copy lost wire semantics")
      node_id = int(reader.schema.node.id)
  except ValidationError:
    raise
  except Exception as exc:
    raise ValidationError('CarParams fingerprint generation failed: ' + str(exc)) from exc
  identity = {'version': 1, 'schema_sha256': schema_sha, 'schema_node_id': node_id, 'wire_tree': original}
  return validate_proof({'canonical_sha256': canonical_hash(identity), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
          'schema_sha256': schema_sha, 'schema_node_id': node_id, 'version': 1,
          'unused_zero_words': unused, 'size_bytes': len(raw)})
