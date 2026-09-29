# Multi-Rail Wallets — Design Spec

**Date:** 2026-09-29
**Status:** Draft for review
**Scope:** Replace the single global platform wallet type with a set of independently
toggled payment rails that users select per transaction.

---

## 1. Problem

The platform has exactly one active wallet type, stored in
`PlatformSettings.wallet_type` (`core/models.py:10`). Three defects follow from this:

1. **The user "Network" dropdown is decorative.**
   `user_panel/templates/deposit.html:56-58` and `withdraw.html:48-52` each render a
   single `<option>` bound to the platform setting. Users cannot choose anything.

2. **The admin is permanently locked on the first currency used.**
   `admin_panel/views.py:698-706` refuses any `wallet_type` change while any
   `Account.account_type` differs, and `user_panel/views.py:82-84` / `:348-350` then
   hard-block those users with "Your account wallet type needs administrator review".
   There is no self-service remedy. Once a user registers, the currency is frozen.

3. **There is no network concept, and TXID validation is EVM-only.**
   There is no TRC20 / BEP20 / ERC20 / base58 distinction. The single regex
   `(?:0x)?[0-9A-F]{64}` (`user_panel/views.py:356`, `admin_panel/views.py:45`) rejects
   TRON hex TXIDs as a class and every Bitcoin or Solana transaction hash.

A fourth, latent, issue surfaces only once multiple rails exist:

4. **Deposit amounts are USD but labelled as coin.**
   `admin_panel/views.py:614` credits `deposit.amount` straight into `Account.balance`,
   and `dashboard.html:32` prints that field with a `$` prefix. The number a user types
   is a **USD value**, even though `deposit.html:61` labels the field
   `Amount ({{ platform_wallet_type }})`. With USDT this is harmless (~$1 parity). With
   BTC it is not: a user who intends to send 0.002 BTC and types "100" is credited
   $100, and the admin has no record of what should have arrived on-chain.

**The load-bearing constraint: `Account.balance` remains a single USD scalar.** The
`Transaction` ledger, investments, ROI, and referrals are all USD-denominated today and
are not touched. A "rail" is the wire a value moves on, not a balance denomination. This
spec therefore does **not** redesign the ledger and requires no migration of existing
balances.

---

## 2. Goals

- The admin can enable, disable, and configure any number of payment rails, each with
  its own receive address and its own limits.
- A user picks any enabled rail on each deposit and each withdrawal; their most recent
  choice is remembered and pre-selected.
- No user can ever be locked out of depositing or withdrawing by an admin settings
  change. The class of bug in defect 2 is structurally impossible.
- Per-network TXID and address validation, replacing the EVM-only regex.
- A user always sees the exact coin quantity they must send, and the admin can always
  see what should have arrived on-chain.
- One USD ledger, unchanged.

## 3. Non-goals

- Per-coin balances (a user holding both 500 USDT and 0.05 BTC). This would require
  splitting `Account.balance` and defining how a USD-priced investment settles across
  denominations. Explicitly deferred.
- On-chain verification. No block explorer or node integration; admin approval remains
  the trust boundary, as today.
- Per-user rate quotes or FX spreads. The cached CoinGecko rate is used as-is.
- Automatic rail creation from the admin UI. The catalog is a code change plus a
  migration, by design (see §4.2).
- Consolidating the triplicated static assets (`app.css` / `admin.js` duplicated across
  `core/`, `user_panel/`, `admin_panel/`). Noted, out of scope.

---

## 4. Design

### 4.1 Behaviour vs. display split

The single most important structural decision: **validation rules live in code, mutable
configuration lives in the database, and the two are joined by one key.**

- **Code (`core/rails.py`)** — the fixed catalog: symbol, network, label, CoinGecko id,
  coin decimals, address regex, TXID regex. Not editable, not stored in the DB.
- **Database (`PaymentRail`)** — display copy of symbol/network/label, plus everything
  the admin controls: active flag, receive address, limits, display order.
- **Join** — `key`, e.g. `USDT:TRC20`.

