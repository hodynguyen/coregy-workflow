"""
Minimal indentation-aware YAML reader (stdlib only).

Covers the subset coregy's config files use: nested mappings, block lists
(including lists of mappings), inline `[a, b]` / `{}` collections, quoted and
plain scalars, booleans, null, ints/floats, and `#` comments. It is not a full
YAML implementation -- anchors, multi-line strings and flow mappings with
content are out of scope.

The per-file line parsers that predate this module keyed everything off fixed
indent levels, which silently mis-parsed the plugin's own default
quality-rules.yaml (a list nested under a key under a key came out flattened).
"""
import re

_KEY_RE = re.compile(r"^(?P<key>[^\s#'\"][^:]*?|'[^']*'|\"[^\"]*\")\s*:(?:\s+(?P<val>.*))?$")


def _strip_comment(text):
    """Drop a trailing `# comment` that sits outside quotes."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def _lines(content):
    out = []
    for raw in content.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.strip() in ("---", "..."):
            continue
        text = _strip_comment(raw.replace("\t", "  "))
        if not text.strip():
            continue
        indent = len(text) - len(text.lstrip(" "))
        out.append([indent, text.strip()])
    return out


def parse_scalar(val):
    """Convert a YAML scalar (or inline collection) to a Python value."""
    if val is None:
        return None
    val = val.strip()
    if val == "":
        return None
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part) for part in _split_inline(inner)]
    if val == "{}":
        return {}
    low = val.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _split_inline(inner):
    parts, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def _is_item(text):
    return text == "-" or text.startswith("- ")


def _parse_block(lines, i, indent):
    if _is_item(lines[i][1]):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_list(lines, i, indent):
    result = []
    while i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
        body = lines[i][1][1:].lstrip()
        if not body:
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                value, i = _parse_block(lines, i, lines[i][0])
            else:
                value = None
            result.append(value)
            continue
        if _KEY_RE.match(body) and not body.startswith(("[", "{")):
            # "- key: value" opens a mapping whose keys align with `key`
            child_indent = indent + (len(lines[i][1]) - len(body))
            lines[i] = [child_indent, body]
            value, i = _parse_map(lines, i, child_indent)
            result.append(value)
            continue
        result.append(parse_scalar(body))
        i += 1
    return result, i


def _parse_map(lines, i, indent):
    result = {}
    while i < len(lines) and lines[i][0] == indent and not _is_item(lines[i][1]):
        m = _KEY_RE.match(lines[i][1])
        if not m:
            i += 1  # not a key line -- skip rather than fail
            continue
        key = m.group("key").strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
            key = key[1:-1]
        val = m.group("val")
        i += 1
        if val is not None and val.strip():
            result[key] = parse_scalar(val)
        elif i < len(lines) and lines[i][0] > indent:
            result[key], i = _parse_block(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
            # YAML allows a block list at the same indent as its key
            result[key], i = _parse_list(lines, i, indent)
        else:
            result[key] = None
    return result, i


def loads(content):
    """Parse YAML text. Returns a dict (or list) -- {} for empty input."""
    lines = _lines(content or "")
    if not lines:
        return {}
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value
