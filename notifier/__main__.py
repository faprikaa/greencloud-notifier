"""Run with python -m notifier. No state or duplicate suppression by design."""
import logging
import signal
import threading
import time
from datetime import datetime, timezone

import requests

from .config import Config, PRODUCTS
from .network import fetch_stock, send_message

LOG = logging.getLogger('notifier')


def sweep(config, web, telegram, stop, telegram_until=0, clock=time.monotonic):
    transient, retry = False, 0
    for product in PRODUCTS:
        if stop.is_set():
            break
        result = fetch_stock(web, product)
        LOG.info('%s: %s %s', product.name, result.status, result.reason)
        transient |= result.transient
        retry = max(retry, result.retry_after)
        if result.status == 'available' and clock() >= telegram_until and not stop.is_set():
            text = (f'🟢 VPS {product.provider} tersedia!\n{product.name}\n{product.url}\n'
                    f'Cek: {datetime.now(timezone.utc).isoformat(timespec="seconds")}\n'
                    'Segera cek/order manual. Stok bisa berubah.')
            delivery = send_message(telegram, config.token, config.chat_id, text)
            LOG.info('%s: Telegram %s %s', product.name, delivery.status, delivery.reason)
            transient |= delivery.transient
            retry = max(retry, delivery.retry_after)
            if delivery.retry_after:
                telegram_until = clock() + delivery.retry_after
            # Pace messages even when all four products are available.
            if stop.wait(1):
                break
        if result.retry_after:
            break  # Respect origin rate limits before checking another product.
    return transient, retry, telegram_until


def run(config, stop):
    failures, telegram_until = 0, 0
    with requests.Session() as web, requests.Session() as telegram:
        web.headers.update({'User-Agent': 'GreenCloudStockNotifier/1.0', 'Accept-Language': 'en'})
        LOG.info('Memantau %s produk; interval %ss; notif di setiap cek tersedia.', len(PRODUCTS), config.interval)
        while not stop.is_set():
            transient, retry, telegram_until = sweep(config, web, telegram, stop, telegram_until)
            failures = min(failures + 1, 4) if transient else 0
            backoff = min(900, 60 * 2 ** failures) if failures else 0
            delay = max(config.interval, retry, backoff)
            LOG.info('Pengecekan berikutnya dalam %ss.', delay)
            stop.wait(delay)
    LOG.info('Notifier berhenti.')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = Config.from_env()
    except ValueError as exc:
        LOG.error('%s', exc)
        return 2
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(config, stop)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
