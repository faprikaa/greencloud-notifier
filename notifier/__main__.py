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
            # Pace messages even when all products are available.
            if stop.wait(1):
                break
        if result.retry_after:
            break  # Respect origin rate limits before checking another product.
    return transient, retry, telegram_until


def verify_telegram(config, telegram, stop):
    """Do not start monitoring until the destination accepts a real message."""
    attempts = 0
    while not stop.is_set():
        result = send_message(
            telegram, config.token, config.chat_id,
            f'✅ Tes Telegram berhasil — VPS notifier siap memantau {len(PRODUCTS)} produk.\n'
            f'Interval dasar: {config.interval:g} detik.\n'
            'Pesan ini bukan pemberitahuan stok tersedia. '
            'Notif stok dikirim setiap pengecekan yang memastikan produk tersedia.',
        )
        if result.status == 'sent':
            LOG.info('Tes Telegram berhasil: chat tujuan menerima pesan startup.')
            return not stop.wait(1)
        attempts = min(attempts + 1, 4)
        delay = max(config.interval, result.retry_after, min(900, 60 * 2 ** attempts))
        LOG.error('Tes Telegram gagal (%s). Periksa token, chat ID, dan akses bot. '
                  'Pemantauan belum dimulai; coba lagi dalam %ss.', result.reason, delay)
        if stop.wait(delay):
            break
    return False


def run(config, stop):
    failures, telegram_until = 0, 0
    with requests.Session() as web, requests.Session() as telegram:
        if not verify_telegram(config, telegram, stop):
            LOG.info('Notifier berhenti sebelum pemantauan dimulai.')
            return
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
