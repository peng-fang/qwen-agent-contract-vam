"""合同风险审查服务封装 + 整份审查结果缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rental_review import review_contract  # noqa: E402

CACHE_DIR = ROOT / 'backend' / 'cache' / 'reviews'
CACHE_VERSION = '12'


def _cache_enabled() -> bool:
    return os.getenv('REVIEW_CACHE_ENABLED', '1').strip().lower() not in {'0', 'false', 'no'}


def _cache_ttl_seconds() -> int:
    try:
        hours = float(os.getenv('REVIEW_CACHE_TTL_HOURS', '168'))
    except ValueError:
        hours = 168
    return max(1, int(hours * 3600))


def _cache_key(path: str, region: str, contract_type: str, use_llm: bool) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    model_settings = {k: os.getenv(k, '') for k in (
        'REVIEW_MODEL_PROVIDER', 'WORKFLOW_MODEL', 'OPENAI_MODEL', 'ANALYZE_MODEL',
        'JUDGE_MODEL', 'JUDGE_FAST_MODEL', 'OLLAMA_MODEL', 'OLLAMA_BASE_URL')}
    raw = f'{CACHE_VERSION}|{digest}|{region}|{contract_type}|{int(use_llm)}|{json.dumps(model_settings, sort_keys=True)}'
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f'{key}.json'


def _read_cache(key: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    cached_at = float(data.get('cached_at', 0))
    if time.time() - cached_at > _cache_ttl_seconds():
        return None
    result = data.get('result')
    return result if isinstance(result, dict) else None


def _write_cache(key: str, result: Dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(
            json.dumps({'cached_at': time.time(), 'result': result}, ensure_ascii=False),
            encoding='utf-8',
        )
    except Exception:
        # 缓存失败不应影响审查主流程
        pass


def run(
    path: str,
    filename: str,
    use_llm: bool = True,
    region: str = 'mainland',
    contract_type: str = 'rental',
    progress: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    env_toggle = os.getenv('RENTAL_REVIEW_USE_LLM', '1').strip().lower()
    enabled = use_llm and env_toggle not in {'0', 'false', 'no'}

    key = None
    if _cache_enabled():
        try:
            key = _cache_key(path, region, contract_type, enabled)
        except Exception:
            key = None
    if key:
        cached = _read_cache(key)
        if cached is not None:
            cached['filename'] = filename
            cached['cache_hit'] = True
            if progress:
                progress('cache', 'done', '命中整份审查结果缓存，直接返回。')
            return cached

    result = review_contract(
        path,
        filename=filename,
        use_llm=enabled,
        region=region,
        contract_type=contract_type,
        progress=progress,
    )
    result['cache_hit'] = False
    degraded = any('模型分析失败' in warning or 'Judge Agent 未返回' in warning for warning in result.get('warnings', []))
    if key and not degraded:
        _write_cache(key, result)
    return result


__all__ = ['run']
