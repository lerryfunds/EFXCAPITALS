import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.request import Request, urlopen

from django.utils import timezone

from .models import CryptoRate

COIN_IDS = {
    "USDT": "tether",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}
CACHE_MINUTES = 5
API_URL = "https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"


def _fetch_rates():
    """Fetch live USD prices from CoinGecko. Returns {SYMBOL: Decimal}."""
    ids = ",".join(COIN_IDS.values())
    request = Request(
        API_URL.format(ids=ids),
        headers={"Accept": "application/json", "User-Agent": "EFXCAPITALS/1.0"},
    )
    with urlopen(request, timeout=5) as response:
        data = json.load(response)

    id_to_symbol = {coin_id: symbol for symbol, coin_id in COIN_IDS.items()}
    result = {}
    for coin_id, quote in data.items():
        symbol = id_to_symbol.get(coin_id)
        if symbol and isinstance(quote, dict) and quote.get("usd"):
            result[symbol] = Decimal(str(quote["usd"]))
    return result


def get_rates(force=False):
    """Return {SYMBOL: Decimal | None} for all supported coins.

    Cached in the DB for CACHE_MINUTES. Falls back to the stored (possibly
    stale) rate when the API is unreachable, so pages never break.
    """
    cutoff = timezone.now() - timedelta(minutes=CACHE_MINUTES)
    stored = {rate.symbol: rate for rate in CryptoRate.objects.all()}

    fresh = (
        all(rate.updated >= cutoff for rate in stored.values())
        and set(COIN_IDS).issubset(stored.keys())
    )

    if force or not fresh:
        try:
            fetched = _fetch_rates()
        except Exception:
            fetched = {}
        if fetched:
            now = timezone.now()
            for symbol, price in fetched.items():
                CryptoRate.objects.update_or_create(
                    symbol=symbol,
                    defaults={"usd_price": price, "updated": now},
                )
            stored = {rate.symbol: rate for rate in CryptoRate.objects.all()}

    result = {
        symbol: (stored[symbol].usd_price if symbol in stored else None)
        for symbol in COIN_IDS
    }
    if result.get("USDT") is None:
        result["USDT"] = Decimal("1.00")
    return result


def convert(symbol, amount):
    """USD value of `amount` coins. Returns Decimal or None when no rate."""
    rate = get_rates().get(symbol)
    if rate is None:
        return None
    return (Decimal(amount) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_coin(symbol, usd_amount):
    """Coin quantity worth `usd_amount`. Returns Decimal or None when no rate."""
    rate = get_rates().get(symbol)
    if rate is None or rate == 0:
        return None
    return Decimal(usd_amount) / rate