"""Lecteur du format binaire Odin Serializer (Sirenix), utilisé par Big Ambitions.

Le flux est une suite d'entrées. Chaque entrée commence par un octet de type
(voir ``Entry``), suivi du nom du champ pour les entrées « nommées », puis de
la valeur. Les objets sont délimités par StartOf*Node / EndOfNode, les
tableaux par StartOfArray / EndOfArray.

Conversion vers Python :
  - nœud (référence ou struct)  -> dict, avec "$type" (et "$id" pour les références)
  - tableau                     -> list
  - nœud ne contenant qu'un tableau (List<T>, HashSet<T>, ...) -> list
  - dictionnaire Odin ($k / $v) -> dict si les clés sont simples, sinon liste de paires
  - référence interne           -> remplacée par l'objet visé (voir resolve_references)
"""

from __future__ import annotations

import struct
import uuid
from enum import IntEnum
from typing import Any


class Entry(IntEnum):
    Invalid = 0
    NamedStartOfReferenceNode = 1
    UnnamedStartOfReferenceNode = 2
    NamedStartOfStructNode = 3
    UnnamedStartOfStructNode = 4
    EndOfNode = 5
    StartOfArray = 6
    EndOfArray = 7
    PrimitiveArray = 8
    NamedInternalReference = 9
    UnnamedInternalReference = 10
    NamedExternalReferenceByIndex = 11
    UnnamedExternalReferenceByIndex = 12
    NamedExternalReferenceByGuid = 13
    UnnamedExternalReferenceByGuid = 14
    NamedSByte = 15
    UnnamedSByte = 16
    NamedByte = 17
    UnnamedByte = 18
    NamedShort = 19
    UnnamedShort = 20
    NamedUShort = 21
    UnnamedUShort = 22
    NamedInt = 23
    UnnamedInt = 24
    NamedUInt = 25
    UnnamedUInt = 26
    NamedLong = 27
    UnnamedLong = 28
    NamedULong = 29
    UnnamedULong = 30
    NamedFloat = 31
    UnnamedFloat = 32
    NamedDouble = 33
    UnnamedDouble = 34
    NamedDecimal = 35
    UnnamedDecimal = 36
    NamedChar = 37
    UnnamedChar = 38
    NamedString = 39
    UnnamedString = 40
    NamedGuid = 41
    UnnamedGuid = 42
    NamedBoolean = 43
    UnnamedBoolean = 44
    NamedNull = 45
    UnnamedNull = 46
    TypeName = 47
    TypeID = 48
    EndOfStream = 49
    NamedExternalReferenceByString = 50
    UnnamedExternalReferenceByString = 51


# Entrées « nommées » : celles qui ont un nom de champ juste après l'octet de type.
_NAMED = {
    Entry.NamedStartOfReferenceNode, Entry.NamedStartOfStructNode,
    Entry.NamedInternalReference, Entry.NamedExternalReferenceByIndex,
    Entry.NamedExternalReferenceByGuid, Entry.NamedExternalReferenceByString,
    Entry.NamedSByte, Entry.NamedByte, Entry.NamedShort, Entry.NamedUShort,
    Entry.NamedInt, Entry.NamedUInt, Entry.NamedLong, Entry.NamedULong,
    Entry.NamedFloat, Entry.NamedDouble, Entry.NamedDecimal, Entry.NamedChar,
    Entry.NamedString, Entry.NamedGuid, Entry.NamedBoolean, Entry.NamedNull,
}

# Primitifs à taille fixe : type d'entrée (sans distinction nommé/anonyme) -> format struct.
_FIXED = {
    Entry.NamedSByte: "<b", Entry.NamedByte: "<B",
    Entry.NamedShort: "<h", Entry.NamedUShort: "<H",
    Entry.NamedInt: "<i", Entry.NamedUInt: "<I",
    Entry.NamedLong: "<q", Entry.NamedULong: "<Q",
    Entry.NamedFloat: "<f", Entry.NamedDouble: "<d",
}
_FIXED.update({Entry(k + 1): v for k, v in list(_FIXED.items())})

# Format des éléments des PrimitiveArray, deviné à partir du type .NET de l'élément.
_PRIMITIVE_ARRAY_FORMATS = {
    "System.Byte": "B", "System.SByte": "b", "System.Boolean": "?",
    "System.Int16": "h", "System.UInt16": "H", "System.Char": "H",
    "System.Int32": "i", "System.UInt32": "I",
    "System.Int64": "q", "System.UInt64": "Q",
    "System.Single": "f", "System.Double": "d",
}
_DEFAULT_BY_SIZE = {1: "B", 2: "h", 4: "i", 8: "q"}


class OdinError(Exception):
    pass