The database never stores a regex. The admin therefore cannot corrupt a validation rule,
and a code change cannot silently drift from stored data. A test asserts the two sides
stay in parity (§7).

### 4.2 The fixed catalog

```python
RAIL_CATALOG = {
    "USDT:TRC20": {
        "symbol": "USDT", "network": "TRC20", "label": "USDT (Tron)",
        "coin_id": "tether", "coin_decimals": 6,
        "address_re": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
        "txid_re":    r"^[0-9a-fA-F]{64}$",
    },
    "USDT:BEP20": {
        "symbol": "USDT", "network": "BEP20", "label": "USDT (BNB Smart Chain)",
        "coin_id": "tether", "coin_decimals": 6,
        "address_re": r"^0x[0-9a-fA-F]{40}$",
        "txid_re":    r"^0x[0-9a-fA-F]{64}$",
    },
    "BTC": {
        "symbol": "BTC", "network": "BITCOIN", "label": "Bitcoin",
        "coin_id": "bitcoin", "coin_decimals": 8,
        "address_re": r"^(bc1[ac-hj-np-z02-9]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$",
        "txid_re":    r"^[1-9A-HJ-NP-Za-km-z]{32,64}$",
    },
    "ETH": {
        "symbol": "ETH", "network": "ERC20", "label": "Ethereum (ERC20)",
        "coin_id": "ethereum", "coin_decimals": 18,
        "address_re": r"^0x[0-9a-fA-F]{40}$",
        "txid_re":    r"^0x[0-9a-fA-F]{64}$",
    },
    "SOL": {
        "symbol": "SOL", "network": "SOLANA", "label": "Solana",
        "coin_id": "solana", "coin_decimals": 9,
        "address_re": r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
        "txid_re":    r"^[1-9A-HJ-NP-Za-km-z]{64,90}$",
    },
}
```

`coin_id` maps into `COIN_IDS` in `core/currency.py:10-15`, which is what gives a rail a
live rate. `USDT` already has a hardcoded `1.00` fallback (`core/currency.py:71-72`);
the other symbols do not, and §5.4 covers what happens when a rate is missing.

The catalog is deliberately not user-extensible. The admin UI has no "add rail"
control — only a toggle, an address, and limits per existing rail. Extending the
platform to a new coin is a code change plus a migration, which is what keeps rates and
validation correct by construction.

### 4.3 `PaymentRail` model

Added to `core/models.py`.

| Field | Type | Notes |
|---|---|---|
| `key` | `CharField(max_length=50, unique=True)` | e.g. `USDT:TRC20`; joins to `RAIL_CATALOG` |
| `symbol` | `CharField(max_length=10)` | display copy |
| `network` | `CharField(max_length=20)` | display copy |
| `label` | `CharField(max_length=50)` | display copy |
| `is_active` | `BooleanField(default=False)` | the admin's switch; **default off** |
| `address` | `CharField(max_length=150, blank=True, default="")` | platform receive address |
| `min_deposit` | `DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)` | `null` = use global default |
| `max_deposit` | same | `null` = no rail cap |
| `min_withdraw` | same | `null` = use global default |
| `max_withdraw` | same | `null` = no rail cap |
| `display_order` | `IntegerField(default=0)` | dropdown ordering |
| `date_updated` | `DateTimeField(auto_now=True)` | |

`is_active` defaults to `False` so a freshly migrated database has **no live rails**.
Nothing is reachable by users until the admin deliberately enables a rail and supplies a
valid address. This mirrors the current posture, where an empty
`PlatformSettings.wallet_address` already blocks deposits
(`user_panel/views.py:352-354`).

`unique_together(symbol, network)` is implied by the unique `key`; no second constraint
is needed.

### 4.4 Retired and renamed fields

**Removed:**

| Removed | Replaced by | Reason |
|---|---|---|
| `PlatformSettings.wallet_type` | `PaymentRail.symbol`/`network`/`key` | one global currency is the root defect |
| `PlatformSettings.wallet_address` | `PaymentRail.address` | a single address cannot serve several rails |
| `Account.account_type` | `Account.preferred_rail` | was a gate; becomes a hint |
| `Deposit.wallet_type` | `Deposit.rail` (FK) | string → referential integrity |
| `Withdrawal.wallet_type` | `Withdrawal.rail` (FK) | string → referential integrity |

