"""Conservative stock detection: a generic Order Now link is not evidence."""
import re
from bs4 import BeautifulSoup


def classify(html, slug, provider='GreenCloud'):
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('#challenge-form, #cf-challenge-running, .g-recaptcha'):
        return 'unknown'
    title = soup.title.get_text(' ', strip=True).lower() if soup.title else ''
    if any(marker in title for marker in ('just a moment', 'attention required', 'access denied')):
        return 'unknown'
    for node in soup.select('script, style, template, noscript, [hidden], [aria-hidden="true"]'):
        node.decompose()
    if provider == 'Kainode':
        return classify_kainode(soup)
    order = soup.select_one('#order-standard_cart')
    if order is None:
        return 'unknown'
    sold = any('out of stock' in el.get_text(' ', strip=True).lower()
               for el in order.select('.error-heading, .alert-danger'))
    form = order.select_one('form#frmConfigureProduct')
    # Standard WHMCS configuration form + matching product title + enabled submit.
    identity = any(re.sub(r'\s+', '', el.get_text()).lower() in
                   (slug, slug + 'dc2')
                   for el in order.select('.product-info h2, .product-info h3, .product-info h4'))
    button = form.select_one('#btnCompleteProductConfig') if form else None
    enabled = button is not None and not button.has_attr('disabled') and \
        button.get('aria-disabled') != 'true' and 'disabled' not in button.get('class', [])
    available = bool(form is not None and identity and enabled)
    if sold and available:
        return 'unknown'
    if sold:
        return 'unavailable'
    return 'available' if available else 'unknown'


def classify_kainode(soup):
    """Kainode product detail: explicit badge plus product-specific checkout link."""
    main = soup.select_one('main')
    if main is None or not any(h.get_text(' ', strip=True) == 'VPS Advanced' for h in main.select('h2')):
        return 'unknown'
    badges = [s.get_text(' ', strip=True).lower() for s in main.select('span')]
    sold = 'product vps advanced is out of stock' in badges
    checkout = '/products/vps-singapore/vps-advanced/checkout'
    links = [a for a in main.select('a[href]')
             if a['href'] in (checkout, 'https://portal.kainode.com' + checkout)
             and not a.has_attr('disabled') and a.get('aria-disabled') != 'true'
             and 'disabled' not in a.get('class', [])]
    available = 'in stock' in badges and bool(links)
    if sold and ('in stock' in badges or links):
        return 'unknown'
    if sold:
        return 'unavailable'
    return 'available' if available else 'unknown'