def _decimal(raw: bytes) -> float:
    lo, mid, hi, flags = struct.unpack("<iiii", raw)
    mantissa = (lo & 0xFFFFFFFF) | ((mid & 0xFFFFFFFF) << 32) | ((hi & 0xFFFFFFFF) << 64)
    scale = (flags >> 16) & 0xFF
    value = mantissa / (10 ** scale)
    return -value if flags < 0 else value


def short_type(type_name: str | None) -> str | None:
    """'System.Collections.Generic.List`1[[X, mscorlib]], mscorlib' -> 'System.Collections.Generic.List`1[[X, mscorlib]]'"""
    if type_name is None:
        return None
    depth = 0
    for i, c in enumerate(type_name):
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == "," and depth == 0:
            return type_name[:i]
    return type_name


class OdinReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.types: dict[int, str] = {}
        # Objets indexés par leur id de référence, pour résoudre les {"$ref": id}.
        self.references: dict[int, Any] = {}

    # --- lecture bas niveau -------------------------------------------------

    def _unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def _bytes(self, n: int) -> bytes:
        raw = self.data[self.pos:self.pos + n]
        self.pos += n
        return raw

    def _string(self) -> str:
        wide = self._unpack("<B")
        length = self._unpack("<i")
        if wide:
            return self._bytes(length * 2).decode("utf-16-le", errors="replace")
        return self._bytes(length).decode("latin-1")

    def _type_entry(self) -> str | None:
        entry = self._unpack("<B")
        if entry == Entry.TypeName:
            type_id = self._unpack("<i")
            name = self._string()
            self.types[type_id] = name
            return name
        if entry == Entry.TypeID:
            return self.types.get(self._unpack("<i"), "?")
        if entry == Entry.UnnamedNull:
            return None
        raise OdinError(f"entrée de type inattendue {entry} à {self.pos - 1}")

    def _peek(self) -> int:
        return self.data[self.pos]

    # --- lecture haut niveau ------------------------------------------------

    def read_root(self) -> Any:
        values = []
        while self.pos < len(self.data) and self._peek() != Entry.EndOfStream:
            _, value = self._read_entry()
            values.append(value)
        return values[0] if len(values) == 1 else values

    def _read_entry(self) -> tuple[str | None, Any]:
        start = self.pos
        entry = Entry(self._unpack("<B"))
        name = self._string() if entry in _NAMED else None

        if entry in _FIXED:
            return name, self._unpack(_FIXED[entry])
        if entry in (Entry.NamedStartOfReferenceNode, Entry.UnnamedStartOfReferenceNode):
            type_name = self._type_entry()
            ref_id = self._unpack("<i")
            node = self._read_node_body(type_name)
            self.references[ref_id] = node
            return name, node
        if entry in (Entry.NamedStartOfStructNode, Entry.UnnamedStartOfStructNode):
            return name, self._read_node_body(self._type_entry())
        if entry == Entry.StartOfArray:
            return name, self._read_array_body()
        if entry == Entry.PrimitiveArray:
            return name, self._read_primitive_array(None)
        if entry in (Entry.NamedInternalReference, Entry.UnnamedInternalReference):
            return name, {"$ref": self._unpack("<i")}
        if entry in (Entry.NamedExternalReferenceByIndex, Entry.UnnamedExternalReferenceByIndex):
            return name, {"$extIndex": self._unpack("<i")}
        if entry in (Entry.NamedExternalReferenceByGuid, Entry.UnnamedExternalReferenceByGuid):
            return name, {"$extGuid": str(uuid.UUID(bytes_le=self._bytes(16)))}
        if entry in (Entry.NamedExternalReferenceByString, Entry.UnnamedExternalReferenceByString):
            return name, {"$extString": self._string()}
        if entry in (Entry.NamedDecimal, Entry.UnnamedDecimal):
            return name, _decimal(self._bytes(16))
        if entry in (Entry.NamedChar, Entry.UnnamedChar):
            return name, chr(self._unpack("<H"))
        if entry in (Entry.NamedString, Entry.UnnamedString):
            return name, self._string()
        if entry in (Entry.NamedGuid, Entry.UnnamedGuid):
            return name, str(uuid.UUID(bytes_le=self._bytes(16)))
        if entry in (Entry.NamedBoolean, Entry.UnnamedBoolean):
            return name, self._unpack("<B") != 0
        if entry in (Entry.NamedNull, Entry.UnnamedNull):
            return name, None
        raise OdinError(f"entrée {entry.name} inattendue à l'offset {start}")

    def _read_array_body(self, element_type: str | None = None) -> list:
        self._unpack("<q")  # longueur annoncée
        items = []
        while self._peek() != Entry.EndOfArray:
            if self._peek() == Entry.PrimitiveArray:
                self.pos += 1
                items.extend(self._read_primitive_array(element_type))
                continue
            items.append(self._read_entry()[1])
        self.pos += 1
        return items

    def _read_primitive_array(self, element_type: str | None) -> list:
        count = self._unpack("<i")
        size = self._unpack("<i")
        raw = self._bytes(count * size)
        fmt = _PRIMITIVE_ARRAY_FORMATS.get(element_type or "") or _DEFAULT_BY_SIZE.get(size)
        if fmt is None or struct.calcsize(fmt) != size:
            return [raw.hex()]
        return list(struct.unpack(f"<{count}{fmt}", raw))

    def _read_node_body(self, type_name: str | None) -> Any:
        fields: dict[str, Any] = {}
        unnamed: list = []
        element_type = _element_type(type_name)
        while self._peek() != Entry.EndOfNode:
            if self._peek() == Entry.StartOfArray:
                self.pos += 1
                unnamed.append(self._read_array_body(element_type))
                continue
            if self._peek() == Entry.PrimitiveArray:
                self.pos += 1
                unnamed.append(self._read_primitive_array(element_type))
                continue
            name, value = self._read_entry()
            if name is None:
                unnamed.append(value)
            else:
                fields[name] = value
        self.pos += 1

        base = short_type(type_name) or ""
        # Nullable<T> : on ne garde que la valeur.
        if base.startswith("System.Nullable`1"):
            return unnamed[0] if unnamed else None
        # Le comparer des Dictionary/HashSet n'a aucun intérêt pour la lecture des données.
        if base.startswith(_COLLECTIONS_WITH_COMPARER):
            fields.pop("comparer", None)

        # Collection pure (List<T>, T[], HashSet<T>, Dictionary<K,V>, ...)
        if not fields and len(unnamed) == 1 and isinstance(unnamed[0], list):
            if not unnamed[0] and "Dictionary`2" in base:
                return {}
            return _maybe_dict(unnamed[0])
        node: dict[str, Any] = {"$type": short_type(type_name)} if type_name else {}
        node.update(fields)
        if unnamed:
            node["$items"] = _maybe_dict(unnamed[0]) if len(unnamed) == 1 and isinstance(unnamed[0], list) else unnamed
        return node