**Renamed:**

| Old | New | Reason |
|---|---|---|
| `Deposit.amount` | `Deposit.amount_usd` | unit is USD; must be unambiguous beside `amount_coin` |
| `Withdrawal.amount` | `Withdrawal.amount_usd` | same |

**Added:**

| New field | Model | Reason |
|---|---|---|
| `preferred_rail` | `Account` | last-used rail, pre-selected in forms; never a gate |
| `rail` | `Deposit`, `Withdrawal` | FK to `PaymentRail`, `PROTECT` |
| `amount_coin` | `Deposit`, `Withdrawal` | coin quantity to expect on / send from the chain |
| `rate_used` | `Deposit`, `Withdrawal` | rate snapshot at submission, for audit |

The `amount` → `amount_usd` rename is mechanical — the fields are read in roughly a
dozen places, including `Sum("amount")` at `user_panel/views.py:56` and the admin review
views — and it is worth doing now rather than leaving a field named `amount` whose unit
is only discoverable by reading the approval code. `Transaction.amount` is **not**
renamed: it is unambiguously the USD ledger amount everywhere it appears, and renaming it
would touch the ROI, investment, and referral paths for no gain.

`PlatformSettings` retains `referral_reward` and its singleton behaviour
(`core/models.py:19-29`).

`Account.preferred_rail = ForeignKey(PaymentRail, null=True, blank=True,
on_delete=SET_NULL)`. It is **only** a form pre-selection default. No code path may
reject a transaction because of it — that invariant is the fix for defect 2.

`Deposit.rail` and `Withdrawal.rail` use `on_delete=PROTECT`. Catalog rows are never
deleted (the admin deactivates instead), so historical deposits always resolve to a
real rail.

### 4.5 The change-blocking guard is deleted

`admin_panel/views.py:698-706` exists solely to prevent a currency change from
stranding accounts. With independent per-rail toggles there is no global currency to
change, so the guard has no subject and is removed. This is the structural fix: the
lockout is not made safer, it is made unrepresentable.

### 4.6 Migrations

Two steps, so each is independently safe and the intermediate state is deployable.

**`0030_payment_rail.py`**
1. Create `PaymentRail`.
2. Add `Account.preferred_rail` (nullable), `Deposit.rail` (nullable), `Withdrawal.rail`
   (nullable).
3. Seed one row per `RAIL_CATALOG` entry, copying `symbol`/`network`/`label`,
   `is_active=False`, empty address, all limits `NULL`, `display_order` from dict order.
4. Backfill: for each existing `Deposit`/`Withdrawal`, resolve `wallet_type` to a rail
   key by exact uppercased symbol match. If a row's symbol has no catalog match, create
   an inactive `LEGACY:<SYMBOL>` row (network `LEGACY`, no address) and point at it.
   **The migration therefore cannot fail on unexpected data.** A `LEGACY:` row is inert
   and exists only to satisfy the foreign key: its key is absent from `RAIL_CATALOG`, so
   `catalog_entry()` returns `None`, it is never returned by `enabled_rails()`, it can
   never be selected by a user, and every validator treats it as unknown rather than
   matching. It renders in history via its own `label`. Admin approval of a historical
   deposit on such a rail falls back to symbol-only checks. The current local database
   has no such rows.
5. Backfill `Account.preferred_rail` from `Account.account_type` by the same rule.

**`0031_remove_legacy_wallet_fields.py`**
1. Delete `Deposit.wallet_type`, `Withdrawal.wallet_type`,
   `PlatformSettings.wallet_type`, `PlatformSettings.wallet_address`,
   `Account.account_type`.
2. Rename `Deposit.amount` → `amount_usd`, `Withdrawal.amount` → `amount_usd`.
3. Alter `Deposit.rail` and `Withdrawal.rail` to non-null.
4. Add `unique_together(("rail", "tx_hash_key"))` on `Deposit`.
5. Alter `Account.preferred_rail` to `on_delete=SET_NULL`.

