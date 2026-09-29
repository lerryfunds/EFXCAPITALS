import re
from decimal import Decimal

DEFAULT_MIN_DEPOSIT = Decimal("1.00")
DEFAULT_MIN_WITHDRAW = Decimal("20.00")
LEGACY_PREFIX = "LEGACY:"

RAIL_CATALOG = {
    "USDT:TRC20": {
        "symbol": "USDT",
        "network": "TRC20",
        "label": "USDT (Tron)",
        "coin_id": "tether",
        "coin_decimals": 6,
        "address_re": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
        "txid_re": r"^[0-9a-fA-F]{64}$",
        "min_deposit": "1.00",
        "max_deposit": "9999999999999999.99",
        "min_withdraw": "20.00",
        "max_withdraw": "9999999999999999.99",
    },
    "USDT:BEP20": {
        "symbol": "USDT",
        "network": "BEP20",
        "label": "USDT (BNB Smart Chain)",
        "coin_id": "tether",
        "coin_decimals": 6,
        "address_re": r"^0x[0-9a-fA-F]{40}$",
        "txid_re": r"^0x[0-9a-fA-F]{64}$",
        "min_deposit": "1.00",
        "max_deposit": "9999999999999999.99",
        "min_withdraw": "20.00",
        "max_withdraw": "9999999999999999.99",
    },
    "BTC": {
        "symbol": "BTC",
        "network": "BITCOIN",
        "label": "Bitcoin",
        "coin_id": "bitcoin",
        "coin_decimals": 8,
        "address_re": r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$",
        "txid_re": r"^[1-9A-HJ-NP-Za-km-z]{32,64}$",
        "min_deposit": "5.00",
        "max_deposit": "9999999999999999.99",
        "min_withdraw": "20.00",
        "max_withdraw": "9999999999999999.99",
    },
    "ETH": {
        "symbol": "ETH",
        "network": "ERC20",
        "label": "Ethereum (ERC20)",
        "coin_id": "ethereum",
        "coin_decimals": 18,
        "address_re": r"^0x[0-9a-fA-F]{40}$",
        "txid_re": r"^0x[0-9a-fA-F]{64}$",
        "min_deposit": "5.00",
        "max_deposit": "9999999999999999.99",
        "min_withdraw": "20.00",
        "max_withdraw": "9999999999999999.99",
    },
    "SOL": {
        "symbol": "SOL",
        "network": "SOLANA",
        "label": "Solana",
        "coin_id": "solana",
        "coin_decimals": 9,
        "address_re": r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
        "txid_re": r"^[1-9A-HJ-NP-Za-km-z]{64,90}$",
        "min_deposit": "5.00",
        "max_deposit": "9999999999999999.99",
        "min_withdraw": "20.00",
        "max_withdraw": "9999999999999999.99",
    },
}

_COMPILED = {
    key: (re.compile(entry["address_re"]), re.compile(entry["txid_re"]))
    for key, entry in RAIL_CATALOG.items()
}


def catalog_entry(key):
    return RAIL_CATALOG.get((key or "").strip())


def valid_address(key, value):
    patterns = _COMPILED.get((key or "").strip())
    if patterns is None:
        return False
    return bool(patterns[0].match((value or "").strip()))


def valid_txid(key, value):
    patterns = _COMPILED.get((key or "").strip())
    if patterns is None:
        return False
    return bool(patterns[1].match((value or "").strip()))
