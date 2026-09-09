import json
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from notifier.config import Config, PRODUCTS
from notifier.stock import classify
from notifier.network import Result, fetch_stock, send_message, retry_seconds, MAX_BYTES
from notifier.__main__ import sweep, run

SLUG = PRODUCTS[0].slug
POSITIVE = '''<div id="order-standard_cart"><div class="product-info"><h2>BudgetKVMSGDC1-2</h2></div>
<form id="frmConfigureProduct"><button id="btnCompleteProductConfig">Continue</button></form></div>'''
NEGATIVE = '''<div id="order-standard_cart"><div class="alert alert-danger error-heading">Out of Stock</div>
<p>We are currently out of stock on this item so orders for it have been suspended until more stock is available.</p></div>'''


def response(content='', code=200, headers=None):
    r = Mock(status_code=code, url=PRODUCTS[0].url)
    r.headers = headers or {'Content-Type': 'text/html'}
    r.iter_content.return_value = [content.encode()]
    r.__enter__ = Mock(return_value=r)
    r.__exit__ = Mock(return_value=False)
    return r


class ConfigTests(unittest.TestCase):
    def test_defaults_and_products(self):
        cfg = Config.from_env({'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '-123'})
        self.assertEqual(cfg.interval, 60)
        self.assertEqual(len(set(p.url for p in PRODUCTS)), 5)

    def test_invalid(self):
        for interval in ['nan', 'inf', 'abc', '0', '29']:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                Config.from_env({'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '1',
                                 'CHECK_INTERVAL_SECONDS': interval})
        with self.assertRaises(ValueError):
            Config.from_env({})


class ClassifierTests(unittest.TestCase):
    def test_positive_synthetic(self):
        self.assertEqual(classify(POSITIVE, SLUG), 'available')

    def test_observed_sold_out_markup(self):
        self.assertEqual(classify(NEGATIVE, SLUG), 'unavailable')

    def test_unknown(self):
        cases = [
            '', '<a href="cart.php">Order Now</a>',
            POSITIVE.replace('BudgetKVMSGDC1-2', 'WrongProduct'),
            POSITIVE.replace('<button ', '<button disabled '),
            POSITIVE.replace('frmConfigureProduct', 'wrong'),
            POSITIVE.replace('product-info', 'navigation'),
            '<title>Just a moment...</title>' + POSITIVE,
            '<form id="challenge-form"></form>' + POSITIVE,
            POSITIVE.replace('</form>', '<div class="error-heading">Out of Stock</div></form>'),
        ]
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(classify(html, SLUG), 'unknown')

    def test_script_not_stock(self):
        self.assertEqual(classify(POSITIVE + '<script>Out of Stock</script>', SLUG), 'available')


class KainodeTests(unittest.TestCase):
    def test_stock(self):
        positive = '<main><h2>VPS Advanced</h2><span>In stock</span><a href="/products/vps-singapore/vps-advanced/checkout">Order</a></main>'
        negative = '<main><h2>VPS Advanced</h2><span>Product VPS Advanced is out of stock</span></main>'
        for html, expected in [
            (positive, 'available'), (negative, 'unavailable'),
            (positive.replace('In stock', 'Welcome'), 'unknown'),
            (positive.replace('VPS Advanced', 'VPS Pro'), 'unknown'),
            (positive.replace('vps-advanced/checkout', 'vps-pro/checkout'), 'unknown'),
            (positive.replace('<a ', '<a disabled '), 'unknown'),
            (positive.replace('</main>', '<span>Product VPS Advanced is out of stock</span></main>'), 'unknown'),
            ('<title>Just a moment...</title>' + positive, 'unknown'),
        ]:
            with self.subTest(html=html):
                self.assertEqual(classify(html, 'vps-advanced', 'Kainode'), expected)


class NetworkTests(unittest.TestCase):
    def test_fetch_available(self):
        s = Mock()
        s.get.return_value = response(POSITIVE)
        self.assertEqual(fetch_stock(s, PRODUCTS[0]).status, 'available')
        self.assertFalse(s.get.call_args.kwargs['allow_redirects'])

    def test_failed_http(self):
        for code in [302, 403, 429, 500]:
            s = Mock()
            s.get.return_value = response(POSITIVE, code, {'Retry-After': '90'})
            result = fetch_stock(s, PRODUCTS[0])
            self.assertEqual(result.status, 'unknown')
            self.assertEqual(result.retry_after, 90)

    def test_unsafe_responses(self):
        for kind in ['foreign', 'type', 'large', 'timeout']:
            with self.subTest(kind=kind):
                s = Mock()
                r = response(POSITIVE)
                if kind == 'foreign':
                    r.url = 'https://example.com/'
                elif kind == 'type':
                    r.headers = {'Content-Type': 'application/json'}
                elif kind == 'large':
                    r.iter_content.return_value = [b'x' * (MAX_BYTES + 1)]
                else:
                    s.get.side_effect = requests.Timeout('SECRET')
                s.get.return_value = r
                result = fetch_stock(s, PRODUCTS[0])
                self.assertEqual(result.status, 'unknown')
                self.assertNotIn('SECRET', result.reason)

    def test_telegram(self):
        for payload, code, expected in [({'ok': True}, 200, 'sent'), ({'ok': False}, 200, 'failed'),
                                        ([], 200, 'failed'), ({'ok': True}, 500, 'failed')]:
            s = Mock()
            s.post.return_value = response(json.dumps(payload), code)
            self.assertEqual(send_message(s, 'SECRET', '1', 'text').status, expected)

    def test_telegram_retry(self):
        s = Mock()
        s.post.return_value = response('{"ok":false,"parameters":{"retry_after":120}}', 429)
        self.assertEqual(send_message(s, 'SECRET', '1', 'text').retry_after, 120)
        s.post.return_value = response('not JSON')
        self.assertEqual(send_message(s, 'SECRET', '1', 'text').status, 'failed')
        s.post.side_effect = requests.ConnectionError('https://api.telegram.org/botSECRET')
        self.assertNotIn('SECRET', send_message(s, 'SECRET', '1', 'text').reason)

    def test_retry_bounds(self):
        for value, expected in [('120', 120), ('99999', 3600), ('nan', 0), (None, 0), ('bad', 0), ('-1', 0)]:
            self.assertEqual(retry_seconds(value), expected)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config('SECRET', '1', 60)
        self.stop = Mock()
        self.stop.is_set.return_value = False
        self.stop.wait.return_value = False

    @patch('notifier.__main__.send_message', return_value=Result('sent'))
    @patch('notifier.__main__.fetch_stock', return_value=Result('available'))
    def test_repeat_every_check(self, fetch, send):
        sweep(self.cfg, Mock(), Mock(), self.stop)
        sweep(self.cfg, Mock(), Mock(), self.stop)
        self.assertEqual(send.call_count, 10)
        self.assertEqual(fetch.call_count, 10)
        self.assertIn('Kainode', send.call_args_list[4].args[3])
        self.assertIn(PRODUCTS[0].url, send.call_args_list[0].args[3])

    @patch('notifier.__main__.send_message', return_value=Result('failed'))
    @patch('notifier.__main__.fetch_stock')
    def test_no_stale_retry(self, fetch, send):
        fetch.side_effect = [Result('available')] + [Result('unknown')] * 9
        sweep(self.cfg, Mock(), Mock(), self.stop)
        sweep(self.cfg, Mock(), Mock(), self.stop)
        self.assertEqual(send.call_count, 1)

    @patch('notifier.__main__.send_message', return_value=Result('failed', 120, True))
    @patch('notifier.__main__.fetch_stock', return_value=Result('available'))
    def test_telegram_rate_limit(self, fetch, send):
        result = sweep(self.cfg, Mock(), Mock(), self.stop, clock=lambda: 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(result[1:], (120, 120))

    @patch('notifier.__main__.fetch_stock', return_value=Result('unknown', 120, True))
    def test_origin_rate_limit(self, fetch):
        sweep(self.cfg, Mock(), Mock(), self.stop)
        self.assertEqual(fetch.call_count, 1)

    @patch('notifier.__main__.fetch_stock')
    def test_stopped(self, fetch):
        stop = threading.Event()
        stop.set()
        sweep(self.cfg, Mock(), Mock(), stop)
        fetch.assert_not_called()

    @patch('notifier.__main__.sweep', return_value=(True, 0, 0))
    def test_loop_backoff_and_shutdown(self, check):
        self.stop.is_set.side_effect = [False, True]
        run(self.cfg, self.stop)
        self.stop.wait.assert_called_once_with(120)


if __name__ == '__main__':
    unittest.main()
