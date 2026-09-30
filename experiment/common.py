import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ('00', '10', '01', '11')

def now():
    return datetime.now(timezone.utc).isoformat()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text())

def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

def atomic_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
    if exclusive:
        with path.open('x') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
    else:
        tmp = path.with_suffix(path.suffix + '.tmp')
        with tmp.open('w') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)

def write_jsonl_once(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ''.join(canonical(row) + '\n' for row in rows)
    if path.exists():
        if path.read_text() != data:
            raise ValueError(f'Refusing to change existing frozen input: {path}')
        return
    with path.open('x') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())

def ranked(seed, namespace, value):
    return digest([seed, namespace, value])

def config(root=ROOT):
    return read_json(root / 'config/study.json')

def require(condition, message):
    if not condition:
        raise ValueError(message)