The current local database contains zero rows in `core_account`, `core_deposit`, and
`core_withdrawal`, but both migrations are written to be correct against a populated
database regardless.

### 4.7 Per-rail TXID uniqueness

`Deposit.tx_hash_key` is currently globally unique (`core/models.py:98-104`). A 64-hex
TXID is legal on both ETH and TRON, so under multiple rails the same hash on two
different chains would collide and the second deposit would be rejected as a duplicate.
Uniqueness becomes per-rail, via the `unique_together` in migration `0031`. The
duplicate-hash check in `admin_panel/views.py:587-593` is updated to scope by rail to
match.

---

## 5. Behaviour

### 5.1 Helper API (`core/rails.py`)

Single-responsibility module: owns the catalog and the rules, imports no views, and
defines no models.

- `catalog_entry(key) -> dict | None` — the code-side definition.
- `valid_address(key, value) -> bool` — anchored regex from the catalog.
- `valid_txid(key, value) -> bool` — anchored regex from the catalog.
- `enabled_rails() -> list[PaymentRail]` — active rails in `display_order`.
- `limits_for(rail) -> tuple[Decimal | None, Decimal | None]` — the rail's effective
  (min, max), falling back to global defaults.
- `coin_amount(rail, usd_amount) -> tuple[Decimal | None, Decimal | None]` —
  `(coin_quantity, rate_used)`; `(None, None)` when no rate is available.

### 5.2 Limit resolution

One helper serves the view, the HTML `min` attribute, and the error text, so they
cannot disagree:

| | `null` in DB | resolved to |
|---|---|---|
| `min_deposit` | yes | `Decimal("1.00")` (current `user_panel/views.py:372` / `deposit.html:64`) |
| `min_withdraw` | yes | `Decimal("20.00")` (current `user_panel/views.py:103` / `withdraw.html:57`) |
| `max_*` | yes | `MAX_FINANCIAL_AMOUNT` |

### 5.3 Deposit

`user_panel/views.py:330-425`.

**GET.** Context gains `rails` (enabled rails), `selected_rail` (`account.preferred_rail`
if still enabled, else the first enabled rail), and `rail_addresses` — a dict keyed by
rail `key` so the existing JS at `deposit.html:120-142` can swap the displayed address
as the dropdown changes without a page reload. `platform_address` and
`platform_wallet_type` are removed.

**POST.** Resolve the rail from the submitted `rail` key, then in order: the key exists
in the catalog; the row exists and `is_active`; `address` is non-empty; `valid_txid`;
`valid_address` is not applied to the platform address here (already checked at save);
USD amount parses, is finite, is positive, and satisfies `limits_for(rail)`. Then
`coin_amount(rail, amount)` yields the snapshot. Create `Deposit` with
`amount` (USD), `amount_coin`, `rate_used`, `rail`, `tx_hash`, `tx_hash_key`, and
`Transaction(tx_type="DEPOSIT", amount=<usd>, status="PENDING")`. Set
`account.preferred_rail = rail`.

**Concurrency.** Inside the existing `transaction.atomic()` /
`select_for_update()` block (`:376-392`), the rail is re-read and re-checked for
still-active and address non-empty. This mirrors the defence the current code already
uses against a settings change landing mid-submit.

### 5.4 Rate unavailability

`get_rates()` already degrades to stale cached values and hardcodes `USDT = 1.00`
(`core/currency.py:39-73`). For a rail whose symbol has no rate:

- The submission **succeeds**, with `amount_coin = None` and `rate_used = None`.
- A success message notes the conversion was unavailable.
- The admin review row shows "rate unavailable — verify on-chain" instead of a coin
  figure.

A user is never locked out of depositing because CoinGecko is down. The USD amount they
typed is still what the ledger records, which is the same behaviour as today.

### 5.5 Withdraw

`user_panel/views.py:63-151`. Identical rail resolution and limit handling, plus:

