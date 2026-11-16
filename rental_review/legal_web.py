"""官方来源法律检索兜底。

只在本地条文库没有命中时使用；不是让模型自由编法条。
流程：Bing 搜索 → 官方域名白名单 → 抓取页面 → 校验条号/关键词 → 缓存。
抓取失败或无法核验时返回空，前端标记“待人工复核”。
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ALLOWLIST = {
    'mainland': ('gov.cn', 'npc.gov.cn', 'flk.npc.gov.cn', 'court.gov.cn'),
    'hongkong': ('elegislation.gov.hk', 'hklii.hk', 'judiciary.hk'),
}
DOMAINS_BY_TYPE = {
    'labor': {
        'mainland': ('gov.cn', 'npc.gov.cn', 'mohrss.gov.cn'),
        'hongkong': ('elegislation.gov.hk',),
    },
    'loan': {
        'mainland': ('gov.cn', 'npc.gov.cn', 'pbc.gov.cn'),
        'hongkong': ('elegislation.gov.hk', 'hkma.gov.hk'),
    },
    'dispute': {
        'mainland': ('gov.cn', 'npc.gov.cn', 'court.gov.cn'),
        'hongkong': ('elegislation.gov.hk', 'hklii.hk', 'judiciary.hk'),
    },
    'ecommerce': {
        'mainland': ('gov.cn', 'npc.gov.cn', 'samr.gov.cn'),
        'hongkong': ('elegislation.gov.hk', 'hklii.hk'),
    },
    'franchise': {
        'mainland': ('gov.cn', 'mofcom.gov.cn'),
        'hongkong': ('elegislation.gov.hk', 'hklii.hk'),
    },
}
CAP_HINTS = {
    'labor': ('cap57', 'cap485', '僱傭條例', '雇佣条例', '強制性公積金', '强制性公积金'),
    'loan': ('cap163', '放債人', '放债人'),
    'dispute': ('cap609', '仲裁條例', '仲裁条例'),
    'ecommerce': ('cap362', '商品說明', '商品说明', 'cap458'),
    'franchise': ('cap458', '不合情理'),
    'rental': ('cap7', '業主與租客', '业主与租客'),
    'consumer': ('cap458', '不合情理'),
    'procurement': ('cap26', '貨品售賣', '货品售卖'),
}
SEARCH_CONTEXT = {
    ('labor', 'hongkong'): '香港 僱傭條例',
    ('labor', 'mainland'): '中国 劳动合同法',
    ('loan', 'hongkong'): '香港 放債人條例',
    ('loan', 'mainland'): '中国 民法典 借款合同',
    ('dispute', 'hongkong'): '香港 仲裁條例',
    ('dispute', 'mainland'): '中国 民事诉讼法 仲裁法',
    ('ecommerce', 'hongkong'): '香港 商品說明條例',
    ('ecommerce', 'mainland'): '中国 电子商务法 消费者权益保护法',
    ('franchise', 'hongkong'): '香港 特許經營 合約',
    ('franchise', 'mainland'): '中国 商业特许经营管理条例',
}


def _domains(region: str, contract_type: str | None = None) -> tuple:
    by_type = DOMAINS_BY_TYPE.get((contract_type or '').strip().lower(), {})
    return tuple(by_type.get(region) or ALLOWLIST.get(region, ()))


def _context_query(query: str, region: str, contract_type: str | None = None) -> str:
    context = SEARCH_CONTEXT.get(((contract_type or '').lower(), region), '')
    return f'{context} {query}'.strip()
CACHE_DIR = Path(__file__).resolve().parents[1] / 'backend' / 'cache' / 'legal'
CACHE_TTL_SECONDS = 30 * 24 * 3600
CACHE_VERSION = 3
_ARTICLE_RE = re.compile(r'第[一二三四五六七八九十百零〇\d]{1,12}[条條]')


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f'{hashlib.sha256(key.encode()).hexdigest()}.json'


def _read_cache(key: str) -> List[dict]:
    path = _cache_path(key)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return []
    if time.time() - float(data.get('cached_at', 0)) > CACHE_TTL_SECONDS:
        return []
    return data.get('results') or []


def _write_cache(key: str, results: List[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps({'cached_at': time.time(), 'results': results}, ensure_ascii=False),
        encoding='utf-8',
    )


def _decode_bing(url: str) -> str:
    url = html.unescape(url)
    match = re.search(r'[?&]u=a1([^&]+)', url)
    if not match:
        return url
    raw = match.group(1)
    raw += '=' * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw).decode('utf-8', errors='ignore')
    except Exception:
        return url


def _tavily_call(
    api_key: str,
    domains: List[str],
    search_query: str,
    region: str,
    contract_type: str | None,
    limit: int,
    search_depth: str,
) -> List[dict]:
    try:
        resp = requests.post(
            'https://api.tavily.com/search',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'query': search_query,
                'search_depth': search_depth,
                'max_results': max(limit, 5),
                'include_domains': domains,
                'include_answer': False,
                'include_raw_content': False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = []
        seen = set()
        for item in resp.json().get('results', []):
            url = str(item.get('url') or '')
            title = str(item.get('title') or '')
            if not url or url in seen or not any(d in url for d in domains):
                continue
            hints = CAP_HINTS.get((contract_type or '').strip().lower(), ())
            if region == 'hongkong' and hints and not any(h.lower() in (url + ' ' + title).lower() for h in hints):
                continue
            seen.add(url)
            results.append({
                'url': url,
                'title': title,
                'content': str(item.get('content') or ''),
            })
        return results[:limit]
    except Exception:
        return []


def _tavily_results(query: str, region: str, limit: int = 3, contract_type: str | None = None) -> List[dict]:
    api_key = os.getenv('TAVILY_API_KEY', '').strip()
    domains = list(_domains(region, contract_type))
    if not api_key or not domains:
        return []
    search_query = _context_query(query, region, contract_type)
    depth = os.getenv('TAVILY_SEARCH_DEPTH', 'basic').strip().lower() or 'basic'
    results = _tavily_call(api_key, domains, search_query, region, contract_type, limit, depth)
    if not results and depth != 'advanced':
        results = _tavily_call(api_key, domains, search_query, region, contract_type, limit, 'advanced')
    return results


def _tavily_links(query: str, region: str, limit: int = 3, contract_type: str | None = None) -> List[str]:
    return [item['url'] for item in _tavily_results(query, region, limit, contract_type)]


def _search_links(query: str, region: str, limit: int = 3, contract_type: str | None = None) -> List[str]:
    provider = os.getenv('LEGAL_WEB_PROVIDER', 'bing').strip().lower()
    if provider == 'tavily':
        return _tavily_links(query, region, limit, contract_type)

    api_key = os.getenv('SERPAPI_KEY', '').strip()
    domains = _domains(region, contract_type)
    links: List[str] = []
    search_query = _context_query(query, region, contract_type)

    if provider == 'serpapi' and api_key:
        for domain in domains:
            try:
                resp = requests.get(
                    'https://serpapi.com/search.json',
                    params={
                        'engine': 'google',
                        'q': f'site:{domain} {search_query}',
                        'api_key': api_key,
                        'num': limit,
                    },
                    timeout=15,
                )
                for item in resp.json().get('organic_results', []):
                    url = item.get('link') or ''
                    if url and url not in links and any(d in url for d in (domain,)):
                        links.append(url)
            except Exception:
                continue
            if len(links) >= limit:
                break
        return links[:limit]

    for domain in domains:
        try:
            resp = requests.get(
                'https://www.bing.com/search',
                params={'q': f'site:{domain} {search_query}'},
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=8,
            )
            for raw in re.findall(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"', resp.text):
                url = _decode_bing(raw)
                if any(url.startswith(f'https://{d}') or f'.{d}/' in url for d in (domain,)):
                    if url not in links:
                        links.append(url)
        except Exception:
            continue
        if len(links) >= limit:
            break
    return links[:limit]


def _decode_html(raw: bytes, declared: str | None = None) -> str:
    candidates = []
    if declared:
        candidates.append(declared)
    head = raw[:4096].decode('ascii', errors='ignore')
    meta = re.search(r'charset=["\']?\s*([\w-]+)', head, re.I)
    if meta:
        candidates.append(meta.group(1))
    candidates.extend(['utf-8', 'gb18030', 'big5'])
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
            if text.count('\ufffd') / max(1, len(text)) < 0.01:
                return text
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace')


def _fetch_page(url: str) -> str:
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    resp.raise_for_status()
    text = _decode_html(resp.content, resp.encoding)
    soup = BeautifulSoup(text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'svg']):
        tag.decompose()
    visible = soup.get_text(' ', strip=True)
    return re.sub(r'\s+', ' ', visible).strip()


def _article_from_url(url: str) -> str:
    match = re.search(r'/s(\d+[A-Za-z]*)', url, re.I)
    if match:
        return f'第{match.group(1)}条'
    return ''


_TRAD = str.maketrans('试用期工资强积金补偿竞业限制劳动合同雇佣', '試用期工資強積金補償競業限制勞動合同僱傭')


def _clean_tavily_summary(content: str, query: str) -> str:
    text = re.sub(r'Title:\s*[^。；;]{0,160}', ' ', content or '')
    text = re.sub(r'Image\s*\d+:[^。；;]{0,220}', ' ', text, flags=re.I)
    text = re.sub(r'(?:\*?\s*:\s*)?(?:徽章|logo)[^。；;]{0,220}', ' ', text, flags=re.I)
    text = re.sub(r'电子版香港法例[^。；;]{0,160}', ' ', text)
    text = re.sub(r'[A-Za-z][A-Za-z\s.,()\-]{20,}', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    tokens = [
        token for token in re.findall(r'[\u4e00-\u9fff]{2,6}', query)
        if token not in {'合同', '条款', '风险', '可能', '要求', '明确'}
    ]
    head_tokens = set()
    for raw in re.findall(r'[\u4e00-\u9fff]{2,6}', query[:28]):
        head_tokens.add(raw)
        for size in (2, 3, 4):
            for start in range(0, max(1, len(raw) - size + 1)):
                part = raw[start:start + size]
                if len(part) == size and part not in {'合同', '条款', '风险', '可能'}:
                    head_tokens.add(part)
    sentences = [s.strip() for s in re.split(r'(?<=[。；;])', text) if s.strip()]
    scored = []
    for index, sentence in enumerate(sentences):
        if len(re.findall(r'[\u4e00-\u9fff]', sentence)) < 8:
            continue
        if head_tokens and not any(
            token in sentence or token.translate(_TRAD) in sentence for token in head_tokens
        ):
            continue
        score = sum(
            1 for token in tokens
            if token in sentence or token.translate(_TRAD) in sentence
        )
        if score:
            scored.append((score, index, sentence))
    if not scored:
        return ''
    best = sorted(scored, key=lambda item: (-item[0], item[1]))[:3]
    return ' '.join(item[2] for item in sorted(best, key=lambda item: item[1]))[:700]


def search_official(query: str, region: str, limit: int = 2, contract_type: str | None = None) -> List[dict]:
    if os.getenv('LEGAL_WEB_SEARCH_ENABLED', '1').strip().lower() in {'0', 'false', 'no'}:
        return []
    region = region if region in ALLOWLIST else 'mainland'
    key = f'v{CACHE_VERSION}|{region}|{contract_type or ""}|{query}'
    cached = _read_cache(key)
    if cached:
        return cached

    provider = os.getenv('LEGAL_WEB_PROVIDER', 'bing').strip().lower()
    if provider == 'tavily':
        results: List[dict] = []
        for item in _tavily_results(query, region, limit=limit + 1, contract_type=contract_type):
            url = item['url']
            title = item.get('title') or ''
            content = (item.get('content') or '').strip()
            if not content:
                try:
                    content = _fetch_page(url)[:700]
                except Exception:
                    content = ''
            article_match = _ARTICLE_RE.search(title) or _ARTICLE_RE.search(content)
            article = article_match.group(0) if article_match else _article_from_url(url)
            if not article:
                article = '官方网页（未识别条号）'
            # 已拿到官方页面摘要，但“是否适用于本案”仍需 Judge/人工复核
            verified = False
            domain = urlparse(url).netloc or url
            summary = _clean_tavily_summary(content, query)
            results.append({
                'article_id': f'web-{hashlib.sha1(url.encode()).hexdigest()[:10]}',
                'article': article,
                'title': (title[:100] or '官方网页'),
                'summary': summary or 'Tavily 未返回正文摘要；请点击来源链接复核。',
                'source': domain,
                'source_url': url,
                'jurisdiction': region,
                'contract_types': [],
                'note': '官方网页摘要（Tavily 提取，非逐字全文）；完整条文请点来源复核。',
                'matched_keywords': [],
                'source_type': 'official_web',
                'verified': verified,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
            })
            if len(results) >= limit:
                break
        if results:
            _write_cache(key, results)
        return results

    results = []
    for url in _search_links(query, region, limit=limit + 1, contract_type=contract_type):
        try:
            text = _fetch_page(url)
        except Exception:
            continue
        article_match = _ARTICLE_RE.search(text)
        url_article = _article_from_url(url)
        article = article_match.group(0) if article_match else (url_article or '官方网页（未识别条号）')
        blocked_page = any(
            marker in text
            for marker in ('WZWS', '安全验证', '访问验证', 'Loading required resource', 'Please wait')
        )
        chinese_ratio = len(re.findall(r'[\u4e00-\u9fff]', text)) / max(1, len(text))
        snippet = text[:500]
        if article_match:
            start = max(0, article_match.start() - 80)
            snippet = text[start:start + 420]
        elif blocked_page or chinese_ratio < 0.05:
            snippet = '官方页面需要浏览器验证或脚本加载，正文未能直接抓取；请点击来源链接人工复核。'
        verified = bool(article_match) and not blocked_page and any(
            token in text for token in re.findall(r'[\u4e00-\u9fff]{2,6}', query)[:6]
        )
        domain = urlparse(url).netloc or url
        results.append({
            'article_id': f'web-{hashlib.sha1(url.encode()).hexdigest()[:10]}',
            'article': article,
            'title': '官方网页',
            'summary': snippet,
            'source': domain,
            'source_url': url,
            'jurisdiction': region,
            'contract_types': [],
            'note': '官方网页检索结果；条号/原文需人工复核。',
            'matched_keywords': [],
            'source_type': 'official_web',
            'verified': verified,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= limit:
            break
    if results:
        _write_cache(key, results)
    return results


__all__ = ['ALLOWLIST', 'search_official']
