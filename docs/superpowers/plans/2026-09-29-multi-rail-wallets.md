# Multi-Rail Wallets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single global platform wallet type with independently toggled payment rails that each user selects per transaction, with per-network address/TXID validation and an on-chain reconcilable coin snapshot.

**Architecture:** A code-owned `RAIL_CATALOG` in a new `core/rails.py` is the single source of truth for *which* rails exist and how addresses/TXIDs are validated. A `PaymentRail` table seeded from that catalog holds only what the admin controls: active flag, receive address, per-rail limits, display order. `Deposit.rail` and `Withdrawal.rail` become foreign keys. `Account.preferred_rail` is a form pre-selection hint and never a gate.

**Tech Stack:** Python 3.14.3, Django 6.1.1, SQLite (local) / Postgres (prod via `dj_database_url`), Django templates, `decimal.Decimal`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-29-multi-rail-wallets-design.md` — read it alongside this plan; the plan argues from it and the spec carries the rationale.

## Global Constraints

- **No new dependencies.** `requirements.txt` is frozen: Django 6.1.1, gunicorn, whitenoise, python-dotenv, psycopg[binary], dj-database-url.
- **Money is `decimal.Decimal`, never `float`.** USD amounts quantize to `Decimal("0.01")` with `ROUND_HALF_UP`. Coin amounts quantize to the rail's `coin_decimals` with `ROUND_DOWN` — never round *up* a quantity the user must send.
- **`MAX_FINANCIAL_AMOUNT = Decimal("9999999999999999.99")`** is defined at `user_panel/views.py:15` and is the ceiling for every amount and every limit.
- **The USD ledger does not change.** `Account.balance`, `Transaction.amount`, investments, ROI, and referrals stay exactly as they are. A rail is a wire, not a balance denomination.
- **Test command:** `.venv/Scripts/python.exe manage.py test --keepdb` (full suite baseline: 75 tests, ~62s, all passing). Run single classes as `.venv/Scripts/python.exe manage.py test core.tests.RailCatalogTest --keepdb`.
- **Follow existing view style:** function-based views, `messages.error(request, ...)` then `redirect(...)` on every failure path, and re-validate mutable config inside a `transaction.atomic()` / `select_for_update()` block rather than trusting the pre-lock read.
- **No code comments** unless explicitly requested.
- **Migration numbering continues from `0029`.** New migrations are `0030` and `0031`.
- **Rails are never deleted.** The admin deactivates. FKs from `Deposit`/`Withdrawal` use `on_delete=PROTECT`.

## Review Focus

Five input classes the spec implies but no single flow's happy path exercises. Each line gets a test in the owning task, in that task's own step style.

1. **Admin disables every rail.** `enabled_rails()` returns `[]`. The deposit and withdraw pages must render a clear "no networks available" state, and a crafted POST must be rejected — never a `TypeError` on `None` or an `IndexError` on `rails[0]`. *(Tasks 5, 6)*
2. **CoinGecko is unreachable and the rail's symbol has no cached rate.** `coin_amount` returns `(None, None)`. The deposit must still succeed with `amount_coin=None` — a rate outage must never lock a user out of funding their account, and must never divide by `None`. *(Tasks 3, 5)*
3. **A rate far outside any sane band makes the coin amount fall below one quantum of the rail's decimals.** This is a *corrupt-rate* guard, not a small-amount guard: with 18 decimals and a realistic rate, no realistic USD amount rounds to zero ($0.10 at $3000/ETH is 0.0000333 ETH, comfortably representable). But a depegged stablecoin or a bad API response can produce a rate large enough that the coin amount quantizes to `0`. Recording a zero-coin deposit is meaningless for reconciliation, so it must be rejected with a message naming the minimum. Tests must use such an absurd rate at or above the rail's configured minimum, so the limit check cannot mask the assertion. *(Tasks 3, 5, 6)*
4. **A crafted POST submits a disabled or unknown rail key.** The dropdown only offers enabled rails, but POST data is attacker-controlled. A disabled rail must be rejected at submit time even though it was valid when the page was rendered. *(Tasks 5, 6)*
5. **A historical `LEGACY:<SYMBOL>` rail, whose key is absent from the catalog.** Every validator must return `False` rather than raising, and admin approval of a deposit on such a rail must still credit the balance. *(Tasks 2, 8)*

---

### Task 1: Rail catalog and pure validators

**Files:**
- Create: `core/rails.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: nothing. This task is self-contained and imports no Django models.
- Produces:
  - `RAIL_CATALOG: dict[str, dict]` — keys `USDT:TRC20`, `USDT:BEP20`, `BTC`, `ETH`, `SOL`. Each entry has `symbol`, `network`, `label`, `coin_id`, `coin_decimals`, `address_re`, `txid_re`, `min_deposit`, `max_deposit`, `min_withdraw`, `max_withdraw` (last four as `str`).
  - `catalog_entry(key: str) -> dict | None`
  - `valid_address(key: str, value: str) -> bool`
  - `valid_txid(key: str, value: str) -> bool`
  - `DEFAULT_MIN_DEPOSIT = Decimal("1.00")`
  - `DEFAULT_MIN_WITHDRAW = Decimal("20.00")`
  - `LEGACY_PREFIX = "LEGACY:"`

- [ ] **Step 1: Write the failing tests**

Append to `core/tests.py`. Add `from core.rails import (RAIL_CATALOG, catalog_entry, valid_address, valid_txid, DEFAULT_MIN_DEPOSIT, DEFAULT_MIN_WITHDRAW, LEGACY_PREFIX)`.

```python
class RailCatalogTest(TestCase):
    def test_catalog_contains_the_five_seeded_rails(self):
        self.assertEqual(
            set(RAIL_CATALOG),
            {"USDT:TRC20", "USDT:BEP20", "BTC", "ETH", "SOL"},
        )

    def test_every_entry_declares_the_fields_the_code_relies_on(self):
        for key, entry in RAIL_CATALOG.items():
            with self.subTest(rail=key):
                self.assertEqual(entry["symbol"], key.split(":")[0])
                self.assertTrue(entry["label"])
                self.assertTrue(entry["address_re"])
                self.assertTrue(entry["txid_re"])
                self.assertGreaterEqual(entry["coin_decimals"], 0)
                for field in ("min_deposit", "max_deposit", "min_withdraw", "max_withdraw"):
                    Decimal(entry[field])

    def test_catalog_entry_returns_none_for_an_unknown_key(self):
        self.assertIsNone(catalog_entry("DOGE:ERC20"))
        self.assertIsNone(catalog_entry(""))

    def test_legacy_key_has_no_catalog_entry(self):
        self.assertIsNone(catalog_entry(f"{LEGACY_PREFIX}TRON"))


class RailValidationTest(TestCase):
    def test_tron_accepts_a_34_char_base58_address(self):
        self.assertTrue(valid_address("USDT:TRC20", "T" + "1" * 33))

    def test_tron_rejects_a_33_char_address(self):
        self.assertFalse(valid_address("USDT:TRC20", "T" + "1" * 32))

    def test_bep20_rejects_a_tron_address(self):
        self.assertFalse(valid_address("USDT:BEP20", "T" + "1" * 33))

    def test_eth_accepts_a_lowercase_0x_address(self):
        self.assertTrue(valid_address("ETH", "0x" + "a" * 40))

    def test_btc_accepts_p2pkh_and_bech32(self):
        self.assertTrue(valid_address("BTC", "1" + "a" * 33))
        self.assertTrue(valid_address("BTC", "bc1q" + "a" * 38))

    def test_sol_address_length_bounds(self):
        self.assertFalse(valid_address("SOL", "1" * 31))
        self.assertTrue(valid_address("SOL", "1" * 32))
        self.assertFalse(valid_address("SOL", "1" * 45))

    def test_empty_address_is_never_valid(self):
        for key in RAIL_CATALOG:
            with self.subTest(rail=key):
                self.assertFalse(valid_address(key, ""))
                self.assertFalse(valid_address(key, "   "))

    def test_unknown_and_legacy_keys_never_validate(self):
        self.assertFalse(valid_address("DOGE:ERC20", "T" + "1" * 33))
        self.assertFalse(valid_address(f"{LEGACY_PREFIX}TRON", "T" + "1" * 33))
        self.assertFalse(valid_txid("DOGE:ERC20", "a" * 64))
        self.assertFalse(valid_txid(f"{LEGACY_PREFIX}TRON", "a" * 64))

    def test_txid_formats_are_rail_specific(self):
        self.assertTrue(valid_txid("USDT:TRC20", "a" * 64))
        self.assertFalse(valid_txid("USDT:TRC20", "0x" + "a" * 64))
        self.assertTrue(valid_txid("ETH", "0x" + "A" * 64))
        self.assertFalse(valid_txid("ETH", "a" * 64))
        self.assertTrue(valid_txid("BTC", "a" * 64))
        self.assertFalse(valid_txid("BTC", "0x" + "a" * 64))
        self.assertFalse(valid_txid("BTC", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"))
        self.assertTrue(valid_txid("SOL", "1" * 88))

    def test_validators_strip_surrounding_whitespace(self):
        self.assertTrue(valid_txid("ETH", "  0x" + "a" * 64 + "\n"))
        self.assertTrue(valid_address("ETH", " 0x" + "a" * 40 + " "))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RailCatalogTest core.tests.RailValidationTest --keepdb`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.rails'`

- [ ] **Step 3: Write the implementation**

Create `core/rails.py`. It imports only `re` and `decimal`; it must not import models, so the validators stay testable in isolation and cannot create an import cycle with `core/currency.py`.