- **Destination address validation.** `valid_address(rail.key, address)` replaces the
  current length-only check at `:86-91`. This is a deliberate addition: a truncated or
  wrong-rail destination is an unrecoverable loss, and a per-rail format check is a
  principal benefit of the feature. If a rail proves to have an address format the
  catalog does not capture, the fix is a catalog entry, not a code change elsewhere.
- **Coin snapshot.** `amount_coin` and `rate_used` are stored so the admin knows how
  much to actually send out on-chain.
- `account.preferred_rail = rail`.

### 5.6 Registration

`core/templates/register.html:60-65` — the wallet-type select is removed. It existed
only to mirror a locked setting, and with per-transaction choice it would be a lie.

The address input at `:56-59` is kept and relabelled as an optional default payout
address, pre-filling the withdraw form's address field. Nothing previously collected is
lost, and the field is no longer a currency selector.

`core/views.py` registration handling drops its `wallet-type` read; `Account` is created
without `account_type`.

### 5.7 Dashboard and transactions

`dashboard.html:33` — `Available {{ account.account_type }}` becomes the preferred rail's
symbol, falling back to `USDT`. The `${{ account.balance }}` figure above it is already
correct and unchanged.

`transactions.html:47` — `Current wallet {{ account.account_type }}` becomes
`Preferred network {{ account.preferred_rail.label }}` (or a neutral "Not set" state).

---

## 6. Admin

### 6.1 Settings page

`admin_panel/templates/admin-settings.html:36-52` — the single Wallet Type select and
one address input become a repeated block per catalog rail, in `display_order`:

- rail label (read-only text, not an input)
- enabled checkbox
- receive address input
- min / max deposit, min / max withdrawal

One POST, with keys namespaced per rail: `rail-USDT:TRC20-active`,
`rail-USDT:TRC20-address`, `rail-USDT:TRC20-min-deposit`, and so on. Colons in `key` are
unsafe in an HTML `name` attribute, so the POST protocol uses `-` separators and the
view reconstructs the key.

`admin_settings` (`admin_panel/views.py:660-719`) validates that **every enabled rail has
a non-empty address matching its catalog pattern**, parses and range-checks the four
limit fields, and rejects a `min` greater than its `max`. The wallet-type branch and the
`:698-706` guard are removed. The referral-reward branch is unchanged. An audit log
entry records the change.

### 6.2 Deposit and withdrawal review

`admin-deposits.html` and `admin-withdrawals.html` gain a rail filter, and the amount
column shows the expected coin figure beside the USD figure (or "rate unavailable").
`valid_wallet_type()` (`admin_panel/views.py:40-41`) is replaced by a rail lookup, and
`valid_tx_hash()` (`:44-45`) is replaced by `core.rails.valid_txid(rail.key, value)`.
The duplicate-hash check at `:587-593` is scoped per rail (§4.7).

`approve_deposit` credits `deposit.amount` (USD) exactly as `:614` does today — the
ledger is unchanged.

### 6.3 Per-user form

`admin_user-form.html:66-72` — the wallet-type select becomes a preferred-rail select
over enabled rails, with an empty "Not set" option. `admin_user_create` and the user
update view stop reading `platform.wallet_type` to populate `Account.account_type` and
populate `preferred_rail` instead.

---

## 7. Testing

Existing suites are `core/tests.py`, `user_panel/tests.py`, and `admin_panel/tests.py`,
using `django.test.TestCase` with direct model setup.

**New coverage**

- `core/tests.py` — `RailCatalogTest`: every `RAIL_CATALOG` key has exactly one
  `PaymentRail` row; and every row whose key does not begin with `LEGACY:` is a catalog
  key (the §4.1 parity invariant, scoped to exclude the §4.6 placeholder rows).
  `RailValidationTest`: per-rail `valid_address` / `valid_txid` accept
  well-formed values and reject cross-rail values (a TRON address is rejected on BEP20;
  a `0x` TXID is rejected on TRON). `limits_for` fallback behaviour.
