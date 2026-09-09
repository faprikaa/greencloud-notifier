"""Environment configuration and the four requested products."""
import math
import os
from dataclasses import dataclass

BASE = 'https://greencloudvps.com/billing/store/budget-kvm-sale/'


@dataclass(frozen=True)
class Product:
    slug: str
    name: str
    provider: str = 'GreenCloud'
    custom_url: str = ''

    @property
    def url(self):
        return self.custom_url or BASE + self.slug


PRODUCTS = (
    Product('budgetkvmsgdc1-2', 'BudgetKVMSGDC1-2'),
    Product('budgetkvmsgdc1-3', 'BudgetKVMSGDC1-3'),
    Product('budgetkvmsg-3', 'BudgetKVMSG-3 DC2'),
    Product('budgetkvmsg-2', 'BudgetKVMSG-2 DC2'),
    Product('vps-advanced', 'VPS Advanced', 'Kainode',
            'https://portal.kainode.com/products/vps-singapore/vps-advanced'),
)


@dataclass(frozen=True)
class Config:
    token: str
    chat_id: str
    interval: float = 60

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
        chat = env.get('TELEGRAM_CHAT_ID', '').strip()
        if not token or not chat:
            raise ValueError('Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID terlebih dahulu.')
        try:
            interval = float(env.get('CHECK_INTERVAL_SECONDS', '60'))
        except ValueError:
            raise ValueError('CHECK_INTERVAL_SECONDS harus angka >= 30.') from None
        if not math.isfinite(interval) or interval < 30:
            raise ValueError('CHECK_INTERVAL_SECONDS harus angka finite >= 30.')
        return cls(token, chat, interval)