_COLLECTIONS_WITH_COMPARER = (
    "System.Collections.Generic.Dictionary`2",
    "System.Collections.Generic.HashSet`1",
    "System.Collections.Generic.SortedDictionary`2",
)


def _element_type(type_name: str | None) -> str | None:
    """Type de l'élément pour List`1[[T, asm]] ou T[], utilisé pour décoder les PrimitiveArray."""
    if not type_name:
        return None
    if "[[" in type_name:
        inner = type_name[type_name.index("[[") + 2:]
        return inner.split(",")[0].strip()
    base = short_type(type_name)
    if base and base.endswith("[]"):
        return base[:-2]
    return None


def _maybe_dict(items: list) -> Any:
    """Transforme une liste de paires Odin {$k, $v} en dict quand les clés sont simples."""
    if not items or not all(isinstance(i, dict) and "$k" in i and "$v" in i for i in items):
        return items
    keys = [i["$k"] for i in items]
    if all(isinstance(k, (str, int, float, bool)) for k in keys) and len(set(map(str, keys))) == len(keys):
        return {str(i["$k"]): i["$v"] for i in items}
    return [{"key": i["$k"], "value": i["$v"]} for i in items]


def resolve_references(root: Any, references: dict[int, Any]) -> Any:
    """Remplace les {"$ref": id} par l'objet visé.

    Les entités qui portent leur propre "id" (employés, managers, ...) ne sont pas
    recopiées : la référence devient {"$refType": "<type>", "id": "<id de l'entité>"},
    ce qui suffit pour faire la jointure. Les cycles sont laissés sous forme de $ref.
    """
    ancestors: set[int] = set()

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            if len(value) == 1 and "$ref" in value:
                target = references.get(value["$ref"])
                if target is None or id(target) in ancestors:
                    return value
                if isinstance(target, dict) and isinstance(target.get("id"), str):
                    return {"$refType": target.get("$type"), "id": target["id"]}
                return visit(target)
            ancestors.add(id(value))
            for key, item in value.items():
                value[key] = visit(item)
            ancestors.discard(id(value))
        elif isinstance(value, list):
            ancestors.add(id(value))
            for i, item in enumerate(value):
                value[i] = visit(item)
            ancestors.discard(id(value))
        return value

    return visit(root)


def loads(data: bytes, resolve: bool = True) -> tuple[Any, OdinReader]:
    reader = OdinReader(data)
    root = reader.read_root()
    if resolve:
        root = resolve_references(root, reader.references)
    return root, reader