```python
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
        "address_re": r"^(bc1[02-9ac-hj-np-z]{39,59}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$",
        "txid_re": r"^[0-9a-fA-F]{64}$",
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
        "txid_re": r"^[1-9A-HJ-NP-Za-km-z]{87,88}$",
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RailCatalogTest core.tests.RailValidationTest --keepdb`
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add core/rails.py core/tests.py
git commit -m "Add payment rail catalog and address/TXID validators"
```

---

### Task 2: `PaymentRail` model, seed migration, and backfill

**Files:**
- Modify: `core/models.py` (add `PaymentRail`; add `Account.preferred_rail`; add nullable `Deposit.rail`/`Withdrawal.rail`, `amount_coin`, `rate_used`)
- Create: `core/migrations/0030_payment_rail.py`
- Modify: `core/admin.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `RAIL_CATALOG`, `LEGACY_PREFIX` from Task 1.
- Produces:
  - `PaymentRail` model with fields `key` (unique, max 50), `symbol`, `network`, `label`, `is_active` (default `False`), `address` (blank), `min_deposit`/`max_deposit`/`min_withdraw`/`max_withdraw` (all `DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)`), `display_order` (default 0), `date_updated` (`auto_now`).
  - `PaymentRail.rails()` classmethod → `QuerySet` ordered by `display_order`, then `key`.
  - `PaymentRail.active_rails()` classmethod → same, filtered to `is_active=True`.
  - `Account.preferred_rail` — `ForeignKey(PaymentRail, null=True, blank=True, on_delete=SET_NULL, related_name="accounts")`.
  - `Deposit.rail` / `Withdrawal.rail` — `ForeignKey(PaymentRail, null=True, on_delete=PROTECT, related_name=...)`.
  - `Deposit.amount_coin` / `Withdrawal.amount_coin` — `DecimalField(max_digits=36, decimal_places=18, null=True, blank=True)`.
  - `Deposit.rate_used` / `Withdrawal.rate_used` — `DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)`.
  - Helper `core.models.legacy_rail_for_symbol(symbol)` used by migration `0031` and by tests.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests.py`. Add `PaymentRail` to the `core.models` import on line 10.

```python
class PaymentRailSeedTest(TestCase):
    def test_migration_seeds_one_row_per_catalog_key(self):
        self.assertEqual(PaymentRail.objects.count(), len(RAIL_CATALOG))
        for key, entry in RAIL_CATALOG.items():
            with self.subTest(rail=key):
                rail = PaymentRail.objects.get(key=key)
                self.assertEqual(rail.symbol, entry["symbol"])
                self.assertEqual(rail.network, entry["network"])
                self.assertEqual(rail.label, entry["label"])

    def test_seeded_rails_are_inactive_and_have_no_address(self):
        for rail in PaymentRail.objects.all():
            with self.subTest(rail=rail.key):
                self.assertFalse(rail.is_active)
                self.assertEqual(rail.address, "")

    def test_seeded_limits_are_null_so_the_catalog_defaults_apply(self):
        for rail in PaymentRail.objects.all():
            with self.subTest(rail=rail.key):
                self.assertIsNone(rail.min_deposit)
                self.assertIsNone(rail.max_deposit)
                self.assertIsNone(rail.min_withdraw)
                self.assertIsNone(rail.max_withdraw)

    def test_every_non_legacy_row_has_a_catalog_key(self):
        for rail in PaymentRail.objects.all():
            with self.subTest(rail=rail.key):
                if not rail.key.startswith(LEGACY_PREFIX):
                    self.assertIn(rail.key, RAIL_CATALOG)

    def test_rails_orders_by_display_order(self):
        self.assertEqual(
            list(PaymentRail.rails().values_list("key", flat=True)),
            ["USDT:TRC20", "USDT:BEP20", "BTC", "ETH", "SOL"],
        )

    def test_active_rails_filters_inactive(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=True)
        self.assertEqual(
            list(PaymentRail.active_rails().values_list("key", flat=True)),
            ["ETH"],
        )

    def test_str_is_the_label(self):
        self.assertEqual(str(PaymentRail.objects.get(key="USDT:TRC20")), "USDT (Tron)")

    def test_legacy_rail_is_never_active(self):
        legacy = legacy_rail_for_symbol("TRON")
        self.assertTrue(legacy.key.startswith(LEGACY_PREFIX))
        self.assertFalse(legacy.is_active)
        self.assertIsNone(catalog_entry(legacy.key))
        self.assertNotIn(legacy, PaymentRail.active_rails())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test core.tests.PaymentRailSeedTest --keepdb`
Expected: FAIL — `ImportError: cannot import name 'PaymentRail'`

- [ ] **Step 3: Add the model**

In `core/models.py`, add after the `PlatformSettings` class (after line 32):

```python
class PaymentRail(models.Model):
    key = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10)
    network = models.CharField(max_length=20)
    label = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)
    address = models.CharField(max_length=150, blank=True, default="")
    min_deposit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    max_deposit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    min_withdraw = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    max_withdraw = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    display_order = models.IntegerField(default=0)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "key"]
        verbose_name = "Payment rail"
        verbose_name_plural = "Payment rails"

    @classmethod
    def rails(cls):
        return cls.objects.all().order_by("display_order", "key")

    @classmethod
    def active_rails(cls):
        return cls.rails().filter(is_active=True)

    def __str__(self):
        return self.label or self.key


def legacy_rail_for_symbol(symbol):
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None
    key = f"{LEGACY_PREFIX}{normalized}"
    rail, _ = PaymentRail.objects.get_or_create(
        key=key,
        defaults={
            "symbol": normalized[:10],
            "network": "LEGACY",
            "label": f"{normalized} (retired network)",
            "is_active": False,
            "address": "",
            "display_order": 9999,
        },
    )
    return rail