- `user_panel/tests.py` — deposit GET lists all enabled rails and omits disabled ones;
  POST rejects a disabled or unknown rail; TXID is validated against the selected rail;
  per-rail min and max are enforced; `amount_coin` and `rate_used` are snapshotted
  correctly for a known rate; submission succeeds with `amount_coin=None` when the rate
  is missing; `preferred_rail` is persisted; the same TXID on two different rails is
  accepted. Withdrawal: destination address validated per rail; per-rail withdrawal
  minimum enforced; coin snapshot stored; insufficient funds still rejected.
- `admin_panel/tests.py` — settings save per-rail config; saving with an enabled rail
  and an empty address is rejected; saving with a malformed address is rejected; toggling
  a rail off removes it from the user-facing dropdown; `min` greater than `max` is
  rejected; per-user preferred rail is assignable.

**Changed or removed coverage** — two existing tests assert the behaviour this spec
deletes, and must be rewritten rather than kept:

- `user_panel/tests.py:257-271` asserts that a user whose `account_type` differs from the
  platform is blocked from depositing. **The gate is gone; the test is deleted.**
- `admin_panel/tests.py:499-517` asserts that a `wallet_type` change is blocked while
  mismatched accounts exist. **The guard is gone; the test is deleted.**
- `user_panel/tests.py:244-255` (deposit rejected for a non-platform wallet) is
  re-pointed at a disabled rail instead.
- `admin_panel/tests.py:486-498` (settings update to `TRON`) is re-pointed at per-rail
  config.
- `core/tests.py:390-419` `CurrencyTest` is retained; extended to assert that
  `coin_amount` returns `None` for a rate-less symbol.

**Not covered, deliberately:** no test asserts real blockchain confirmation, because no
such integration is introduced. Admin approval remains the trust boundary.

---

## 8. Files touched

| File | Change |
|---|---|
| `core/rails.py` | **new** — catalog and validation helpers |
| `core/models.py` | add `PaymentRail`; `Account.preferred_rail`; `Deposit`/`Withdrawal.rail` + `amount_coin`/`rate_used`; rename `amount`→`amount_usd`; remove 5 retired fields |
| `core/currency.py` | unchanged (`RAIL_CATALOG.coin_id` consumes `COIN_IDS`) |
| `core/migrations/0030_…`, `0031_…` | **new** |
| `core/views.py` | drop `wallet-type` from registration |
| `core/templates/register.html` | remove select; relabel address |
| `core/admin.py` | register `PaymentRail` |
| `user_panel/views.py` | rail resolution, per-rail validation, snapshots, drop `account_type` gate |
| `user_panel/templates/deposit.html` | multi-rail select, per-rail address, coin-amount line, USD label |
| `user_panel/templates/withdraw.html` | multi-rail select, per-rail address, coin-amount line |
| `user_panel/templates/dashboard.html`, `transactions.html` | preferred-rail display |
| `admin_panel/views.py` | per-rail settings; rail lookups; drop guard and `valid_wallet_type` |
| `admin_panel/templates/admin-settings.html` | per-rail config block; relabel `Referral Reward (USDT)` → `Referral Reward ($)` |
| `admin_panel/templates/admin-deposits.html`, `admin-withdrawals.html` | rail filter, coin column |
| `admin_panel/templates/admin-user-form.html` | preferred-rail select |
| `admin_panel/templates/admin-package-form.html` | relabel `Minimum/Maximum Amount (USDT)` → `$` |
| `core/tests.py`, `user_panel/tests.py`, `admin_panel/tests.py` | per §7 |

---

## 9. Open judgement calls

Flagged rather than silently decided:

1. **Withdrawal destination address validation (§5.5).** New behaviour, not a
   requirement. Principal benefit of per-rail support, but it can reject an address
   format the catalog does not anticipate. Fallback: length-only, as today.
2. **Catalog contents (§4.2).** Five rails seeded: USDT/TRC20, USDT/BEP20, BTC, ETH, SOL.
   USDT/ERC20 and USDC are the obvious next candidates. `USDT` appearing twice (TRC20,
   BEP20) is intentional — same coin, different rails.
3. **Address format strictness.** The BTC regex covers P2PKH/P2SH and bech32 bech32m
   (`bc1`, `bc1p`). A newer address prefix would need a catalog amendment.
