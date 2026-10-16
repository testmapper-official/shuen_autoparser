# -*- coding: utf-8 -*-
"""
Canonical JSON utilities for reliable comparison of profile data.

The game server may re-serialize JSON with different key ordering and
whitespace, so raw string comparison reports false differences and leads
to duplicate backups. This module provides order-independent comparison
helpers used by backup deduplication and local-vs-server verification.
"""

import hashlib
import json


def canonical_json(obj):
    """Serialize obj to a canonical string.

    Keys are sorted and separators are compact, so two JSON objects that
    contain the same data in different key order produce identical output.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def json_fingerprint(obj):
    """Return a sha256 hex digest of the canonical serialization."""
    return hashlib.sha256(canonical_json(obj).encode('utf-8')).hexdigest()


def coerce_scalar(value):
    """Loose-normalize a scalar for comparison purposes.

    Numeric strings become numbers ("123" -> 123, "1.5" -> 1.5) because the
    server historically re-serialized some values with a different type,
    which created false differences and duplicate backups.
    Whole floats collapse to int (2.0 -> 2) so that json.dumps output is
    stable across type drift.
    Any other value is returned unchanged.
    """
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return value
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def loose_normalize(obj):
    """Recursively coerce numeric strings inside dicts/lists."""
    if isinstance(obj, dict):
        return {k: loose_normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [loose_normalize(v) for v in obj]
    return coerce_scalar(obj)


def are_json_equivalent(a, b, loose=True):
    """Compare two JSON-like objects order-independently.

    With loose=True numeric strings are treated as their numeric value
    ("123" == 123, "1.50" == 1.5). Loose comparison is used for backup
    deduplication: such differences are artifacts of serialization, not
    real data changes.
    """
    if a is None or b is None:
        return a is b
    try:
        left = loose_normalize(a) if loose else a
        right = loose_normalize(b) if loose else b
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError):
        return False
