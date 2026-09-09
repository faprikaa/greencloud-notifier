"""Bounded HTTP requests; exceptions and token-bearing URLs are never logged."""
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests

from .stock import classify

TIMEOUT = (5, 20)
MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Result:
    status: str
    retry_after: float = 0
    transient: bool = False
    reason: str = ''


def retry_seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0
    return min(3600, max(0, seconds)) if math.isfinite(seconds) else 0


def body(response):
    chunks, size = [], 0
    for chunk in response.iter_content(16384):
        size += len(chunk)
        if size > MAX_BYTES:
            raise ValueError('response-too-large')
        chunks.append(chunk)
    return b''.join(chunks)


def fetch_stock(session, product):
    try:
        # Do not follow redirects into a generic cart/login/protection page.
        with session.get(product.url, params={'language': 'english'}, timeout=TIMEOUT,
                         allow_redirects=False, stream=True) as response:
            code = response.status_code
            if code != 200:
                return Result('unknown', retry_seconds(response.headers.get('Retry-After')),
                              code in (403, 429) or code >= 500, f'HTTP {code}')
            expected, actual = urlsplit(product.url), urlsplit(response.url)
            if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
                return Result('unknown', reason='unexpected URL')
            if 'text/html' not in response.headers.get('Content-Type', '').lower():
                return Result('unknown', reason='non-HTML response')
            status = classify(body(response).decode('utf-8', errors='replace'), product.slug, product.provider)
            return Result(status, reason='unrecognized or ambiguous HTML' if status == 'unknown' else '')
    except (requests.RequestException, ValueError):
        return Result('unknown', transient=True, reason='request/response failure')


def send_message(session, token, chat_id, text):
    try:
        with session.post(f'https://api.telegram.org/bot{token}/sendMessage',
                          json={'chat_id': chat_id, 'text': text,
                                'link_preview_options': {'is_disabled': True}},
                          timeout=TIMEOUT, allow_redirects=False, stream=True) as response:
            retry = retry_seconds(response.headers.get('Retry-After'))
            try:
                payload = json.loads(body(response))
            except (ValueError, UnicodeError):
                return Result('failed', retry, True, 'invalid Telegram response')
            if not isinstance(payload, dict):
                return Result('failed', retry, True, 'invalid Telegram response')
            parameters = payload.get('parameters')
            if isinstance(parameters, dict):
                retry = max(retry, retry_seconds(parameters.get('retry_after')))
            if response.status_code == 200 and payload.get('ok') is True:
                return Result('sent')
            return Result('failed', retry, True, f'Telegram HTTP {response.status_code}')
    except (requests.RequestException, ValueError):
        return Result('failed', transient=True, reason='Telegram request failure')