```

Add to the imports at the top of `core/models.py`: `from .rails import LEGACY_PREFIX`.

Then add to `Account` (after line 43): `preferred_rail = models.ForeignKey(PaymentRail, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts")`.

Then add to `Deposit` (after line 104): `rail = models.ForeignKey(PaymentRail, null=True, on_delete=models.PROTECT, related_name="deposits")`, `amount_coin = models.DecimalField(max_digits=36, decimal_places=18, null=True, blank=True)`, `rate_used = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)`.

Add the same three fields to `Withdrawal` after line 115, with `related_name="withdrawals"`.

- [ ] **Step 4: Generate the migration**

Run: `.venv/Scripts/python.exe manage.py makemigrations core --name payment_rail`
Expected: creates `core/migrations/0030_payment_rail.py`.

- [ ] **Step 5: Add the seed data migration**

Append a data migration to `core/migrations/0030_payment_rail.py`, after the generated operations. It seeds one row per catalog entry with `is_active=False`, empty address, and all four limits `None`, assigning `display_order` from dict position:

```python
def seed_rails(apps, schema_editor):
    PaymentRail = apps.get_model("core", "PaymentRail")
    from core.rails import RAIL_CATALOG

    for order, (key, entry) in enumerate(RAIL_CATALOG.items()):
        PaymentRail.objects.update_or_create(
            key=key,
            defaults={
                "symbol": entry["symbol"],
                "network": entry["network"],
                "label": entry["label"],
                "is_active": False,
                "address": "",
                "min_deposit": None,
                "max_deposit": None,
                "min_withdraw": None,
                "max_withdraw": None,
                "display_order": order,
            },
        )
```

Wire it up as a second `migrations.RunPython` operation, forward-only (`migrations.RunPython.noop` for the reverse), and set `dependencies` to include `("core", "0029_alter_withdrawal_date_approved")` — `makemigrations` should produce this automatically.

- [ ] **Step 6: Register in the Django admin**

Replace `core/admin.py` with:

```python
from django.contrib import admin
from .models import PlatformSettings, PaymentRail
# Register your models here.

@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(PaymentRail)
class PaymentRailAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "is_active", "address", "date_updated")
    list_filter = ("is_active", "symbol")
    search_fields = ("key", "label", "address")
    readonly_fields = ("key", "symbol", "network", "display_order")
```

Rails are never deletable through `/dj-admin/`, so add `has_delete_permission` returning `False`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test core.tests.PaymentRailSeedTest --keepdb`
Expected: PASS, 8 tests. Then run the full suite: `.venv/Scripts/python.exe manage.py test --keepdb` — expected 83 passing, 0 failures. The additive migration must not break any existing test.

- [ ] **Step 8: Commit**

```bash
git add core/models.py core/migrations/0030_payment_rail.py core/admin.py core/tests.py
git commit -m "Add PaymentRail model with catalog seed and legacy backfill"
```

---

### Task 3: Rail resolution, limits, and coin conversion helpers

**Files:**
- Modify: `core/rails.py` (append model-aware helpers)
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `PaymentRail` (Task 2), `RAIL_CATALOG`, `catalog_entry`, `DEFAULT_MIN_DEPOSIT`, `DEFAULT_MIN_WITHDRAW` (Task 1), `get_rates` from `core/currency.py`.
- Produces (all in `core/rails.py`):
  - `resolve_rail(key, *, require_active=True) -> PaymentRail | None` — returns the row only when the key is in the catalog, the row exists, and (when `require_active`) `is_active` is set. Returns `None` for unknown, disabled, or missing rows, including `LEGACY:` keys.
  - `deposit_limits(rail) -> tuple[Decimal, Decimal]` — `(min, max)`. DB column wins; `None` column falls back to the catalog entry's string; a `LEGACY:` rail with no catalog entry falls back to `DEFAULT_MIN_DEPOSIT` and `MAX_FINANCIAL_AMOUNT`.
  - `withdraw_limits(rail) -> tuple[Decimal, Decimal]` — same shape, with `DEFAULT_MIN_WITHDRAW`.
  - `coin_amount(rail, usd_amount) -> tuple[Decimal | None, Decimal | None]` — `(coin_quantity, rate_used)`. Returns `(None, None)` when the symbol has no rate or the rate is zero. Quantizes with `ROUND_DOWN` to the rail's `coin_decimals`. May legitimately return a zero coin quantity — callers must reject that (Review Focus 3).
  - `MAX_FINANCIAL_AMOUNT = Decimal("9999999999999999.99")` — moved here from `user_panel/views.py:15`; that module imports it from here.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests.py`. Add `from core.rails import (resolve_rail, deposit_limits, withdraw_limits, coin_amount, MAX_FINANCIAL_AMOUNT)` and `from core.models import PaymentRail`.

```python
class RailResolutionTest(TestCase):
    def setUp(self):
        self.tron = PaymentRail.objects.get(key="USDT:TRC20")
        self.eth = PaymentRail.objects.get(key="ETH")
        PaymentRail.objects.filter(key="USDT:TRC20").update(is_active=True)

    def test_resolves_an_active_rail(self):
        self.assertEqual(resolve_rail("USDT:TRC20"), self.tron)

    def test_rejects_a_disabled_rail(self):
        self.assertIsNone(resolve_rail("ETH"))

    def test_can_resolve_a_disabled_rail_when_activity_is_not_required(self):
        self.assertEqual(resolve_rail("ETH", require_active=False), self.eth)

    def test_rejects_unknown_missing_and_legacy_keys(self):
        self.assertIsNone(resolve_rail("DOGE:ERC20"))
        self.assertIsNone(resolve_rail(""))
        self.assertIsNone(resolve_rail(None))
        self.assertIsNone(resolve_rail(f"{LEGACY_PREFIX}TRON"))

    def test_deposit_limits_fall_back_to_the_catalog_when_columns_are_null(self):
        low, high = deposit_limits(self.eth)
        self.assertEqual(low, Decimal("5.00"))
        self.assertEqual(high, MAX_FINANCIAL_AMOUNT)

    def test_deposit_limits_prefer_the_database_column(self):
        PaymentRail.objects.filter(key="ETH").update(min_deposit=Decimal("25.00"))
        low, _high = deposit_limits(PaymentRail.objects.get(key="ETH"))
        self.assertEqual(low, Decimal("25.00"))

    def test_withdraw_limits_default_to_twenty(self):
        low, high = withdraw_limits(self.eth)
        self.assertEqual(low, DEFAULT_MIN_WITHDRAW)
        self.assertEqual(high, MAX_FINANCIAL_AMOUNT)

    def test_legacy_rail_limits_use_module_defaults(self):
        low, high = deposit_limits(legacy_rail_for_symbol("TRON"))
        self.assertEqual(low, DEFAULT_MIN_DEPOSIT)
        self.assertEqual(high, MAX_FINANCIAL_AMOUNT)


class CoinAmountTest(TestCase):
    def setUp(self):
        self.eth = PaymentRail.objects.get(key="ETH")
        self.usdt = PaymentRail.objects.get(key="USDT:TRC20")

    def test_converts_and_rounds_down_to_the_rail_precision(self):
        with mock.patch("core.rails.get_rates", return_value={"ETH": Decimal("3000")}):
            coin, rate = coin_amount(self.eth, Decimal("100.00"))
        self.assertEqual(rate, Decimal("3000"))
        self.assertEqual(coin, Decimal("0.033333333333333333"))

    def test_rounds_down_rather_than_up(self):
        with mock.patch("core.rails.get_rates", return_value={"ETH": Decimal("3000")}):
            coin, _rate = coin_amount(self.eth, Decimal("100.01"))
        self.assertEqual(coin, Decimal("0.033336666666666666"))

    def test_returns_none_pair_when_the_rate_is_missing(self):
        with mock.patch("core.rails.get_rates", return_value={}):
            self.assertEqual(coin_amount(self.eth, Decimal("100.00")), (None, None))

    def test_returns_none_pair_when_the_rate_is_zero(self):
        with mock.patch("core.rails.get_rates", return_value={"ETH": Decimal("0")}):
            self.assertEqual(coin_amount(self.eth, Decimal("100.00")), (None, None))

    def test_legacy_rail_has_no_decimals_so_it_returns_none(self):
        with mock.patch("core.rails.get_rates", return_value={"TRON": Decimal("1")}):
            self.assertEqual(coin_amount(legacy_rail_for_symbol("TRON"), Decimal("10")), (None, None))

    def test_corrupt_rate_rounds_coin_amount_to_zero(self):
        with mock.patch("core.rails.get_rates", return_value={"ETH": Decimal("1e30")}):
            coin, rate = coin_amount(self.eth, Decimal("20"))
        self.assertEqual(coin, Decimal("0"))
        self.assertIsNotNone(rate)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RailResolutionTest core.tests.CoinAmountTest --keepdb`
Expected: FAIL — `ImportError: cannot import name 'resolve_rail'`

- [ ] **Step 3: Write the implementation**

Append to `core/rails.py`. Add `from .models import PaymentRail` and `from .currency import get_rates` at the top of the file, plus `ROUND_DOWN` to the existing `decimal` import.

```python
MAX_FINANCIAL_AMOUNT = Decimal("9999999999999999.99")


def resolve_rail(key, *, require_active=True):
    normalized = (key or "").strip()
    if not normalized or normalized not in RAIL_CATALOG:
        return None
    rails = PaymentRail.rails() if not require_active else PaymentRail.active_rails()
    return rails.filter(key=normalized).first()


def _limits(rail, min_column, max_column, default_min, catalog_fields):
    entry = RAIL_CATALOG.get(rail.key)
    catalog_min = Decimal(entry[catalog_fields[0]]) if entry else default_min
    catalog_max = Decimal(entry[catalog_fields[1]]) if entry else MAX_FINANCIAL_AMOUNT
    low = getattr(rail, min_column)
    high = getattr(rail, max_column)
    return (
        low if low is not None else catalog_min,
        high if high is not None else catalog_max,
    )


def deposit_limits(rail):
    return _limits(rail, "min_deposit", "max_deposit", DEFAULT_MIN_DEPOSIT,
                   ("min_deposit", "max_deposit"))


def withdraw_limits(rail):
    return _limits(rail, "min_withdraw", "max_withdraw", DEFAULT_MIN_WITHDRAW,
                   ("min_withdraw", "max_withdraw"))


def coin_amount(rail, usd_amount):
    entry = RAIL_CATALOG.get(rail.key)
    if entry is None:
        return None, None
    rate = get_rates().get(entry["symbol"])
    if rate is None or rate <= 0:
        return None, None
    quantum = Decimal(1).scaleb(-entry["coin_decimals"])
    coin = (Decimal(usd_amount) / rate).quantize(quantum, rounding=ROUND_DOWN)
    return coin, rate
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RailResolutionTest core.tests.CoinAmountTest --keepdb`
Expected: PASS, 15 tests.

- [ ] **Step 5: Point both view modules at the shared ceiling**

`MAX_FINANCIAL_AMOUNT` is currently defined twice — `user_panel/views.py:15` and `admin_panel/views.py:16` — with the same literal. Replace the `user_panel/views.py:15` definition with `from core.rails import MAX_FINANCIAL_AMOUNT`, and delete the `admin_panel/views.py:16` definition in favour of `from core.rails import MAX_FINANCIAL_AMOUNT, RAIL_CATALOG, valid_address`. `admin_panel` also defines `MAX_REFERRAL_REWARD` at `:17`, which is unrelated and stays.

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all 98 tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/rails.py user_panel/views.py core/tests.py
git commit -m "Add rail resolution, per-rail limits, and coin conversion helpers"
```

---

### Task 4: Admin per-rail settings

**Files:**
- Modify: `admin_panel/views.py:660-719` (`admin_settings`)
- Modify: `admin_panel/templates/admin-settings.html:36-52`
- Test: `admin_panel/tests.py`

**Interfaces:**
- Consumes: `PaymentRail.rails()` (Task 2), `valid_address`, `RAIL_CATALOG` (Task 1), `MAX_FINANCIAL_AMOUNT` (Task 3), `add_audit_log` (existing, `admin_panel/views.py:36`).
- Produces: POST protocol `rail-<key>-active`, `rail-<key>-address`, `rail-<key>-min-deposit`, `rail-<key>-max-deposit`, `rail-<key>-min-withdraw`, `rail-<key>-max-withdraw`, where `<key>` uses `-` in place of `:` in the form names (e.g. `rail-USDT:TRC20-active` is not a valid HTML `name`; use `rail-USDT-TRC20-active` and map back). Template context gains `rails` (all rails in display order) and `referral_reward_label` is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `admin_panel/tests.py`. Add `PaymentRail` to the `core.models` import on line 4 of that file.

```python
class AdminRailSettingsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="root", password="x", is_staff=True, is_superuser=True
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def post_rails(self, **overrides):
        data = {}
        for key in RAIL_CATALOG:
            slug = key.replace(":", "-")
            data[f"rail-{slug}-active"] = ""
            data[f"rail-{slug}-address"] = ""
            data[f"rail-{slug}-min-deposit"] = ""
            data[f"rail-{slug}-max-deposit"] = ""
            data[f"rail-{slug}-min-withdraw"] = ""
            data[f"rail-{slug}-max-withdraw"] = ""
        data["referral-reward"] = "25.00"
        data.update(overrides)
        return self.client.post("/admin-secure-portal/settings/", data)

    def test_saves_an_enabled_rail_with_a_valid_address(self):
        self.post_rails(**{
            "rail-USDT-TRC20-active": "on",
            "rail-USDT-TRC20-address": "T" + "1" * 33,
        })
        rail = PaymentRail.objects.get(key="USDT:TRC20")
        self.assertTrue(rail.is_active)
        self.assertEqual(rail.address, "T" + "1" * 33)

    def test_enabling_a_rail_without_an_address_is_rejected(self):
        self.post_rails(**{"rail-USDT-TRC20-active": "on"})
        self.assertFalse(PaymentRail.objects.get(key="USDT:TRC20").is_active)

    def test_enabling_a_rail_with_a_mismatched_address_is_rejected(self):
        self.post_rails(**{
            "rail-USDT-TRC20-active": "on",
            "rail-USDT-TRC20-address": "0x" + "a" * 40,
        })
        self.assertFalse(PaymentRail.objects.get(key="USDT:TRC20").is_active)

    def test_address_is_validated_against_the_rails_own_pattern(self):
        self.post_rails(**{
            "rail-ETH-active": "on",
            "rail-ETH-address": "0x" + "a" * 40,
        })
        self.assertTrue(PaymentRail.objects.get(key="ETH").is_active)

    def test_a_disabled_rail_keeps_its_stored_address(self):
        PaymentRail.objects.filter(key="ETH").update(address="0x" + "a" * 40, is_active=True)
        self.post_rails()
        rail = PaymentRail.objects.get(key="ETH")
        self.assertFalse(rail.is_active)
        self.assertEqual(rail.address, "0x" + "a" * 40)

    def test_saves_per_rail_limits(self):
        self.post_rails(**{
            "rail-BTC-active": "on",
            "rail-BTC-address": "1" * 34,
            "rail-BTC-min-deposit": "50.00",
            "rail-BTC-max-withdraw": "5000.00",
        })
        rail = PaymentRail.objects.get(key="BTC")
        self.assertEqual(rail.min_deposit, Decimal("50.00"))
        self.assertEqual(rail.max_withdraw, Decimal("5000.00"))

    def test_blank_limits_are_stored_as_null(self):
        self.post_rails(**{
            "rail-BTC-active": "on",
            "rail-BTC-address": "1" * 34,
        })
        self.assertIsNone(PaymentRail.objects.get(key="BTC").min_deposit)

    def test_min_greater_than_max_is_rejected(self):
        self.post_rails(**{
            "rail-BTC-active": "on",
            "rail-BTC-address": "1" * 34,
            "rail-BTC-min-deposit": "100.00",
            "rail-BTC-max-deposit": "10.00",
        })
        self.assertIsNone(PaymentRail.objects.get(key="BTC").min_deposit)

    def test_negative_limit_is_rejected(self):
        self.post_rails(**{
            "rail-BTC-active": "on",
            "rail-BTC-address": "1" * 34,
            "rail-BTC-min-deposit": "-5.00",
        })
        self.assertIsNone(PaymentRail.objects.get(key="BTC").min_deposit)

    def test_limit_above_ceiling_is_rejected(self):
        self.post_rails(**{
            "rail-BTC-active": "on",
            "rail-BTC-address": "1" * 34,
            "rail-BTC-max-deposit": "99999999999999999999.00",
        })
        self.assertIsNone(PaymentRail.objects.get(key="BTC").max_deposit)

    def test_unknown_rail_fields_in_the_post_are_ignored(self):
        self.post_rails(**{
            "rail-DOGE-ERC20-active": "on",
            "rail-DOGE-ERC20-address": "0x" + "a" * 40,
        })
        self.assertFalse(PaymentRail.objects.filter(key__startswith="DOGE").exists())

    def test_referral_reward_still_saves_alongside_rails(self):
        self.post_rails(**{
            "referral-reward": "40.00",
            "rail-USDT-TRC20-active": "on",
            "rail-USDT-TRC20-address": "T" + "1" * 33,
        })
        self.assertEqual(PlatformSettings.load().referral_reward, Decimal("40.00"))

    def test_legacy_rail_rows_are_listed_but_cannot_be_enabled(self):
        legacy = legacy_rail_for_symbol("TRON")
        r = self.client.get("/admin-secure-portal/settings/")
        self.assertContains(r, "TRON (retired network)")
        self.assertContains(r, f'value="{legacy.key}"')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test admin_panel.tests.AdminRailSettingsTest --keepdb`
Expected: FAIL — assertions fail because `admin_settings` still handles the single `wallet-type` select and ignores the new fields.

- [ ] **Step 3: Rewrite the view**

Replace the body of `admin_settings` in `admin_panel/views.py:660-719` with:

```python
def admin_settings(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    platform = PlatformSettings.load()

    if request.method == "POST":
        form = request.POST
        raw_reward = form.get("referral-reward", "").strip()

        try:
            reward = Decimal(raw_reward).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid referral reward")
            return redirect("admin_settings")
        if (
            not reward.is_finite()
            or reward < 0
            or reward > MAX_REFERRAL_REWARD
        ):
            messages.error(request, "Enter a valid referral reward")
            return redirect("admin_settings")

        updates = []
        for rail in PaymentRail.rails():
            slug = rail.key.replace(":", "-")
            active = bool(form.get(f"rail-{slug}-active", "").strip())
            address = form.get(f"rail-{slug}-address", "").strip()
            limits = {}
            for field, column in (
                ("min-deposit", "min_deposit"),
                ("max-deposit", "max_deposit"),
                ("min-withdraw", "min_withdraw"),
                ("max-withdraw", "max_withdraw"),
            ):
                raw = form.get(f"rail-{slug}-{field}", "").strip()
                if not raw:
                    limits[column] = None
                    continue
                try:
                    value = Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                except (InvalidOperation, ValueError):
                    messages.error(request, f"Enter a valid {field.replace('-', ' ')} for {rail.label}")
                    return redirect("admin_settings")
                if not value.is_finite() or value < 0 or value > MAX_FINANCIAL_AMOUNT:
                    messages.error(request, f"Enter a valid {field.replace('-', ' ')} for {rail.label}")
                    return redirect("admin_settings")
                limits[column] = value

            if limits["min_deposit"] is not None and limits["max_deposit"] is not None:
                if limits["min_deposit"] > limits["max_deposit"]:
                    messages.error(request, f"Minimum deposit is above the maximum for {rail.label}")
                    return redirect("admin_settings")
            if limits["min_withdraw"] is not None and limits["max_withdraw"] is not None:
                if limits["min_withdraw"] > limits["max_withdraw"]:
                    messages.error(request, f"Minimum withdrawal is above the maximum for {rail.label}")
                    return redirect("admin_settings")

            if rail.key not in RAIL_CATALOG:
                active = False
                address = rail.address
            if active and not address:
                messages.error(request, f"Enter a receive address for {rail.label} or disable it")
                return redirect("admin_settings")
            if active and not valid_address(rail.key, address):
                messages.error(request, f"{address} is not a valid {rail.label} address")
                return redirect("admin_settings")
            if len(address) > 150:
                messages.error(request, f"The receive address for {rail.label} is too long")
                return redirect("admin_settings")

            updates.append((rail, active, address, limits))

        with transaction.atomic():
            for rail, active, address, limits in updates:
                rail.is_active = active
                rail.address = address
                for column, value in limits.items():
                    setattr(rail, column, value)
                rail.save(update_fields=[
                    "is_active", "address",
                    "min_deposit", "max_deposit", "min_withdraw", "max_withdraw",
                    "date_updated",
                ])
            locked = PlatformSettings.objects.select_for_update().get(pk=1)
            locked.referral_reward = reward
            locked.save(update_fields=["referral_reward", "date_updated"])
            active_labels = ", ".join(rail.label for rail, active, _a, _l in updates if active) or "none"
            add_audit_log(request, "Updated platform settings", f"Active rails: {active_labels}, referral reward ${reward}")
        messages.success(request, "Platform settings saved")
        return redirect("admin_settings")

    context = {
        "platform" : platform,
        "rails" : PaymentRail.rails(),
    }

    return render(request, "admin-settings.html", context)
```

Add `from core.rails import RAIL_CATALOG, valid_address` and `from core.models import PaymentRail, legacy_rail_for_symbol` to the imports at the top of `admin_panel/views.py`. `MAX_FINANCIAL_AMOUNT` is already imported from `core.rails` by Task 3, so do not re-declare it.

- [ ] **Step 4: Rewrite the settings template**

In `admin_panel/templates/admin-settings.html`, replace lines 36-52 (the whole `Deposit Wallet` section) with:

```html
      <h3 class="form-section-title">Payment Rails</h3>
      <p class="muted" style="margin:0 0 14px">Enable the networks users can deposit and withdraw on. Every enabled rail needs a valid receive address.</p>
      {% for rail in rails %}
        {% with slug=rail.key|replace:":","-" %}
        <div class="rail-card">
          <div class="rail-head">
            <label class="rail-toggle">
              <input type="checkbox" name="rail-{{ slug }}-active" {% if rail.is_active %}checked{% endif %}>
              <span>{{ rail.label }}</span>
            </label>
            <code class="rail-key">{{ rail.key }}</code>
          </div>
          <div class="form-grid">
            <div class="field full">
              <label for="addr-{{ slug }}">Receive address ({{ rail.network }})</label>
              <input id="addr-{{ slug }}" type="text" maxlength="150" name="rail-{{ slug }}-address" value="{{ rail.address }}">
            </div>
            <div class="field">
              <label for="mind-{{ slug }}">Min deposit ($)</label>
              <input id="mind-{{ slug }}" type="number" min="0" step="0.01" name="rail-{{ slug }}-min-deposit" value="{% if rail.min_deposit is not None %}{{ rail.min_deposit }}{% endif %}">
            </div>
            <div class="field">
              <label for="maxd-{{ slug }}">Max deposit ($)</label>
              <input id="maxd-{{ slug }}" type="number" min="0" step="0.01" name="rail-{{ slug }}-max-deposit" value="{% if rail.max_deposit is not None %}{{ rail.max_deposit }}{% endif %}">
            </div>
            <div class="field">
              <label for="minw-{{ slug }}">Min withdrawal ($)</label>
              <input id="minw-{{ slug }}" type="number" min="0" step="0.01" name="rail-{{ slug }}-min-withdraw" value="{% if rail.min_withdraw is not None %}{{ rail.min_withdraw }}{% endif %}">
            </div>
            <div class="field">
              <label for="maxw-{{ slug }}">Max withdrawal ($)</label>
              <input id="maxw-{{ slug }}" type="number" min="0" step="0.01" name="rail-{{ slug }}-max-withdraw" value="{% if rail.max_withdraw is not None %}{{ rail.max_withdraw }}{% endif %}">
            </div>
          </div>
        </div>
        {% endwith %}
      {% endfor %}
```

Also change line 57's label from `Referral Reward (USDT)` to `Referral Reward ($)`.

Add the supporting CSS to `admin_panel/static/css/app.css`:

```css
.rail-card{border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
.rail-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.rail-toggle{display:flex;align-items:center;gap:8px;font-weight:600;cursor:pointer}
.rail-key{font-size:12px;color:var(--muted)}
.muted{color:var(--muted);font-size:13px}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test admin_panel.tests.AdminRailSettingsTest --keepdb`
Expected: PASS, 13 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all pass. `AdminSettingsTest` at `admin_panel/tests.py:479-524` will fail here — that test is **deleted** in Task 10, so re-point it now by removing the two wallet-type assertions, or expect the failure and fix it in Task 10. Prefer fixing it now: delete the `test_changing_wallet_type_is_blocked` method and the wallet-type assertions from `test_settings_update_saves_values`.

- [ ] **Step 7: Commit**

```bash
git add admin_panel/views.py admin_panel/templates/admin-settings.html admin_panel/static/css/app.css admin_panel/tests.py
git commit -m "Replace single wallet type with per-rail admin configuration"
```

---

### Task 5: User deposit flow

**Files:**
- Modify: `user_panel/views.py:330-425` (`deposit`)
- Modify: `user_panel/templates/deposit.html:35-81, 110-145`
- Test: `user_panel/tests.py`

**Interfaces:**
- Consumes: `resolve_rail`, `valid_txid`, `deposit_limits`, `coin_amount` (Tasks 1, 3), `PaymentRail.active_rails` (Task 2).
- Produces: GET context gains `rails` (list), `selected_rail` (`PaymentRail` or `None`), `rail_addresses` (dict `key -> address`), `selected_rail_key` (str). POST field `rail` replaces `wallet_type`. `Deposit.amount` is still `amount` at this stage (renamed in Task 10).

- [ ] **Step 1: Write the failing tests**

Append to `user_panel/tests.py`. Add `PaymentRail` to the `core.models` import on line 4, and `from core.rails import LEGACY_PREFIX` at the top.

```python
class DepositRailTest(TestCase):
    def setUp(self):
        now = timezone.now()
        for sym, price in [("USDT", "1.00"), ("ETH", "3000")]:
            CryptoRate.objects.update_or_create(symbol=sym, defaults={"usd_price": Decimal(price), "updated": now})
        self.user = User.objects.create_user(username="depositor", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.client = Client()
        self.client.force_login(self.user)
        self.tron = PaymentRail.objects.get(key="USDT:TRC20")
        self.eth = PaymentRail.objects.get(key="ETH")
        PaymentRail.objects.filter(key="USDT:TRC20").update(is_active=True, address="T" + "1" * 33)
        PaymentRail.objects.filter(key="ETH").update(is_active=True, address="0x" + "a" * 40)

    def post_deposit(self, **overrides):
        data = {
            "rail": "USDT:TRC20",
            "amount": "200.00",
            "tx_hash": "a" * 64,
        }
        data.update(overrides)
        return self.client.post("/dashboard/deposit/", data)

    def test_deposit_page_offers_every_active_rail(self):
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            [rail.key for rail in r.context["rails"]],
            ["USDT:TRC20", "ETH"],
        )
        self.assertEqual(r.context["selected_rail_key"], "USDT:TRC20")

    def test_deposit_page_omits_disabled_rails(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=False)
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual([rail.key for rail in r.context["rails"]], ["USDT:TRC20"])

    def test_deposit_page_passes_an_address_per_rail(self):
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.context["rail_addresses"]["ETH"], "0x" + "a" * 40)

    def test_creates_a_pending_deposit_on_the_chosen_rail(self):
        self.post_deposit()
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.rail, self.tron)
        self.assertEqual(deposit.amount, Decimal("200.00"))
        self.assertEqual(deposit.status, "PENDING")
        self.assertEqual(
            Transaction.objects.get(tx_type="DEPOSIT").amount, Decimal("200.00")
        )

    def test_stores_the_coin_snapshot_and_rate(self):
        self.post_deposit()
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.amount_coin, Decimal("200.000000"))
        self.assertEqual(deposit.rate_used, Decimal("1.00000000"))

    def test_remembers_the_rail_as_the_account_preference(self):
        self.post_deposit(rail="ETH", tx_hash="0x" + "b" * 64)
        self.account.refresh_from_db()
        self.assertEqual(self.account.preferred_rail, self.eth)

    def test_rejects_a_disabled_rail_submitted_directly(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=False)
        self.post_deposit(rail="ETH", tx_hash="0x" + "b" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_rejects_an_unknown_rail_key(self):
        self.post_deposit(rail="DOGE:ERC20")
        self.assertEqual(Deposit.objects.count(), 0)

    def test_rejects_a_legacy_rail_key(self):
        self.post_deposit(rail=f"{LEGACY_PREFIX}TRON")
        self.assertEqual(Deposit.objects.count(), 0)

    def test_rejects_an_empty_rail_key(self):
        self.post_deposit(rail="")
        self.assertEqual(Deposit.objects.count(), 0)

    def test_txid_is_validated_against_the_selected_rail(self):
        self.post_deposit(rail="USDT:TRC20", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_accepts_a_rail_specific_txid(self):
        self.post_deposit(rail="ETH", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.get().rail, self.eth)

    def test_rejects_a_rail_with_no_configured_address(self):
        PaymentRail.objects.filter(key="ETH").update(address="")
        self.post_deposit(rail="ETH", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_enforces_the_rails_minimum_deposit(self):
        PaymentRail.objects.filter(key="ETH").update(min_deposit=Decimal("50.00"))
        self.post_deposit(rail="ETH", amount="10.00", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_enforces_the_rails_maximum_deposit(self):
        PaymentRail.objects.filter(key="ETH").update(max_deposit=Decimal("100.00"))
        self.post_deposit(rail="ETH", amount="500.00", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_deposit_succeeds_with_no_coin_snapshot_when_the_rate_is_missing(self):
        with mock.patch("core.rails.get_rates", return_value={}):
            self.post_deposit(rail="ETH", tx_hash="0x" + "c" * 64)
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.amount, Decimal("200.00"))
        self.assertIsNone(deposit.amount_coin)
        self.assertIsNone(deposit.rate_used)

    def test_rejects_an_amount_that_rounds_to_zero_coins_on_eth(self):
        with mock.patch("core.rails.get_rates", return_value={"ETH": Decimal("1e30")}):
            self.post_deposit(rail="ETH", amount="5.00", tx_hash="0x" + "c" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_rejects_an_amount_that_rounds_to_zero_coins_on_a_stablecoin(self):
        with mock.patch("core.rails.get_rates", return_value={"USDT": Decimal("1e12")}):
            self.post_deposit(amount="10.00", tx_hash="d" * 64)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_tx_hash_key_is_namespaced_per_rail(self):
        self.post_deposit(rail="USDT:TRC20", tx_hash="e" * 64)
        self.post_deposit(rail="ETH", tx_hash="0x" + "e" * 64)
        keys = set(Deposit.objects.values_list("tx_hash_key", flat=True))
        self.assertEqual(len(keys), 2)
        self.assertIn("USDT:TRC20:" + "e" * 64, keys)
        self.assertIn("ETH:0x" + "e" * 64, keys)

    def test_a_repeated_txid_on_the_same_rail_is_still_rejected(self):
        self.post_deposit(tx_hash="f" * 64)
        self.post_deposit(tx_hash="f" * 64)
        self.assertEqual(Deposit.objects.count(), 1)

    def test_disabling_every_rail_renders_a_message_instead_of_crashing(self):
        PaymentRail.objects.update(is_active=False)
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["selected_rail"])
        self.assertEqual(list(r.context["rails"]), [])

    def test_disabling_every_rail_rejects_a_crafted_post(self):
        PaymentRail.objects.update(is_active=False)
        self.post_deposit()
        self.assertEqual(Deposit.objects.count(), 0)

    def test_prefers_the_account_preference_when_the_rail_is_still_active(self):
        self.account.preferred_rail = self.eth
        self.account.save(update_fields=["preferred_rail"])
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.context["selected_rail"], self.eth)

    def test_falls_back_to_the_first_rail_when_the_preference_was_disabled(self):
        self.account.preferred_rail = PaymentRail.objects.get(key="SOL")
        self.account.save(update_fields=["preferred_rail"])
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.context["selected_rail"], self.tron)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.DepositRailTest --keepdb`
Expected: FAIL — `deposit` still reads `wallet_type` and rejects the new `rail` field.

- [ ] **Step 3: Rewrite the deposit view**

Replace `user_panel/views.py:330-425` with:

```python
@active_login_required
def deposit(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    if request.method == "POST":
        form = request.POST

        rail_key = form.get("rail", "").strip()
        tx_hash = normalized_tx_hash(form.get("tx_hash", ""))
        raw_amount = form.get("amount", "").strip()

        rail = resolve_rail(rail_key)
        if rail is None:
            messages.error(request, "That network is no longer available, please choose another")
            return redirect("deposit")
        if not rail.address.strip():
            messages.error(request, f"Deposits on {rail.label} are temporarily unavailable")
            return redirect("deposit")
        if not valid_txid(rail.key, tx_hash):
            messages.error(request, f"Enter a valid {rail.network} transaction hash")
            return redirect("deposit")

        try:
            amount = Decimal(raw_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid deposit amount")
            return redirect("deposit")

        min_deposit, max_deposit = deposit_limits(rail)
        if not amount.is_finite() or amount < min_deposit or amount > max_deposit:
            messages.error(request, f"Enter a deposit amount between ${min_deposit} and ${max_deposit}")
            return redirect("deposit")

        amount_coin, rate_used = coin_amount(rail, amount)
        if amount_coin == 0:
            messages.error(request, f"${amount} is too small to send as {rail.symbol}, try a larger amount")
            return redirect("deposit")

        try:
            with transaction.atomic():
                locked_rail = PaymentRail.objects.select_for_update().get(pk=rail.pk)
                if not locked_rail.is_active or not locked_rail.address.strip():
                    messages.error(request, "That network is no longer available, please choose another")
                    return redirect("deposit")
                locked_user = User.objects.select_for_update().get(pk=request.user.pk)
                locked_account = Account.objects.select_for_update().get(
                    pk=account.pk,
                    user=locked_user,
                )
                deposit = Deposit.objects.create(
                    user=locked_user,
                    amount=amount,
                    amount_coin=amount_coin,
                    rate_used=rate_used,
                    rail=locked_rail,
                    tx_hash=tx_hash,
                    tx_hash_key=f"{locked_rail.key}:{tx_hash}",
                )
                Transaction.objects.create(
                    user=locked_user,
                    tx_type="DEPOSIT",
                    amount=amount,
                    status="PENDING",
                    related_id=deposit.id,
                    description=f"{locked_rail.label} deposit of ${amount}",
                )
                if locked_account.preferred_rail_id != locked_rail.pk:
                    locked_account.preferred_rail = locked_rail
                    locked_account.save(update_fields=["preferred_rail"])
        except IntegrityError:
            messages.error(request, "This transaction has already been submitted")
            return redirect("deposit")

        if amount_coin is None:
            messages.warning(request, "Deposit submitted, but a live rate was unavailable so no coin amount was recorded.")
        else:
            messages.success(request, f"Deposit submitted, send {amount_coin} {rail.symbol} on {rail.network}. Admin will credit your wallet after verification.")
        return redirect("deposit")

    rails = list(PaymentRail.active_rails())
    selected_rail = None
    if rails:
        selected_rail = next(
            (candidate for candidate in rails if candidate.pk == account.preferred_rail_id),
            rails[0],
        )

    prices = get_rates()
    rail_addresses = {candidate.key: candidate.address for candidate in rails}
    context = {
        "account" : account,
        "rails" : rails,
        "selected_rail" : selected_rail,
        "selected_rail_key" : selected_rail.key if selected_rail else "",
        "rail_addresses" : rail_addresses,
        "rail_addresses_json" : json.dumps(rail_addresses),
        "deposits" : Deposit.objects.filter(user = request.user).order_by("-date_requested")[:10],
        "prices" : prices,
        "prices_json" : prices_json(prices),
    }

    return render(request, "deposit.html", context)
```

Add `from core.rails import resolve_rail, valid_txid, deposit_limits, coin_amount` to the imports in `user_panel/views.py`.

`tx_hash_key` becomes the composite `f"{rail_key}:{tx_hash}"`. This is what makes duplicate detection per-rail: the same hash on two rails produces two distinct keys, so the existing column-level `unique=True` constraint already does its job per rail. Task 10 additionally declares `unique_together = [("rail", "tx_hash_key")]` and asserts it; that second constraint is redundant with the namespaced key rather than conflicting with it, and both are kept.

- [ ] **Step 4: Rewrite the deposit template**

In `user_panel/templates/deposit.html`, replace lines 35-81 with:

```html
    <div class="info-box">
      <h3>How to deposit</h3>
      {% if rails %}
      <ol>
        <li>Choose the network you'll send on.</li>
        <li>Send the exact amount shown below to that network's address.</li>
        <li>Paste the transaction hash (TXID) in the form and submit.</li>
        <li>Admin reviews and your balance is credited once approved.</li>
      </ol>
      <div class="field">
        <label for="network">Network</label>
        <select id="network" name="rail">
          {% for candidate in rails %}
            <option value="{{ candidate.key }}" data-symbol="{{ candidate.symbol }}" {% if candidate.key == selected_rail_key %}selected{% endif %}>{{ candidate.label }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="address-copy">
        <address id="deposit-address">{% if selected_rail %}{{ selected_rail.address }}{% endif %}</address>
        {% if selected_rail %}
          <button class="copy-btn" onclick="copyAddress(this)">Copy</button>
        {% endif %}
      </div>
      {% else %}
        <p>No deposit networks are available right now. Please contact support.</p>
      {% endif %}
    </div>

    {% if rails %}
    <form class="panel" style="display:flex;flex-direction:column;gap:18px" method="post">
      {% csrf_token %}
      <div class="form-grid">
        <div class="field">
          <label for="amount">Amount ($)</label>
          <div class="input-icon">
            <span class="in-sym">$</span>
            <input id="amount" type="number" placeholder="100.00" min="1" step="0.01" required name="amount">
          </div>
          <small id="coinHint" class="muted">You must send <b>—</b> to the address above.</small>
        </div>
        <div class="field full">
          <label for="txhash">Transaction Hash (TXID)</label>
          <input id="txhash" type="text" placeholder="Paste the blockchain transaction ID" required name="tx_hash">
        </div>
      </div>
      <div class="warn">
          <span class="w-icon">!</span>
        <span>Only send on the selected network to the address above. Sending on the wrong network may result in loss of funds. Deposits are credited after admin verification.</span>
      </div>
      <button type="submit" class="btn btn-gold btn-block">Submit Deposit</button>
    </form>
    {% endif %}
```

Replace the `recent deposits` table header (line 90) `<tr><th>Date</th><th>Amount</th><th>Network</th><th>Status</th></tr>` and the network cell at line 97 with `{{ d.rail.label }}`, and add a coin-amount cell: `<td>{{ d.amount_coin|default_if_none:"—" }}</td>` with a matching `<th>Coin</th>`.

Replace the two `<script>` blocks at lines 110-145 with:

```html
<script>
window.CRYPTORATES = {{ prices_json|safe }};
window.RAILADDRESSES = {{ rail_addresses_json|safe }};
function copyAddress(btn){
  navigator.clipboard.writeText(document.getElementById('deposit-address').textContent.trim()).then(()=>{
    const t = btn.textContent;
    btn.textContent = 'Copied ✓';
    setTimeout(()=>btn.textContent = t, 1600);
  });
}
</script>
<script>
(function(){
  const rates = window.CRYPTORATES || {};
  const addresses = window.RAILADDRESSES || {};
  const net = document.getElementById('network');
  const amt = document.getElementById('amount');
  const hint = document.getElementById('coinHint');
  const addr = document.getElementById('deposit-address');
  if(!net) return;
  function paint(){
    const opt = net.options[net.selectedIndex];
    const symbol = (opt && opt.dataset.symbol || '').toUpperCase();
    const rate = rates[symbol];
    const value = parseFloat(amt.value);
    if(addr) addr.textContent = addresses[net.value] || '';
    if(!hint) return;
    if(rate && value > 0){
      const coin = (value / rate).toLocaleString('en-US',{maximumFractionDigits:8});
      hint.innerHTML = 'You must send <b>' + coin + ' ' + symbol + '</b> to the address above.';
    } else if(rate && symbol === 'USDT'){
      hint.innerHTML = 'You must send <b>' + value.toFixed(2) + ' USDT</b> to the address above.';
    } else {
      hint.textContent = 'Live rate unavailable for this network.';
    }
  }
  net.addEventListener('change', paint);
  amt.addEventListener('input', paint);
  paint();
})();
</script>
```

`json` is already imported at `user_panel/views.py:12` and `PaymentRail` is added to the `core.models` import on line 4.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.DepositRailTest --keepdb`
Expected: PASS, 26 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: failures remain in `DepositTest` / `DepositValidationTest` at `user_panel/tests.py:190-318`, which still POST `wallet_type` and set `PlatformSettings.wallet_address`. Re-point their `setUp` to activate a rail and their POSTs to send `rail`, and **delete** `test_account_wallet_type_mismatch_blocks_deposit` (`:257-271`) since that gate no longer exists.

- [ ] **Step 7: Commit**

```bash
git add user_panel/views.py user_panel/templates/deposit.html user_panel/tests.py
git commit -m "Support per-transaction rail selection and coin snapshot on deposit"
```

---

### Task 6: User withdraw flow

**Files:**
- Modify: `user_panel/views.py:63-151` (`withdraw`)
- Modify: `user_panel/templates/withdraw.html:36-76, 82-104`
- Test: `user_panel/tests.py`

**Interfaces:**
- Consumes: `resolve_rail`, `valid_address`, `withdraw_limits`, `coin_amount` (Tasks 1, 3), `PaymentRail.active_rails` (Task 2).
- Produces: GET context gains `rails`, `selected_rail`, `selected_rail_key`, `rail_addresses`. POST field `rail` replaces `wallet_type`.

- [ ] **Step 1: Write the failing tests**

Append to `user_panel/tests.py`:

```python
class WithdrawRailTest(TestCase):
    def setUp(self):
        now = timezone.now()
        for sym, price in [("USDT", "1.00"), ("ETH", "3000")]:
            CryptoRate.objects.update_or_create(symbol=sym, defaults={"usd_price": Decimal(price), "updated": now})
        self.user = User.objects.create_user(username="withdrawer", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("1000.00"))
        self.client = Client()
        self.client.force_login(self.user)
        self.tron = PaymentRail.objects.get(key="USDT:TRC20")
        self.eth = PaymentRail.objects.get(key="ETH")
        PaymentRail.objects.filter(key="USDT:TRC20").update(is_active=True)
        PaymentRail.objects.filter(key="ETH").update(is_active=True)

    def post_withdraw(self, **overrides):
        data = {
            "rail": "USDT:TRC20",
            "amount": "100.00",
            "address": "T" + "2" * 33,
        }
        data.update(overrides)
        return self.client.post("/dashboard/withdraw/", data)

    def test_withdraw_page_offers_every_active_rail(self):
        r = self.client.get("/dashboard/withdraw/")
        self.assertEqual([rail.key for rail in r.context["rails"]], ["USDT:TRC20", "ETH"])

    def test_creates_a_pending_withdrawal_on_the_chosen_rail(self):
        self.post_withdraw()
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.rail, self.tron)
        self.assertEqual(withdrawal.address, "T" + "2" * 33)
        self.assertEqual(withdrawal.status, "PENDING")
        self.assertEqual(
            Transaction.objects.get(tx_type="WITHDRAWAL").amount, Decimal("-100.00")
        )

    def test_stores_the_coin_snapshot_the_admin_must_send(self):
        self.post_withdraw()
        self.assertEqual(Withdrawal.objects.get().amount_coin, Decimal("100.000000000"))

    def test_user_may_withdraw_a_different_rail_than_they_deposited(self):
        self.account.preferred_rail = self.tron
        self.account.save(update_fields=["preferred_rail"])
        self.post_withdraw(rail="ETH", address="0x" + "d" * 40)
        self.assertEqual(Withdrawal.objects.get().rail, self.eth)

    def test_remembers_the_rail_as_the_account_preference(self):
        self.post_withdraw(rail="ETH", address="0x" + "d" * 40)
        self.account.refresh_from_db()
        self.assertEqual(self.account.preferred_rail, self.eth)

    def test_rejects_a_disabled_rail(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=False)
        self.post_withdraw(rail="ETH", address="0x" + "d" * 40)
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_rejects_a_legacy_rail_key(self):
        self.post_withdraw(rail=f"{LEGACY_PREFIX}TRON", address="T" + "2" * 33)
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_rejects_an_address_that_does_not_match_the_rail(self):
        self.post_withdraw(rail="ETH", address="T" + "2" * 33)
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_rejects_a_truncated_address(self):
        self.post_withdraw(rail="USDT:TRC20", address="T" + "2" * 32)
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_rejects_an_empty_address(self):
        self.post_withdraw(address="")
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_enforces_the_rails_minimum_withdrawal(self):
        PaymentRail.objects.filter(key="ETH").update(min_withdraw=Decimal("500.00"))
        self.post_withdraw(rail="ETH", address="0x" + "d" * 40, amount="100.00")
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_still_rejects_an_amount_below_the_floor(self):
        self.post_withdraw(amount="10.00")
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_still_rejects_insufficient_funds(self):
        self.post_withdraw(amount="9999.00")
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_debits_the_balance_and_holds_it(self):
        self.post_withdraw()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("900.00"))

    def test_withdrawal_succeeds_with_no_coin_snapshot_when_the_rate_is_missing(self):
        with mock.patch("core.rails.get_rates", return_value={}):
            self.post_withdraw()
        self.assertIsNone(Withdrawal.objects.get().amount_coin)

    def test_rejects_an_amount_that_rounds_to_zero_coins(self):
        with mock.patch("core.rails.get_rates", return_value={"USDT": Decimal("1e12")}):
            self.post_withdraw(amount="20.00")
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_disabling_every_rail_renders_a_message_instead_of_crashing(self):
        PaymentRail.objects.update(is_active=False)
        r = self.client.get("/dashboard/withdraw/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["selected_rail"])

    def test_disabling_every_rail_rejects_a_crafted_post(self):
        PaymentRail.objects.update(is_active=False)
        self.post_withdraw()
        self.assertEqual(Withdrawal.objects.count(), 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.WithdrawRailTest --keepdb`
Expected: FAIL — `withdraw` still reads `wallet_type` and the length-only address check.

- [ ] **Step 3: Rewrite the withdraw view**

Replace `user_panel/views.py:63-151` with:

```python
@active_login_required
def withdraw(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    if request.method == "POST":
        form = request.POST

        rail_key = form.get("rail", "").strip()
        raw_amount = form.get("amount", "").strip()
        address = form.get("address", "").strip()
        description = form.get("description", "").strip()

        rail = resolve_rail(rail_key)
        if rail is None:
            messages.error(request, "That network is no longer available, please choose another")
            return redirect("withdraw")

        if not address:
            messages.error(request, "Enter a wallet address")
            return redirect("withdraw")
        if len(address) > 150:
            messages.error(request, "Wallet address is too long")
            return redirect("withdraw")
        if not valid_address(rail.key, address):
            messages.error(request, f"Enter a valid {rail.network} address")
            return redirect("withdraw")

        try:
            amount = Decimal(raw_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid withdrawal amount")
            return redirect("withdraw")

        min_withdraw, max_withdraw = withdraw_limits(rail)
        if not amount.is_finite() or amount < min_withdraw or amount > max_withdraw:
            messages.error(request, f"Enter a withdrawal amount between ${min_withdraw} and ${max_withdraw}")
            return redirect("withdraw")

        amount_coin, rate_used = coin_amount(rail, amount)
        if amount_coin == 0:
            messages.error(request, f"${amount} is too small to send as {rail.symbol}, try a larger amount")
            return redirect("withdraw")

        with transaction.atomic():
            locked_rail = PaymentRail.objects.select_for_update().get(pk=rail.pk)
            if not locked_rail.is_active:
                messages.error(request, "That network is no longer available, please choose another")
                return redirect("withdraw")
            locked_account = Account.objects.select_for_update().get(pk=account.pk)
            if amount > locked_account.balance:
                messages.error(request, "ERROR: INSUFFICIENT FUNDS")
                return redirect("withdraw")

            withdrawal = Withdrawal.objects.create(
                user=request.user,
                rail=locked_rail,
                address=address,
                amount=amount,
                amount_coin=amount_coin,
                rate_used=rate_used,
                description=description,
            )
            Transaction.objects.create(
                user=request.user,
                tx_type="WITHDRAWAL",
                amount=-amount,
                status="PENDING",
                related_id=withdrawal.id,
                description=f"{locked_rail.label} withdrawal requested",
            )
            locked_account.balance = F("balance") - amount
            locked_account.save(update_fields=["balance"])
            if locked_account.preferred_rail_id != locked_rail.pk:
                locked_account.preferred_rail = locked_rail
                locked_account.save(update_fields=["preferred_rail"])

        if amount_coin is None:
            messages.warning(request, "Withdrawal submitted, but a live rate was unavailable so no coin amount was recorded.")
        else:
            messages.success(request, f"Withdrawal submitted. Send {amount_coin} {rail.symbol} on {rail.network} to {address} once approved.")
        return redirect("withdraw")

    rails = list(PaymentRail.active_rails())
    selected_rail = None
    if rails:
        selected_rail = next(
            (candidate for candidate in rails if candidate.pk == account.preferred_rail_id),
            rails[0],
        )

    prices = get_rates()
    context = {
        "account" : account,
        "rails" : rails,
        "selected_rail" : selected_rail,
        "selected_rail_key" : selected_rail.key if selected_rail else "",
        "prices" : prices,
        "prices_json" : prices_json(prices),
    }

    return render(request, "withdraw.html", context)
```

- [ ] **Step 4: Rewrite the withdraw template**

In `user_panel/templates/withdraw.html`, replace lines 36-76 (the rules box, the form, and the network select) with:

```html
    <div class="info-box">
      <h3>Withdrawal rules</h3>
      <ul>
        <li>Withdrawals are reviewed by an admin before any funds are sent.</li>
        <li>Choose the network you want to be paid on and enter an address for that network.</li>
        <li>Your balance is held as soon as you submit and is returned if the request is rejected.</li>
      </ul>
    </div>

    {% if rails %}
    <form class="panel" style="display:flex;flex-direction:column;gap:18px" method="post">
      {% csrf_token %}
      <div class="form-grid">
        <div class="field">
          <label for="network">Network</label>
          <select id="network" name="rail" required>
            {% for candidate in rails %}
              <option value="{{ candidate.key }}" data-symbol="{{ candidate.symbol }}" {% if candidate.key == selected_rail_key %}selected{% endif %}>{{ candidate.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="field">
          <label for="amount">Amount ($)</label>
          <div class="input-icon">
            <span class="in-sym">$</span>
            <input id="amount" type="number" placeholder="100.00" min="1" step="0.01" required name="amount">
          </div>
          <small id="coinHint" class="muted">You will receive <b>—</b>.</small>
        </div>
        <div class="field full">
          <label for="waddress">Your {{ selected_rail.network }} address</label>
          <input id="waddress" type="text" maxlength="150" required name="address" value="{{ account.wallet_address|default_if_none:'' }}">
        </div>
        <div class="field full">
          <label for="desc">Note <small>(optional)</small></label>
          <textarea id="desc" name="description" rows="2"></textarea>
        </div>
      </div>
      <div class="warn">
          <span class="w-icon">!</span>
        <span>Only enter an address for the network you selected. Funds sent to a wrong or malformed address cannot be recovered.</span>
      </div>
      <button type="submit" class="btn btn-gold btn-block">Request Withdrawal</button>
    </form>
    {% else %}
      <div class="panel"><div class="empty">No withdrawal networks are available right now. Please contact support.</div></div>
    {% endif %}
```

The amount input's `min` changes from `20` to `1`: the real floor now comes from `withdraw_limits(rail)`, and a hardcoded `20` in the HTML would wrongly block a rail whose admin-set minimum is lower. The `<textarea>` carries the existing `description` field name so the view is unchanged. Replace the `<script>` block at lines 82-104 with the same rate-driven coin hint used on the deposit page, writing to `#coinHint` and reading `#network` / `#amount`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.WithdrawRailTest --keepdb`
Expected: PASS, 20 tests.

- [ ] **Step 6: Run the full suite and re-point the old withdrawal tests**

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: `WithdrawTest` at `user_panel/tests.py:160-189` fails — it POSTs `{"wallet_type": "USDT", ..., "address": "abc"}` and sets `PlatformSettings.wallet_address`. Re-point its `setUp` to activate a rail and its POSTs to send `rail`, and change `"address": "abc"` to a valid `"T" + "2" * 33`.

- [ ] **Step 7: Commit**

```bash
git add user_panel/views.py user_panel/templates/withdraw.html user_panel/tests.py
git commit -m "Support per-transaction rail selection and address validation on withdraw"
```

---

### Task 7: Registration and admin account creation

**Files:**
- Modify: `core/views.py:71-160` (`register_view`)
- Modify: `core/templates/register.html:56-65`
- Modify: `admin_panel/views.py:240-310` (`admin_user_create`) and the user-update view
- Modify: `admin_panel/templates/admin-user-form.html:66-72`
- Test: `core/tests.py`, `admin_panel/tests.py`

**Interfaces:**
- Consumes: `resolve_rail`, `valid_address`, `PaymentRail.active_rails` (Tasks 1–3).
- Produces: POST field `rail` (empty allowed) replaces `wallet-type` on both the public signup form and the admin user form.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests.py`:

```python
class RegistrationRailTest(TestCase):
    def setUp(self):
        PaymentRail.objects.filter(key="USDT:TRC20").update(is_active=True)
        PaymentRail.objects.filter(key="ETH").update(is_active=True)
        self.data = {
            "full_name": "Ada Lovelace",
            "username": "ada",
            "email": "ada@example.com",
            "address": "T" + "1" * 33,
            "rail": "USDT:TRC20",
            "whatsapp-number": "+15550000",
            "password": "Str0ngPassw0rd!",
            "c_password": "Str0ngPassw0rd!",
        }

    def test_signup_page_lists_the_enabled_rails(self):
        r = self.client.get("/register/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "USDT (Tron)")
        self.assertContains(r, "Ethereum (ERC20)")

    def test_signup_page_hides_disabled_rails(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=False)
        r = self.client.get("/register/")
        self.assertNotContains(r, "Ethereum (ERC20)")

    def test_stores_the_chosen_rail_as_the_preference(self):
        self.client.post("/register/", self.data)
        account = Account.objects.get(user__username="ada")
        self.assertEqual(account.preferred_rail, PaymentRail.objects.get(key="USDT:TRC20"))

    def test_accepts_a_matching_address(self):
        self.client.post("/register/", dict(self.data, rail="ETH", address="0x" + "a" * 40))
        self.assertTrue(User.objects.filter(username="ada").exists())

    def test_rejects_an_address_that_does_not_match_the_chosen_rail(self):
        self.client.post("/register/", dict(self.data, rail="ETH", address="T" + "1" * 33))
        self.assertFalse(User.objects.filter(username="ada").exists())

    def test_rejects_a_disabled_rail(self):
        PaymentRail.objects.filter(key="ETH").update(is_active=False)
        self.client.post("/register/", dict(self.data, rail="ETH", address="0x" + "a" * 40))
        self.assertFalse(User.objects.filter(username="ada").exists())

    def test_rejects_an_unknown_rail(self):
        self.client.post("/register/", dict(self.data, rail="DOGE:ERC20"))
        self.assertFalse(User.objects.filter(username="ada").exists())

    def test_registration_succeeds_with_no_rail_and_no_address(self):
        self.client.post("/register/", dict(self.data, rail="", address=""))
        account = Account.objects.get(user__username="ada")
        self.assertIsNone(account.preferred_rail)

    def test_registration_succeeds_with_no_rail_and_an_unvalidated_address(self):
        self.client.post("/register/", dict(self.data, rail="", address="anything at all"))
        account = Account.objects.get(user__username="ada")
        self.assertIsNone(account.preferred_rail)
        self.assertEqual(account.wallet_address, "anything at all")

    def test_registration_still_awards_a_referral_reward(self):
        referrer = User.objects.create_user(username="ref", password="x")
        referrer_account = Account.objects.create(user=referrer, balance=Decimal("0.00"))
        ref_code = str(referrer_account.referral_code)
        self.client.post(f"/register/?ref={ref_code}", self.data)
        referrer_account.refresh_from_db()
        self.assertEqual(referrer_account.balance, Decimal("25.00"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RegistrationRailTest --keepdb`
Expected: FAIL — `register_view` still rejects any wallet type differing from `platform.wallet_type`.

- [ ] **Step 3: Update the register view**

In `core/views.py`, replace line 84 with:

```python
        rail_key = form.get("rail", "").strip()
```

Replace the check at lines 103-111 with:

```python
        rail = resolve_rail(rail_key) if rail_key else None
        if rail_key and rail is None:
            messages.error(request, "Choose an available network")
            return redirect("register")
        if wallet_address and len(wallet_address) > 150:
            messages.error(request, "Wallet address is too long")
            return redirect("register")
        if rail is not None and wallet_address and not valid_address(rail.key, wallet_address):
            messages.error(request, f"Enter a valid {rail.network} address")
            return redirect("register")
```

Inside the `transaction.atomic()` block, delete the re-check at lines 122-125 and replace the `Account.objects.create` call at lines 143-147 with:

```python
                Account.objects.create(
                    user=user,
                    preferred_rail=rail,
                    wallet_address=wallet_address or None,
                )
```

`PlatformSettings` is still needed inside the block for `referral_reward`, so keep the `select_for_update()` re-read but drop only the wallet-type comparison.

Add `from core.rails import resolve_rail, valid_address` to the imports.

- [ ] **Step 4: Update the signup template**

In `core/templates/register.html`, replace lines 56-65 with:

```html
        <div class="field">
          <label for="address">Payout address <small>(optional)</small></label>
          <input id="address" type="text" maxlength="150" placeholder="The address you want to be paid to" name="address">
        </div>
        <div class="field">
          <label for="rail">Network</label>
          <select name="rail" id="rail">
            <option value="">I'll choose when I deposit</option>
            {% for candidate in rails %}
              <option value="{{ candidate.key }}">{{ candidate.label }}</option>
            {% endfor %}
          </select>
          <small class="muted">Pick the network you'll send on so we can check your address now.</small>
        </div>
```

Add `"rails" : list(PaymentRail.active_rails())` to the GET context of `register_view`.

- [ ] **Step 5: Update the admin user create view**

In `admin_panel/views.py`, replace line 249 with `rail_key = form.get("rail", "").strip()` and the check at lines 261-266 with:

```python
        rail = resolve_rail(rail_key) if rail_key else None
        if rail_key and rail is None:
            messages.error(request, "Choose an available network")
            return redirect("admin_user_create")
        if not wallet_address or len(wallet_address) > 150:
            messages.error(request, "A valid wallet address is required")
            return redirect("admin_user_create")
        if rail is not None and not valid_address(rail.key, wallet_address):
            messages.error(request, f"Enter a valid {rail.network} address")
            return redirect("admin_user_create")
```

Delete the re-check at lines 290-293, and set `preferred_rail=rail` instead of `account_type=...` in the `Account.objects.create` call. Apply the same three changes to the user-update view.

- [ ] **Step 6: Update the admin user form template**

In `admin_panel/templates/admin-user-form.html`, replace the wallet-type select at lines 66-72 with:

```html
          <label for="rail">Preferred network</label>
          <select id="rail" name="rail">
            <option value="">Not set</option>
            {% for candidate in rails %}
              <option value="{{ candidate.key }}" {% if account.preferred_rail_id == candidate.pk %}selected{% endif %}>{{ candidate.label }}</option>
            {% endfor %}
          </select>
```

Add `"rails" : list(PaymentRail.active_rails())` to both the create and edit view contexts.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test core.tests.RegistrationRailTest --keepdb`
Expected: PASS, 10 tests.

- [ ] **Step 8: Delete the obsolete registration tests and run the full suite**

Delete `test_registration_rejects_a_different_wallet_network` at `core/tests.py:138-153` and the `"wallet-type": "TRON"` POST at `core/tests.py:163` that depends on it. Update the `setUp` at `core/tests.py:134-136` (which sets `platform.wallet_type = "TRON"`) to enable a rail instead.

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all pass. `AdminUserTest` cases posting `"wallet-type": "USDT"` at `admin_panel/tests.py:422` must be re-pointed to `rail`.

- [ ] **Step 9: Commit**

```bash
git add core/views.py core/templates/register.html admin_panel/views.py admin_panel/templates/admin-user-form.html core/tests.py admin_panel/tests.py
git commit -m "Offer real rail selection at signup and admin account creation"
```

---

### Task 8: Admin deposit and withdrawal review

**Files:**
- Modify: `admin_panel/views.py:20-45` (helpers), `:563-624` (deposits), `:407-524` (withdrawals)
- Modify: `admin_panel/templates/admin-deposits.html`, `admin-withdrawals.html`
- Test: `admin_panel/tests.py`

**Interfaces:**
- Consumes: `resolve_rail(key, require_active=False)`, `valid_txid` (Tasks 1, 3), `PaymentRail` (Task 2).
- Produces: `valid_rail(key)` and `valid_tx_hash(rail_key, value)` replace `valid_wallet_type` and the old `valid_tx_hash`. Both deposit and withdrawal list views accept a `?rail=<key>` query filter.

- [ ] **Step 1: Write the failing tests**

Append to `admin_panel/tests.py`:

```python
class AdminRailReviewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="root2", password="x", is_staff=True, is_superuser=True
        )
        self.user = User.objects.create_user(username="client", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.client = Client()
        self.client.force_login(self.admin)
        self.tron = PaymentRail.objects.get(key="USDT:TRC20")
        self.eth = PaymentRail.objects.get(key="ETH")
        PaymentRail.objects.filter(key="USDT:TRC20").update(is_active=True, address="T" + "1" * 33)
        PaymentRail.objects.filter(key="ETH").update(is_active=True, address="0x" + "a" * 40)

    def make_deposit(self, rail, tx_hash, amount=Decimal("200.00")):
        deposit = Deposit.objects.create(
            user=self.user, amount=amount, amount_coin=amount, rail=rail,
            tx_hash=tx_hash, tx_hash_key=f"{rail.key}:{tx_hash}",
        )
        Transaction.objects.create(
            user=self.user, tx_type="DEPOSIT", amount=amount,
            status="PENDING", related_id=deposit.id,
        )
        return deposit

    def test_approving_a_deposit_credits_the_usd_amount(self):
        deposit = self.make_deposit(self.tron, "a" * 64)
        self.client.post(f"/admin-secure-portal/deposits/approve/{deposit.id}/")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("200.00"))
        self.assertEqual(Deposit.objects.get(pk=deposit.pk).status, "APPROVED")

    def test_approving_a_legacy_rail_deposit_still_credits_the_balance(self):
        legacy = legacy_rail_for_symbol("TRON")
        deposit = self.make_deposit(legacy, "b" * 64)
        self.client.post(f"/admin-secure-portal/deposits/approve/{deposit.id}/")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("200.00"))

    def test_deposits_can_be_filtered_by_rail(self):
        self.make_deposit(self.tron, "a" * 64)
        self.make_deposit(self.eth, "0x" + "b" * 62)
        r = self.client.get("/admin-secure-portal/deposits/?rail=ETH")
        self.assertEqual([d.rail for d in r.context["deposits"]], [self.eth])

    def test_approving_a_deposit_rejects_a_txid_wrong_for_its_rail(self):
        deposit = self.make_deposit(self.tron, "0x" + "c" * 64)
        self.client.post(f"/admin-secure-portal/deposits/approve/{deposit.id}/")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(Deposit.objects.get(pk=deposit.pk).status, "PENDING")

    def test_the_same_txid_on_two_rails_can_both_be_approved(self):
        first = self.make_deposit(self.tron, "d" * 64)
        second = self.make_deposit(self.eth, "0x" + "d" * 64)
        self.client.post(f"/admin-secure-portal/deposits/approve/{first.id}/")
        self.client.post(f"/admin-secure-portal/deposits/approve/{second.id}/")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("400.00"))

    def test_withdrawal_list_shows_the_rail_and_coin_amount(self):
        withdrawal = Withdrawal.objects.create(
            user=self.user, rail=self.eth, address="0x" + "d" * 40,
            amount=Decimal("50.00"), amount_coin=Decimal("0.016666"),
        )
        Transaction.objects.create(
            user=self.user, tx_type="WITHDRAWAL", amount=Decimal("-50.00"),
            status="PENDING", related_id=withdrawal.id,
        )
        r = self.client.get("/admin-secure-portal/withdrawals/pending/")
        self.assertContains(r, "Ethereum (ERC20)")
        self.assertContains(r, "0.016666")

    def test_approving_a_withdrawal_does_not_require_a_rail_match(self):
        withdrawal = Withdrawal.objects.create(
            user=self.user, rail=self.eth, address="0x" + "d" * 40, amount=Decimal("50.00"),
        )
        Transaction.objects.create(
            user=self.user, tx_type="WITHDRAWAL", amount=Decimal("-50.00"),
            status="PENDING", related_id=withdrawal.id,
        )
        self.client.post(f"/admin-secure-portal/withdrawals/approve/{withdrawal.id}/")
        self.assertEqual(Withdrawal.objects.get(pk=withdrawal.pk).status, "APPROVED")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test admin_panel.tests.AdminRailReviewTest --keepdb`
Expected: FAIL — `approve_deposit` still calls `valid_wallet_type` and the old `valid_tx_hash`.

- [ ] **Step 3: Replace the validators**

Replace `admin_panel/views.py:40-45` with:

```python
def valid_rail(rail_key):
    return resolve_rail(rail_key, require_active=False) is not None

def valid_tx_hash(rail_key, value):
    return valid_txid(rail_key, value)
```

- [ ] **Step 4: Update `approve_deposit`**

Replace the guard at `admin_panel/views.py:594-602` with:

```python
        if deposit.status == "PENDING" and (
            not valid_rail(deposit.rail.key)
            or not valid_tx_hash(deposit.rail.key, deposit.tx_hash)
            or not deposit.amount.is_finite()
            or deposit.amount <= 0
            or duplicate_hash
        ):
            messages.error(request, "Deposit network, amount, or transaction hash is invalid")
            return redirect("admin_deposits")
```

Scope `duplicate_hash` to the rail — in the block that computes it (`:587-593`), change the lookup to `Deposit.objects.filter(tx_hash_key=f"{deposit.rail.key}:{normalized_hash}")`.

- [ ] **Step 5: Update `approve_withdrawal`**

Replace the wallet-type check at `admin_panel/views.py:442-448` with a rail existence check that permits retired rails:

```python
        if not valid_rail(withdrawal.rail.key):
            messages.error(request, "Withdrawal network is invalid")
            return redirect("admin_withdrawals")
```

- [ ] **Step 6: Add the rail filter to both list views**

In `admin_deposits`, after the existing filters, add:

```python
    rail_filter = request.GET.get("rail", "").strip()
    if rail_filter:
        deposits = deposits.filter(rail__key=rail_filter)
    else:
        rail_filter = ""
```

and add `"rail_filter": rail_filter, "rails": PaymentRail.rails()` to the context. Apply the same in `admin_withdrawals`.

- [ ] **Step 7: Update the review templates**

In `admin-deposits.html`, insert a filter bar directly above the table (`:39`):

```html
      <form class="filter-bar" method="get">
        <label for="rail">Network</label>
        <select id="rail" name="rail">
          <option value="">All networks</option>
          {% for candidate in rails %}
            <option value="{{ candidate.key }}" {% if candidate.key == rail_filter %}selected{% endif %}>{{ candidate.label }}</option>
          {% endfor %}
        </select>
        <button type="submit" class="btn btn-ghost">Filter</button>
      </form>
```

Change the header row (`:39`) to `<tr><th>Date</th><th>Amount</th><th>Coin</th><th>Network</th><th>TXID</th><th>Status</th></tr>` and add the coin cell next to the existing network cell:

```html
              <td>{{ d.rail.label }}</td>
              <td>{{ d.amount_coin|default_if_none:"rate unavailable" }} {{ d.rail.symbol }}</td>
```

Apply the equivalent filter bar, `Network` cell change, and `Coin` column in `admin-withdrawals.html` before its status-filter row (`:33-36`), using `w.rail.label` and `{{ w.amount_coin|default_if_none:"rate unavailable" }}`.

Add the filter-bar styles to `admin_panel/static/css/app.css`:

```css
.filter-bar{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
```

- [ ] **Step 8: Run the tests to verify them, then the full suite**

Run: `.venv/Scripts/python.exe manage.py test admin_panel.tests.AdminRailReviewTest --keepdb`
Expected: PASS, 8 tests.

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: failures in `AdminDepositTest`, `AdminWithdrawalTest`, and the tests at `admin_panel/tests.py:322-412`, all of which call `Deposit.objects.create(amount=..., wallet_type="USDT", ...)` and `Withdrawal.objects.create(wallet_type="USDT", ...)`. Re-point every one to pass `rail=<row>` instead of `wallet_type=...`, and update `"wallet-type": "USDT"` POSTs (`:422`) to `"rail": "USDT:TRC20"`. Delete `test_changing_wallet_type_is_blocked` at `:499-517` if it still exists.

- [ ] **Step 9: Commit**

```bash
git add admin_panel/views.py admin_panel/templates/admin-deposits.html admin_panel/templates/admin-withdrawals.html admin_panel/tests.py
git commit -m "Review deposits and withdrawals per rail with on-chain coin amounts"
```

---

### Task 9: Dashboard, transaction history, and copy fixes

**Files:**
- Modify: `user_panel/templates/dashboard.html:32-33`
- Modify: `user_panel/templates/transactions.html:47`
- Modify: `user_panel/views.py:42-61` (`dashboard_view`)
- Modify: `admin_panel/templates/admin-package-form.html:78,85`
- Test: `user_panel/tests.py`

**Interfaces:**
- Consumes: `PaymentRail` (Task 2).
- Produces: dashboard and transaction history render the preferred rail's label instead of the removed `account.account_type`.

- [ ] **Step 1: Write the failing tests**

Append to `user_panel/tests.py`:

```python
class PreferredRailDisplayTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="viewer", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("500.00"))
        self.client = Client()
        self.client.force_login(self.user)
        self.eth = PaymentRail.objects.get(key="ETH")
        PaymentRail.objects.filter(key="ETH").update(is_active=True)

    def test_dashboard_shows_the_preferred_rail_symbol(self):
        self.account.preferred_rail = self.eth
        self.account.save(update_fields=["preferred_rail"])
        r = self.client.get("/dashboard/")
        self.assertContains(r, "Ethereum (ERC20)")

    def test_dashboard_falls_back_when_no_rail_is_preferred(self):
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Your account wallet type needs administrator review")

    def test_transaction_history_reports_the_preferred_rail(self):
        self.account.preferred_rail = self.eth
        self.account.save(update_fields=["preferred_rail"])
        r = self.client.get("/dashboard/transactions/")
        self.assertContains(r, "Ethereum (ERC20)")

    def test_transaction_history_is_fine_with_no_rail(self):
        r = self.client.get("/dashboard/transactions/")
        self.assertEqual(r.status_code, 200)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.PreferredRailDisplayTest --keepdb`
Expected: FAIL — the templates still reference `account.account_type`, which is a template attribute lookup that renders empty rather than erroring, so the `assertContains` cases fail.

- [ ] **Step 3: Update the templates**

In `user_panel/templates/dashboard.html`, replace line 33 with:

```html
        <div class="w-note">Available USD{% if account.preferred_rail %} · on {{ account.preferred_rail.label }}{% endif %}</div>
```

In `user_panel/templates/transactions.html`, replace line 47 with:

```html
        <p>Preferred network: {% if account.preferred_rail %}{{ account.preferred_rail.label }}{% else %}Not set{% endif %}</p>
```

- [ ] **Step 4: Fix the USD mislabelling**

In `admin_panel/templates/admin-package-form.html`, change lines 78 and 85 from `Minimum Amount (USDT)` / `Maximum Amount (USDT)` to `Minimum Amount ($)` / `Maximum Amount ($)`. In `admin_panel/templates/admin-settings.html`, line 57 becomes `Referral Reward ($)` (already done in Task 4).

- [ ] **Step 5: Run the tests, then the full suite**

Run: `.venv/Scripts/python.exe manage.py test user_panel.tests.PreferredRailDisplayTest --keepdb`
Expected: PASS, 4 tests.

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add user_panel/templates/dashboard.html user_panel/templates/transactions.html admin_panel/templates/admin-package-form.html user_panel/tests.py
git commit -m "Show the preferred rail in the dashboard and fix USD mislabelling"
```

---

### Task 10: Retire the legacy wallet fields

**Files:**
- Create: `core/migrations/0031_retire_legacy_wallet_fields.py`
- Modify: `core/models.py`
- Test: the three existing suites

**Interfaces:**
- Consumes: `legacy_rail_for_symbol` (Task 2).
- Produces: `Deposit.amount_usd` (renamed from `amount`), `Deposit.rail` / `Withdrawal.rail` non-null, `PlatformSettings` reduced to `referral_reward`, `Account.account_type` removed, `unique_together(("rail", "tx_hash_key"))` on `Deposit`.

**This is the cutover.** Every task before this one leaves the app running; this task drops columns, so all references must already be gone. Verify with the full suite before starting.

- [ ] **Step 1: Confirm the preconditions**

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all pass. If any test still touches `platform.wallet_type`, `account_type`, `deposit.amount`, or `withdrawal.amount` as a *rename candidate*, fix it now — this task is where those references break.

- [ ] **Step 2: Write the failing test**

Add to `core/tests.py`:

```python
class LegacyFieldRetirementTest(TestCase):
    def test_platform_settings_no_longer_declares_a_wallet_type(self):
        self.assertFalse(
            [f.name for f in PlatformSettings._meta.get_fields() if f.name == "wallet_type"]
        )

    def test_account_no_longer_declares_account_type(self):
        self.assertFalse(
            [f.name for f in Account._meta.get_fields() if f.name == "account_type"]
        )

    def test_deposit_uses_amount_usd(self):
        self.assertIn("amount_usd", [f.name for f in Deposit._meta.get_fields()])
        self.assertNotIn("amount", [f.name for f in Deposit._meta.get_fields()])

    def test_withdrawal_uses_amount_usd(self):
        self.assertIn("amount_usd", [f.name for f in Withdrawal._meta.get_fields()])
        self.assertNotIn("amount", [f.name for f in Withdrawal._meta.get_fields()])

    def test_rail_is_mandatory_on_both_ledger_rows(self):
        for model in (Deposit, Withdrawal):
            with self.subTest(model=model.__name__):
                self.assertFalse(model._meta.get_field("rail").null)

    def test_tx_hash_uniqueness_is_scoped_per_rail(self):
        names = {tuple(c) for c in Deposit._meta.unique_together}
        self.assertIn(("rail", "tx_hash_key"), names)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe manage.py test core.tests.LegacyFieldRetirementTest --keepdb`
Expected: FAIL on all six assertions.

- [ ] **Step 4: Change the models**

In `core/models.py`:

- `PlatformSettings` — delete the `wallet_type` and `wallet_address` fields (lines 10-11).
- `Account` — delete `account_type` (line 41).
- `Deposit` — delete `wallet_type` (line 96); rename `amount` to `amount_usd`; change `rail` to `null=False`.
- `Withdrawal` — delete `wallet_type` (line 112); rename `amount` to `amount_usd`; change `rail` to `null=False`.
- Add `class Meta:` to `Deposit` with `unique_together = [("rail", "tx_hash_key")]`.

- [ ] **Step 5: Write the data migration**

Create `core/migrations/0031_retire_legacy_wallet_fields.py` with a `RunPython` that backfills `rail` from the old `wallet_type` strings **before** the field becomes non-null, creating a `LEGACY:<SYMBOL>` row for any unmatched symbol:

```python
def backfill_rails(apps, schema_editor):
    PaymentRail = apps.get_model("core", "PaymentRail")
    Deposit = apps.get_model("core", "Deposit")
    Withdrawal = apps.get_model("core", "Withdrawal")
    Account = apps.get_model("core", "Account")

    def resolve(symbol):
        normalized = (symbol or "").strip().upper()
        if not normalized:
            return None
        rail = PaymentRail.objects.filter(key=normalized).first()
        if rail is not None:
            return rail
        rail, _ = PaymentRail.objects.get_or_create(
            key=f"LEGACY:{normalized}",
            defaults={
                "symbol": normalized[:10],
                "network": "LEGACY",
                "label": f"{normalized} (retired network)",
                "is_active": False,
                "address": "",
                "display_order": 9999,
            },
        )
        return rail

    for model, field in ((Deposit, "wallet_type"), (Withdrawal, "wallet_type"), (Account, "account_type")):
        for row in model.objects.filter(rail__isnull=True):
            rail = resolve(getattr(row, field))
            if rail is not None:
                row.rail = rail
                row.save(update_fields=["rail"])

    for account in Account.objects.filter(preferred_rail__isnull=True):
        rail = resolve(account.account_type)
        if rail is not None:
            account.preferred_rail = rail
            account.save(update_fields=["preferred_rail"])
```

Order the operations: `RunPython(backfill_rails)` → `RenameField` ×2 → `AlterField` (rail non-null) ×2 → `RemoveField` ×5 → `AddConstraint` for the `unique_together`. Set `dependencies` to `[("core", "0030_payment_rail")]`.

- [ ] **Step 6: Fix every remaining reference**

Run: `grep -rn "account_type\|wallet_type\|wallet_address" core user_panel admin_panel --include=*.py --include=*.html | grep -v migrations | grep -v LEGACY`

Expected: only `PlatformSettings` in `core/tests.py` referring to the *removed* referral-only model, and the `LEGACY_PREFIX` handling that is intentional. Fix every other hit — in particular `user_panel/views.py` (the `to_coin(account.account_type, ...)` call at line 54 must become `to_coin(account.preferred_rail.symbol, ...)` guarded on `preferred_rail`), and any `d.amount` / `w.amount` in templates and views (now `amount_usd`).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe manage.py test core.tests.LegacyFieldRetirementTest --keepdb`
Expected: PASS, 6 tests.

- [ ] **Step 8: Run the full suite**

Run: `.venv/Scripts/python.exe manage.py test --keepdb`
Expected: all pass. This is the task where any straggler `amount=` / `wallet_type=` in a test surfaces; fix each to `amount_usd=` and `rail=`.

- [ ] **Step 9: Verify migrations apply cleanly from empty**

Run: `.venv/Scripts/python.exe manage.py migrate --run-syncdb` against a scratch database, then `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 10: Commit**

```bash
git add core/models.py core/migrations/0031_retire_legacy_wallet_fields.py core/tests.py
git add -u
git commit -m "Retire the single global wallet type fields"
```
