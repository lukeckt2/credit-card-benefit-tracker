"""Definition-only CSV import for adding a new card."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CARD_STATUSES,
    CYCLE_TYPES,
    UNITS,
    BenefitDefinition,
    BenefitPeriod,
    CardMaster,
    UsageEvent,
)
from app.schemas import RolloverRequest
from app.services.rollover import generate_candidate_periods, apply_rollover


CSV_COLUMNS = (
    "card_slug",
    "card_display_name",
    "card_card_name",
    "card_issuer",
    "card_annual_fee",
    "card_status",
    "card_open_date",
    "card_open_month",
    "card_open_day",
    "card_source_url",
    "card_notes",
    "benefit_name",
    "benefit_normalized_name",
    "benefit_cycle_type",
    "benefit_unit",
    "benefit_default_amount_total",
    "benefit_default_deadline_rule",
    "benefit_default_period_rule",
    "benefit_active",
    "benefit_notes",
)
CARD_COLUMNS = CSV_COLUMNS[:11]
FORBIDDEN_COLUMNS = {
    "period_key",
    "period_start",
    "period_end",
    "period_deadline",
    "period_amount_total",
    "period_status",
    "period_completed_at",
    "initial_used_amount",
    "initial_usage_note",
    "source_key",
}
SUPPORTED_ROLLOVER_CYCLE_TYPES = {
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "membership_year",
    "anniversary",
}


@dataclass
class WarningItem:
    type: str
    message: str
    row: int | None = None
    column: str | None = None
    value: str | None = None
    fields: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type, "message": self.message}
        if self.row is not None:
            data["row"] = self.row
        if self.column is not None:
            data["column"] = self.column
        if self.value is not None:
            data["value"] = self.value
        if self.fields is not None:
            data["fields"] = self.fields
        return data


@dataclass
class SkippedRow:
    row: int
    reason: str
    benefit_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"row": self.row, "reason": self.reason}
        if self.benefit_name:
            data["benefit_name"] = self.benefit_name
        return data


@dataclass
class CardPlan:
    slug: str
    display_name: str
    card_name: str
    issuer: str
    annual_fee: Decimal | None
    status: str
    open_date: date | None
    open_month: int | None
    open_day: int | None
    source_url: str | None
    notes: str | None
    action: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "card_name": self.card_name,
            "issuer": self.issuer,
            "annual_fee": decimal_to_json(self.annual_fee),
            "status": self.status,
            "open_date": self.open_date.isoformat() if self.open_date else None,
            "open_month": self.open_month,
            "open_day": self.open_day,
            "source_url": self.source_url,
            "notes": self.notes,
            "action": self.action,
        }


@dataclass
class DefinitionPlan:
    card_slug: str
    name: str
    normalized_name: str
    cycle_type: str
    unit: str | None
    default_amount_total: Decimal
    default_deadline_rule: str | None
    default_period_rule: str | None
    active: bool
    notes: str | None
    source_row: int
    action: str = "unknown"

    @property
    def key(self) -> tuple[str, str]:
        return (self.card_slug, self.normalized_name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_slug": self.card_slug,
            "name": self.name,
            "normalized_name": self.normalized_name,
            "cycle_type": self.cycle_type,
            "unit": self.unit,
            "default_amount_total": decimal_to_json(self.default_amount_total),
            "default_deadline_rule": self.default_deadline_rule,
            "default_period_rule": self.default_period_rule,
            "active": self.active,
            "notes": self.notes,
            "source_row": self.source_row,
            "action": self.action,
        }


@dataclass
class CurrentPeriodPlan:
    definition_key: tuple[str, str]
    benefit_name: str
    cycle_type: str
    period_key: str
    period_start: date
    period_end: date
    deadline: date
    amount_total: Decimal
    action: str = "create"

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_slug": self.definition_key[0],
            "definition_normalized_name": self.definition_key[1],
            "benefit_name": self.benefit_name,
            "cycle_type": self.cycle_type,
            "period_key": self.period_key,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "deadline": self.deadline.isoformat(),
            "amount_total": decimal_to_json(self.amount_total),
            "action": self.action,
        }


@dataclass
class CardCsvPlan:
    csv_path: Path
    as_of: date
    card: CardPlan | None = None
    definitions: list[DefinitionPlan] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)
    skipped_rows: list[SkippedRow] = field(default_factory=list)


def decimal_to_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_token(value: str | None) -> str | None:
    normalized = normalize_optional(value)
    if normalized is None:
        return None
    return normalized.lower().replace("-", "_")


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized[:255]


def parse_decimal(raw: str | None) -> Decimal | None:
    value = normalize_optional(raw)
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("$", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(raw: str | None) -> date | None:
    value = normalize_optional(raw)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_int(raw: str | None) -> int | None:
    value = normalize_optional(raw)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_bool(raw: str | None, *, default: bool) -> bool | None:
    value = normalize_optional(raw)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def add_warning(plan: CardCsvPlan, warning: WarningItem) -> None:
    plan.warnings.append(warning)


def add_skipped(
    plan: CardCsvPlan, row: int, reason: str, benefit_name: str | None = None
) -> None:
    plan.skipped_rows.append(SkippedRow(row=row, reason=reason, benefit_name=benefit_name))


def build_plan(csv_path: Path, *, as_of: date) -> CardCsvPlan:
    plan = CardCsvPlan(csv_path=csv_path, as_of=as_of)
    if not csv_path.exists() or not csv_path.is_file():
        add_warning(plan, WarningItem("missing_csv", "CSV file does not exist."))
        add_skipped(plan, 1, "missing_csv")
        return plan

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not validate_header(plan, fieldnames):
        return plan
    if not rows:
        add_warning(plan, WarningItem("empty_csv", "CSV file has no data rows."))
        add_skipped(plan, 1, "empty_csv")
        return plan

    slugs = {
        normalize_optional(row.get("card_slug"))
        for row in rows
        if normalize_optional(row.get("card_slug")) is not None
    }
    if len(slugs) != 1:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_count",
                "CSV must contain exactly one non-empty card_slug.",
                fields=sorted(slug for slug in slugs if slug),
            ),
        )
        for row_number, row in enumerate(rows, start=2):
            add_skipped(plan, row_number, "invalid_card_count", row.get("benefit_name"))
        return plan

    first_row = rows[0]
    card = parse_card(first_row, plan)
    if card is None:
        for row_number, row in enumerate(rows, start=2):
            add_skipped(plan, row_number, "invalid_card", row.get("benefit_name"))
        return plan
    plan.card = card

    first_card_values = {column: normalize_optional(first_row.get(column)) for column in CARD_COLUMNS}
    definitions_by_name: dict[str, DefinitionPlan] = {}
    for row_number, row in enumerate(rows, start=2):
        card_values = {column: normalize_optional(row.get(column)) for column in CARD_COLUMNS}
        if card_values != first_card_values:
            add_warning(
                plan,
                WarningItem(
                    "inconsistent_card_fields",
                    "All rows in a card CSV must repeat the same card-level fields.",
                    row=row_number,
                ),
            )
            add_skipped(plan, row_number, "inconsistent_card_fields", row.get("benefit_name"))
            continue

        definition = parse_definition(row, row_number, card, plan)
        if definition is None:
            add_skipped(plan, row_number, "invalid_benefit_definition", row.get("benefit_name"))
            continue

        existing_definition = definitions_by_name.get(definition.normalized_name)
        if existing_definition is not None:
            add_warning(
                plan,
                WarningItem(
                    "duplicate_definition",
                    "Duplicate benefit_normalized_name values are not allowed in one card CSV.",
                    row=row_number,
                    value=definition.normalized_name,
                ),
            )
            add_skipped(plan, row_number, "duplicate_definition", definition.name)
            continue
        definitions_by_name[definition.normalized_name] = definition

    plan.definitions = list(definitions_by_name.values())
    if not plan.definitions:
        add_warning(
            plan,
            WarningItem(
                "no_valid_definitions",
                "CSV did not produce any valid benefit definitions.",
            ),
        )
    return plan


def validate_header(plan: CardCsvPlan, fieldnames: list[str]) -> bool:
    if not fieldnames:
        add_warning(plan, WarningItem("missing_header", "CSV file has no header row."))
        add_skipped(plan, 1, "missing_header")
        return False

    expected = set(CSV_COLUMNS)
    actual = set(fieldnames)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    forbidden = sorted(actual & FORBIDDEN_COLUMNS)
    if missing or extra or forbidden:
        if missing:
            add_warning(
                plan,
                WarningItem(
                    "missing_columns",
                    "CSV header is missing required columns.",
                    row=1,
                    fields=missing,
                ),
            )
        if extra:
            add_warning(
                plan,
                WarningItem(
                    "unsupported_columns",
                    "CSV header contains unsupported columns.",
                    row=1,
                    fields=extra,
                ),
            )
        if forbidden:
            add_warning(
                plan,
                WarningItem(
                    "forbidden_period_or_usage_columns",
                    "Period and initial-usage columns are intentionally not accepted by the add-card CSV workflow.",
                    row=1,
                    fields=forbidden,
                ),
            )
        add_skipped(plan, 1, "invalid_header")
        return False
    return True


def parse_card(row: dict[str, str], plan: CardCsvPlan) -> CardPlan | None:
    required_fields = {
        "card_slug": row.get("card_slug"),
        "card_display_name": row.get("card_display_name"),
        "card_card_name": row.get("card_card_name"),
        "card_issuer": row.get("card_issuer"),
    }
    missing = [field for field, value in required_fields.items() if normalize_optional(value) is None]
    if missing:
        add_warning(
            plan,
            WarningItem("missing_card_fields", "Card is missing required fields.", row=2, fields=missing),
        )
        return None

    status = normalize_token(row.get("card_status")) or "active"
    if status not in CARD_STATUSES:
        add_warning(
            plan,
            WarningItem(
                "unsupported_card_status",
                "Card status is unsupported.",
                row=2,
                column="card_status",
                value=row.get("card_status"),
            ),
        )
        return None

    annual_fee = parse_decimal(row.get("card_annual_fee"))
    if normalize_optional(row.get("card_annual_fee")) is not None and annual_fee is None:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_annual_fee",
                "Card annual fee must be a decimal value.",
                row=2,
                column="card_annual_fee",
                value=row.get("card_annual_fee"),
            ),
        )
        return None

    open_date = parse_date(row.get("card_open_date"))
    if normalize_optional(row.get("card_open_date")) is not None and open_date is None:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_open_date",
                "Card open date must use YYYY-MM-DD.",
                row=2,
                column="card_open_date",
                value=row.get("card_open_date"),
            ),
        )
        return None

    open_month = parse_int(row.get("card_open_month"))
    if open_month is not None and not 1 <= open_month <= 12:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_open_month",
                "Card open month must be between 1 and 12.",
                row=2,
                column="card_open_month",
                value=row.get("card_open_month"),
            ),
        )
        return None
    if normalize_optional(row.get("card_open_month")) is not None and open_month is None:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_open_month",
                "Card open month must be an integer.",
                row=2,
                column="card_open_month",
                value=row.get("card_open_month"),
            ),
        )
        return None

    open_day = parse_int(row.get("card_open_day"))
    if open_day is not None and not 1 <= open_day <= 31:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_open_day",
                "Card open day must be between 1 and 31.",
                row=2,
                column="card_open_day",
                value=row.get("card_open_day"),
            ),
        )
        return None
    if normalize_optional(row.get("card_open_day")) is not None and open_day is None:
        add_warning(
            plan,
            WarningItem(
                "invalid_card_open_day",
                "Card open day must be an integer.",
                row=2,
                column="card_open_day",
                value=row.get("card_open_day"),
            ),
        )
        return None

    if open_date is not None:
        if open_month is None:
            open_month = open_date.month
        if open_day is None:
            open_day = open_date.day
        if open_month != open_date.month or open_day != open_date.day:
            add_warning(
                plan,
                WarningItem(
                    "inconsistent_card_open_date",
                    "card_open_date must match card_open_month and card_open_day when all are provided.",
                    row=2,
                ),
            )
            return None

    return CardPlan(
        slug=normalize_optional(row.get("card_slug")) or "",
        display_name=normalize_optional(row.get("card_display_name")) or "",
        card_name=normalize_optional(row.get("card_card_name")) or "",
        issuer=normalize_optional(row.get("card_issuer")) or "",
        annual_fee=annual_fee,
        status=status,
        open_date=open_date,
        open_month=open_month,
        open_day=open_day,
        source_url=normalize_optional(row.get("card_source_url")),
        notes=normalize_optional(row.get("card_notes")),
    )


def parse_definition(
    row: dict[str, str], row_number: int, card: CardPlan, plan: CardCsvPlan
) -> DefinitionPlan | None:
    required_fields = {
        "benefit_name": row.get("benefit_name"),
        "benefit_cycle_type": row.get("benefit_cycle_type"),
        "benefit_default_amount_total": row.get("benefit_default_amount_total"),
    }
    missing = [field for field, value in required_fields.items() if normalize_optional(value) is None]
    if missing:
        add_warning(
            plan,
            WarningItem(
                "missing_benefit_fields",
                "Benefit definition is missing required fields.",
                row=row_number,
                fields=missing,
            ),
        )
        return None

    cycle_type = normalize_token(row.get("benefit_cycle_type"))
    if cycle_type not in CYCLE_TYPES:
        add_warning(
            plan,
            WarningItem(
                "unsupported_cycle_type",
                "Benefit cycle type is unsupported.",
                row=row_number,
                column="benefit_cycle_type",
                value=row.get("benefit_cycle_type"),
            ),
        )
        return None

    unit = normalize_token(row.get("benefit_unit"))
    if unit is not None and unit not in UNITS:
        add_warning(
            plan,
            WarningItem(
                "unsupported_unit",
                "Benefit unit is unsupported.",
                row=row_number,
                column="benefit_unit",
                value=row.get("benefit_unit"),
            ),
        )
        return None

    amount_total = parse_decimal(row.get("benefit_default_amount_total"))
    if amount_total is None or amount_total < 0:
        add_warning(
            plan,
            WarningItem(
                "invalid_benefit_default_amount_total",
                "Benefit default amount total must be a non-negative decimal value.",
                row=row_number,
                column="benefit_default_amount_total",
                value=row.get("benefit_default_amount_total"),
            ),
        )
        return None

    active = parse_bool(row.get("benefit_active"), default=True)
    if active is None:
        add_warning(
            plan,
            WarningItem(
                "invalid_benefit_active",
                "Benefit active must be true or false when provided.",
                row=row_number,
                column="benefit_active",
                value=row.get("benefit_active"),
            ),
        )
        return None

    default_deadline_rule = normalize_optional(row.get("benefit_default_deadline_rule"))
    default_period_rule = normalize_optional(row.get("benefit_default_period_rule"))
    if default_deadline_rule or default_period_rule:
        add_warning(
            plan,
            WarningItem(
                "unsupported_custom_rule_fields",
                "Custom period/deadline rule fields must stay blank until a structured format is approved.",
                row=row_number,
                fields=[
                    field
                    for field, value in (
                        ("benefit_default_deadline_rule", default_deadline_rule),
                        ("benefit_default_period_rule", default_period_rule),
                    )
                    if value
                ],
            ),
        )
        return None

    name = normalize_optional(row.get("benefit_name")) or ""
    normalized_name = normalize_optional(row.get("benefit_normalized_name")) or normalize_name(name)
    normalized_name = normalize_name(normalized_name)

    if cycle_type in {"membership_year", "anniversary"} and (
        card.open_month is None or card.open_day is None
    ):
        add_warning(
            plan,
            WarningItem(
                "missing_open_month_day",
                "Membership-year and anniversary benefits can be imported, but current periods cannot be generated without card open month/day.",
                row=row_number,
                value=name,
            ),
        )

    return DefinitionPlan(
        card_slug=card.slug,
        name=name,
        normalized_name=normalized_name,
        cycle_type=cycle_type,
        unit=unit,
        default_amount_total=amount_total,
        default_deadline_rule=None,
        default_period_rule=None,
        active=active,
        notes=normalize_optional(row.get("benefit_notes")),
        source_row=row_number,
    )


def db_counts(session: Session) -> dict[str, int]:
    return {
        "card_master": session.scalar(select(func.count()).select_from(CardMaster)) or 0,
        "benefit_definitions": session.scalar(select(func.count()).select_from(BenefitDefinition)) or 0,
        "benefit_periods": session.scalar(select(func.count()).select_from(BenefitPeriod)) or 0,
        "usage_events": session.scalar(select(func.count()).select_from(UsageEvent)) or 0,
    }


def annotate_actions(plan: CardCsvPlan, session: Session) -> None:
    if plan.card is None:
        return

    existing_card = session.scalar(select(CardMaster).where(CardMaster.slug == plan.card.slug))
    if existing_card is None:
        plan.card.action = "create"
        for definition in plan.definitions:
            definition.action = "create"
        return

    plan.card.action = "exists" if card_matches(existing_card, plan.card) else "conflict"
    existing_definitions = {
        definition.normalized_name: definition
        for definition in session.scalars(
            select(BenefitDefinition).where(
                BenefitDefinition.card_id == existing_card.card_id,
                BenefitDefinition.normalized_name.in_(
                    [definition.normalized_name for definition in plan.definitions]
                ),
            )
        )
    }
    for definition in plan.definitions:
        existing_definition = existing_definitions.get(definition.normalized_name)
        if existing_definition is None:
            definition.action = "create"
        elif definition_matches(existing_definition, definition):
            definition.action = "exists"
        else:
            definition.action = "conflict"


def card_matches(existing: CardMaster, planned: CardPlan) -> bool:
    return all(
        (
            existing.display_name == planned.display_name,
            existing.card_name == planned.card_name,
            existing.issuer == planned.issuer,
            decimal_equal(existing.annual_fee, planned.annual_fee),
            existing.status == planned.status,
            existing.open_date == planned.open_date,
            existing.open_month == planned.open_month,
            existing.open_day == planned.open_day,
            existing.source_url == planned.source_url,
            existing.notes == planned.notes,
        )
    )


def definition_matches(existing: BenefitDefinition, planned: DefinitionPlan) -> bool:
    return all(
        (
            existing.name == planned.name,
            existing.cycle_type == planned.cycle_type,
            existing.unit == planned.unit,
            decimal_equal(existing.default_amount_total, planned.default_amount_total),
            existing.default_deadline_rule == planned.default_deadline_rule,
            existing.default_period_rule == planned.default_period_rule,
            bool(existing.active) == planned.active,
            existing.notes == planned.notes,
        )
    )


def decimal_equal(left: Decimal | int | float | str | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return Decimal(str(left)) == right


def current_period_plans(plan: CardCsvPlan, session: Session) -> list[CurrentPeriodPlan]:
    if plan.card is None:
        return []

    existing_period_keys = existing_period_keys_by_definition(plan, session)
    periods: list[CurrentPeriodPlan] = []
    for definition in plan.definitions:
        if definition.cycle_type not in SUPPORTED_ROLLOVER_CYCLE_TYPES:
            continue
        if definition.action == "conflict":
            continue
        candidates = generate_candidate_periods(
            definition.cycle_type,
            plan.as_of,
            plan.as_of,
            open_month=plan.card.open_month,
            open_day=plan.card.open_day,
        )
        for candidate in candidates:
            action = (
                "exists"
                if candidate.period_key in existing_period_keys.get(definition.normalized_name, set())
                else "create"
            )
            periods.append(
                CurrentPeriodPlan(
                    definition_key=definition.key,
                    benefit_name=definition.name,
                    cycle_type=definition.cycle_type,
                    period_key=candidate.period_key,
                    period_start=candidate.period_start,
                    period_end=candidate.period_end,
                    deadline=candidate.deadline,
                    amount_total=definition.default_amount_total,
                    action=action,
                )
            )
    return periods


def existing_period_keys_by_definition(
    plan: CardCsvPlan, session: Session
) -> dict[str, set[str]]:
    if plan.card is None:
        return {}
    card = session.scalar(select(CardMaster).where(CardMaster.slug == plan.card.slug))
    if card is None:
        return {}
    definitions = list(
        session.scalars(
            select(BenefitDefinition).where(
                BenefitDefinition.card_id == card.card_id,
                BenefitDefinition.normalized_name.in_(
                    [definition.normalized_name for definition in plan.definitions]
                ),
            )
        )
    )
    definition_ids = [definition.benefit_definition_id for definition in definitions]
    if not definition_ids:
        return {}
    normalized_by_id = {
        definition.benefit_definition_id: definition.normalized_name
        for definition in definitions
    }
    result = {definition.normalized_name: set() for definition in definitions}
    for period in session.scalars(
        select(BenefitPeriod).where(BenefitPeriod.benefit_definition_id.in_(definition_ids))
    ):
        normalized_name = normalized_by_id[period.benefit_definition_id]
        result[normalized_name].add(period.period_key)
    return result


def summarize_actions(items: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter(item.action for item in items).items()))


def output_warnings(plan: CardCsvPlan) -> list[WarningItem]:
    warnings = list(plan.warnings)
    if plan.card and plan.card.action == "conflict":
        warnings.append(
            WarningItem(
                "card_conflict",
                "Existing card row differs from the CSV; apply is blocked to avoid overwriting data.",
                value=plan.card.slug,
            )
        )
    for definition in plan.definitions:
        if definition.action == "conflict":
            warnings.append(
                WarningItem(
                    "benefit_definition_conflict",
                    "Existing benefit definition differs from the CSV; apply is blocked to avoid overwriting data.",
                    row=definition.source_row,
                    value=definition.normalized_name,
                )
            )
        if definition.cycle_type in {"cert", "multi_year"}:
            warnings.append(
                WarningItem(
                    "fixed_period_not_generated",
                    "Certificate and multi-year benefits can be imported, but current periods are not generated without explicit fixed periods or approved recurrence rules.",
                    row=definition.source_row,
                    value=definition.normalized_name,
                )
            )
    return warnings


def warning_types(warnings: list[WarningItem]) -> dict[str, int]:
    return dict(sorted(Counter(warning.type for warning in warnings).items()))


def has_conflicts(plan: CardCsvPlan) -> bool:
    return bool(
        (plan.card and plan.card.action == "conflict")
        or any(definition.action == "conflict" for definition in plan.definitions)
    )


def has_blocking_issues(plan: CardCsvPlan) -> bool:
    return plan.card is None or not plan.definitions or bool(plan.skipped_rows) or has_conflicts(plan)


def plan_output(
    plan: CardCsvPlan, session: Session, *, include_details: bool
) -> dict[str, Any]:
    annotate_actions(plan, session)
    current_periods = current_period_plans(plan, session)
    warnings = output_warnings(plan)
    output: dict[str, Any] = {
        "csv_path": str(plan.csv_path),
        "as_of": plan.as_of.isoformat(),
        "summary": {
            "planned_cards": 1 if plan.card else 0,
            "planned_benefit_definitions": len(plan.definitions),
            "planned_current_periods": len(current_periods),
            "warnings": len(warnings),
            "skipped_rows": len(plan.skipped_rows),
            "blocking_issues": has_blocking_issues(plan),
        },
        "actions": {
            "cards": summarize_actions([plan.card] if plan.card else []),
            "benefit_definitions": summarize_actions(plan.definitions),
            "current_periods": summarize_actions(current_periods),
        },
        "database_counts": db_counts(session),
        "warning_types": warning_types(warnings),
        "warnings": [warning.as_dict() for warning in warnings],
        "skipped_rows": [row.as_dict() for row in plan.skipped_rows],
    }
    if include_details:
        output["planned_records"] = {
            "card": plan.card.as_dict() if plan.card else None,
            "benefit_definitions": [definition.as_dict() for definition in plan.definitions],
            "current_periods": [period.as_dict() for period in current_periods],
        }
    return output


def apply_plan(plan: CardCsvPlan, session: Session) -> dict[str, Any]:
    before_counts = db_counts(session)
    annotate_actions(plan, session)
    warnings = output_warnings(plan)
    if has_blocking_issues(plan):
        return {
            "applied": False,
            "blocked": True,
            "before_counts": before_counts,
            "after_counts": db_counts(session),
            "actions": {
                "cards": summarize_actions([plan.card] if plan.card else []),
                "benefit_definitions": summarize_actions(plan.definitions),
            },
            "warnings": [warning.as_dict() for warning in warnings],
            "skipped_rows": [row.as_dict() for row in plan.skipped_rows],
        }

    session.rollback()
    rollover_response = None
    created_cards = 0
    created_definitions = 0
    with session.begin():
        assert plan.card is not None
        card = session.scalar(select(CardMaster).where(CardMaster.slug == plan.card.slug))
        if card is None:
            card = CardMaster(slug=plan.card.slug)
            session.add(card)
            created_cards = 1
        set_card_fields(card, plan.card)
        session.flush()

        imported_definitions: list[BenefitDefinition] = []
        for definition_plan in plan.definitions:
            definition = session.scalar(
                select(BenefitDefinition).where(
                    BenefitDefinition.card_id == card.card_id,
                    BenefitDefinition.normalized_name == definition_plan.normalized_name,
                )
            )
            if definition is None:
                definition = BenefitDefinition(
                    card_id=card.card_id,
                    normalized_name=definition_plan.normalized_name,
                )
                session.add(definition)
                created_definitions += 1
            set_definition_fields(definition, definition_plan)
            imported_definitions.append(definition)
        session.flush()

        definition_ids = [definition.benefit_definition_id for definition in imported_definitions]
        if definition_ids:
            rollover_response = apply_rollover(
                session,
                RolloverRequest(
                    window_start=plan.as_of,
                    window_end=plan.as_of,
                    definition_ids=definition_ids,
                ),
            )

    return {
        "applied": True,
        "blocked": False,
        "before_counts": before_counts,
        "after_counts": db_counts(session),
        "created_cards": created_cards,
        "created_benefit_definitions": created_definitions,
        "rollover": rollover_response.model_dump(mode="json") if rollover_response else None,
        "warnings": [warning.as_dict() for warning in output_warnings(plan)],
        "skipped_rows": [row.as_dict() for row in plan.skipped_rows],
    }


def set_card_fields(card: CardMaster, plan: CardPlan) -> None:
    card.display_name = plan.display_name
    card.card_name = plan.card_name
    card.issuer = plan.issuer
    card.annual_fee = plan.annual_fee
    card.status = plan.status
    card.open_date = plan.open_date
    card.open_month = plan.open_month
    card.open_day = plan.open_day
    card.source_url = plan.source_url
    card.notes = plan.notes


def set_definition_fields(definition: BenefitDefinition, plan: DefinitionPlan) -> None:
    definition.name = plan.name
    definition.cycle_type = plan.cycle_type
    definition.unit = plan.unit
    definition.default_amount_total = plan.default_amount_total
    definition.default_deadline_rule = plan.default_deadline_rule
    definition.default_period_rule = plan.default_period_rule
    definition.active = plan.active
    definition.notes = plan.notes


def reconcile_plan(plan: CardCsvPlan, session: Session) -> dict[str, Any]:
    annotate_actions(plan, session)
    warnings = output_warnings(plan)
    issues: list[dict[str, Any]] = []
    if plan.card is None:
        issues.append({"type": "missing_planned_card"})
    else:
        card = session.scalar(select(CardMaster).where(CardMaster.slug == plan.card.slug))
        if card is None:
            issues.append({"type": "missing_card", "slug": plan.card.slug})
        elif not card_matches(card, plan.card):
            issues.append({"type": "card_field_mismatch", "slug": plan.card.slug})

        if card is not None:
            for definition_plan in plan.definitions:
                definition = session.scalar(
                    select(BenefitDefinition).where(
                        BenefitDefinition.card_id == card.card_id,
                        BenefitDefinition.normalized_name == definition_plan.normalized_name,
                    )
                )
                if definition is None:
                    issues.append(
                        {
                            "type": "missing_benefit_definition",
                            "card_slug": definition_plan.card_slug,
                            "normalized_name": definition_plan.normalized_name,
                        }
                    )
                    continue
                if not definition_matches(definition, definition_plan):
                    issues.append(
                        {
                            "type": "benefit_definition_field_mismatch",
                            "card_slug": definition_plan.card_slug,
                            "normalized_name": definition_plan.normalized_name,
                        }
                    )

    for period_plan in current_period_plans(plan, session):
        if period_plan.action != "exists":
            issues.append(
                {
                    "type": "missing_current_period",
                    "card_slug": period_plan.definition_key[0],
                    "normalized_name": period_plan.definition_key[1],
                    "period_key": period_plan.period_key,
                }
            )

    return {
        "csv_path": str(plan.csv_path),
        "as_of": plan.as_of.isoformat(),
        "summary": {
            "expected_cards": 1 if plan.card else 0,
            "expected_benefit_definitions": len(plan.definitions),
            "warnings": len(warnings),
            "skipped_rows": len(plan.skipped_rows),
            "issues": len(issues),
        },
        "database_counts": db_counts(session),
        "warning_types": warning_types(warnings),
        "issues": issues,
        "warnings": [warning.as_dict() for warning in warnings],
        "skipped_rows": [row.as_dict() for row in plan.skipped_rows],
    }
