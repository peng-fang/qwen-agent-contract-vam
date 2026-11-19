"""Small versioned JSON records for the local workflow; no credentials are stored."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / 'backend' / 'workspace' / 'workflows'
_lock = threading.RLock()


class RevisionConflict(ValueError):
    pass


def _path(kind: str, record_id: str) -> Path:
    if kind not in {'reports', 'conversations', 'verifications', 'payments'} or not re.fullmatch(r'[a-f0-9]{32}', record_id):
        raise ValueError('记录编号无效')
    return ROOT / kind / f'{record_id}.json'


def get(kind: str, record_id: str) -> dict:
    with _lock:
        try:
            return json.loads(_path(kind, record_id).read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise KeyError('记录不存在或已清理') from exc


def save(kind: str, data: dict, *, expected: int | None = None) -> dict:
    with _lock:
        result = deepcopy(data)
        record_id = result.setdefault('id', uuid.uuid4().hex)
        path = _path(kind, record_id)
        current = get(kind, record_id) if path.exists() else None
        if current and expected != current['revision']:
            raise RevisionConflict('记录已更新，请重新加载后提交')
        result['revision'] = (current['revision'] if current else 0) + 1
        result['updated_at'] = datetime.now(timezone.utc).isoformat()
        result.setdefault('created_at', result['updated_at'])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
                temporary = Path(f.name)
                json.dump(result, f, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return result
