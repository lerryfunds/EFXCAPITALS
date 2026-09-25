from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import InvestmentPayout, Transaction, userPackage


class Command(BaseCommand):
    help = "Audit investment ROI and principal records without changing financial data."

    def add_arguments(self, parser):
        parser.add_argument("--investment", dest="investment_id")
        parser.add_argument("--user", dest="user_id")
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--fail-on-discrepancy",
            action="store_true",
            dest="fail_on_discrepancy",
        )

    def handle(self, *args, **options):
        queryset = userPackage.objects.select_related("package", "user__user")
        if options["investment_id"]:
            queryset = queryset.filter(pk=options["investment_id"])
        if options["user_id"]:
            queryset = queryset.filter(user__user_id=options["user_id"])

        now = timezone.now()
        findings = []
        expected_total = Decimal("0.00")
        recorded_total = Decimal("0.00")
        ledger_total = Decimal("0.00")

        for investment in queryset.order_by("pk"):
            cycle = investment.effective_cycle()
            interval = investment.effective_interval()
            if cycle <= 0 or interval <= 0:
                findings.append(
                    self.finding(
                        investment,
                        "invalid_terms",
                        f"cycle={cycle}, interval={interval}",
                    )
                )
                continue

            elapsed = max(now - investment.date_activated, timedelta())
            try:
                elapsed_cycles = min(elapsed // timedelta(hours=interval), cycle)
            except (OverflowError, TypeError, ValueError):
                findings.append(
                    self.finding(
                        investment,
                        "invalid_terms",
                        f"cycle={cycle}, interval={interval}",
                    )
                )
                continue
            per_cycle = (
                investment.amount * investment.effective_roi() / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            expected_roi = per_cycle * elapsed_cycles
            expected_principal = (
                investment.amount if elapsed_cycles >= cycle else Decimal("0.00")
            )
            expected = expected_roi + expected_principal

            payout_rows = list(
                InvestmentPayout.objects.filter(investment=investment).values(
                    "id",
                    "transaction_id",
                    "kind",
                    "cycle_number",
                    "amount",
                )
            )
            payout_transactions = {
                row["transaction_id"]: Transaction.objects.filter(pk=row["transaction_id"]).first()
                for row in payout_rows
            }
            recorded_roi = sum(
                (
                    row["amount"]
                    for row in payout_rows
                    if row["kind"] == InvestmentPayout.Kind.ROI
                ),
                Decimal("0.00"),
            )
            recorded_principal = sum(
                (
                    row["amount"]
                    for row in payout_rows
                    if row["kind"] == InvestmentPayout.Kind.PRINCIPAL
                ),
                Decimal("0.00"),
            )
            ledger_rows = list(
                Transaction.objects.filter(
                    related_id=investment.id,
                    tx_type__in=["ROI", "PRINCIPAL"],
                    status="COMPLETED",
                ).values("id", "tx_type", "amount")
            )
            ledger_roi = sum(
                (row["amount"] for row in ledger_rows if row["tx_type"] == "ROI"),
                Decimal("0.00"),
            )
            ledger_principal = sum(
                (
                    row["amount"]
                    for row in ledger_rows
                    if row["tx_type"] == "PRINCIPAL"
                ),
                Decimal("0.00"),
            )
            recorded = recorded_roi + recorded_principal
            ledger = ledger_roi + ledger_principal
            expected_total += expected
            recorded_total += recorded
            ledger_total += ledger

            for row in payout_rows:
                transaction_record = payout_transactions[row["transaction_id"]]
                expected_type = row["kind"]
                if (
                    transaction_record is None
                    or transaction_record.tx_type != expected_type
                    or transaction_record.related_id != investment.id
                    or transaction_record.status != "COMPLETED"
                    or transaction_record.amount != row["amount"]
                ):
                    findings.append(
                        self.finding(
                            investment,
                            "payout_transaction_mismatch",
                            f"payout={row['id']}, transaction={row['transaction_id']}",
                        )
                    )

            payout_transaction_ids = {row["transaction_id"] for row in payout_rows}
            if any(row["id"] not in payout_transaction_ids for row in ledger_rows):
                findings.append(
                    self.finding(
                        investment,
                        "orphan_ledger_rows",
                        "completed ROI or principal transactions lack payout records",
                    )
                )
            if ledger != recorded:
                findings.append(
                    self.finding(
                        investment,
                        "ledger_mismatch",
                        f"recorded={recorded}, ledger={ledger}",
                    )
                )

            roi_cycle_numbers = sorted(
                row["cycle_number"]
                for row in payout_rows
                if row["kind"] == InvestmentPayout.Kind.ROI
            )
            expected_roi_cycles = list(range(1, elapsed_cycles + 1))
            if roi_cycle_numbers != expected_roi_cycles:
                findings.append(
                    self.finding(
                        investment,
                        "cycle_sequence_mismatch",
                        f"recorded={roi_cycle_numbers}, expected={expected_roi_cycles}",
                    )
                )
            principal_rows = [
                row
                for row in payout_rows
                if row["kind"] == InvestmentPayout.Kind.PRINCIPAL
            ]
            if any(row["cycle_number"] != 0 for row in principal_rows):
                findings.append(
                    self.finding(
                        investment,
                        "principal_cycle_mismatch",
                        "principal payout must use cycle 0",
                    )
                )

            if recorded != expected:
                findings.append(
                    self.finding(
                        investment,
                        "amount_mismatch",
                        f"expected={expected}, recorded={recorded}, "
                        f"roi_ledger={ledger_roi}, principal_ledger={ledger_principal}",
                    )
                )
            if elapsed_cycles > investment.days:
                findings.append(
                    self.finding(
                        investment,
                        "cycle_counter_behind",
                        f"elapsed={elapsed_cycles}, recorded_days={investment.days}",
                    )
                )
            elif investment.days > elapsed_cycles:
                findings.append(
                    self.finding(
                        investment,
                        "cycle_counter_ahead",
                        f"elapsed={elapsed_cycles}, recorded_days={investment.days}",
                    )
                )
            if expected_principal and not recorded_principal:
                findings.append(
                    self.finding(investment, "missing_principal", "principal not recorded")
                )
            if expected_roi and not recorded_roi:
                findings.append(
                    self.finding(investment, "missing_roi", "ROI not recorded")
                )

        report = {
            "examined": queryset.count(),
            "expected_total": str(expected_total),
            "recorded_total": str(recorded_total),
            "ledger_total": str(ledger_total),
            "discrepancies": findings,
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(report, default=str))
        else:
            self.stdout.write(
                f"Examined {report['examined']} investment(s); "
                f"expected {report['expected_total']}, recorded {report['recorded_total']}, "
                f"ledger {report['ledger_total']}."
            )
            for item in findings:
                self.stdout.write(
                    f"{item['investment_id']} {item['kind']}: {item['detail']}"
                )

        if options["fail_on_discrepancy"] and findings:
            raise CommandError("ROI audit found discrepancies")

    def finding(self, investment, kind, detail):
        return {
            "investment_id": str(investment.pk),
            "user": investment.user.user.username,
            "kind": kind,
            "detail": detail,
        }
