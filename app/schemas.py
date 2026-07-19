"""Pydantic request and response contracts for the runtime API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CardStatus = Literal["active", "inactive", "closed"]
CycleType = Literal[
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "membership_year",
    "anniversary",
    "cert",
    "multi_year",
]
PeriodStatus = Literal["pending", "completed", "skipped", "expired"]
ManualUsageEventType = Literal["usage", "adjustment", "correction"]
UsageEventType = Literal["import_initial", "usage", "adjustment", "correction"]


def decimal_to_api(value: Decimal | int | float | str | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardRead(BaseModel):
    card_id: int
    slug: str
    display_name: str
    card_name: str
    issuer: str
    annual_fee: float | None
    status: CardStatus
    open_date: date | None
    open_month: int | None
    open_day: int | None
    source_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CardListResponse(BaseModel):
    cards: list[CardRead]


class BenefitDefinitionSummary(BaseModel):
    benefit_definition_id: int
    card_id: int
    name: str
    normalized_name: str
    cycle_type: CycleType
    unit: str | None
    default_amount_total: float
    active: bool


class BenefitDefinitionRead(BenefitDefinitionSummary):
    default_deadline_rule: str | None
    default_period_rule: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    card: CardRead | None = None


class BenefitDefinitionListResponse(BaseModel):
    benefit_definitions: list[BenefitDefinitionRead]


class UsageTotals(BaseModel):
    amount_used: float
    amount_remaining: float


class BenefitPeriodSummary(BaseModel):
    benefit_period_id: int
    benefit_definition_id: int
    period_key: str
    period_start: date
    period_end: date
    deadline: date
    amount_total: float
    status: PeriodStatus
    completed_at: datetime | None
    amount_used: float
    amount_remaining: float


class BenefitPeriodRead(BenefitPeriodSummary):
    created_at: datetime
    updated_at: datetime
    card: CardRead | None = None
    benefit_definition: BenefitDefinitionSummary | None = None


class BenefitPeriodListResponse(BaseModel):
    benefit_periods: list[BenefitPeriodRead]


class BenefitDefinitionWithPeriods(BenefitDefinitionRead):
    periods: list[BenefitPeriodSummary]


class CardDetail(CardRead):
    benefit_definitions: list[BenefitDefinitionWithPeriods]


class DashboardRow(BaseModel):
    period_id: int
    benefit_definition_id: int
    card_id: int
    card_name: str
    issuer: str
    benefit_name: str
    cycle_type: CycleType
    unit: str | None
    period_key: str
    period_start: date
    period_end: date
    amount_total: float
    amount_used: float
    amount_remaining: float
    deadline: date
    days_until_deadline: int
    status: PeriodStatus
    completed_at: datetime | None
    priority: str
    is_current: bool
    is_pending: bool
    is_completed: bool


class DashboardSection(BaseModel):
    key: str
    title: str
    rows: list[DashboardRow]


class DashboardResponse(BaseModel):
    as_of: date
    sections: list[DashboardSection]


class PeriodUpdate(StrictBaseModel):
    period_start: date | None = None
    period_end: date | None = None
    deadline: date | None = None
    amount_total: Decimal | None = Field(default=None, ge=0)
    status: PeriodStatus | None = None

    @model_validator(mode="after")
    def require_update(self) -> "PeriodUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("At least one period field must be provided.")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end.")
        return self


class UsageEventCreate(StrictBaseModel):
    amount_delta: Decimal
    note: str | None = None
    used_at: datetime | None = None
    source_key: str | None = Field(default=None, max_length=512)


class UsageAdjustmentCreate(StrictBaseModel):
    current_used_amount: Decimal
    event_type: Literal["adjustment", "correction"] = "adjustment"
    note: str | None = None
    used_at: datetime | None = None
    source_key: str | None = Field(default=None, max_length=512)


class UsageEventRead(BaseModel):
    usage_event_id: int
    benefit_period_id: int
    event_type: UsageEventType
    amount_delta: float
    note: str | None
    used_at: datetime
    source_key: str | None
    created_at: datetime


class UsageEventListResponse(BaseModel):
    usage_events: list[UsageEventRead]


class UsageMutationResponse(BaseModel):
    usage_event: UsageEventRead
    period: BenefitPeriodRead


class RolloverRequest(StrictBaseModel):
    window_start: date
    window_end: date
    definition_ids: list[int] | None = None
    include_inactive_cards: bool = False
    include_inactive_definitions: bool = False
    only_periods_starting_in_window: bool = False

    @model_validator(mode="after")
    def validate_window(self) -> "RolloverRequest":
        if self.window_start > self.window_end:
            raise ValueError("window_start must be on or before window_end.")
        return self


class RolloverWarning(BaseModel):
    type: str
    message: str
    benefit_definition_id: int | None = None
    card_id: int | None = None


class RolloverPeriod(BaseModel):
    action: Literal["create", "exists"]
    benefit_definition_id: int
    card_id: int
    card_name: str
    benefit_name: str
    cycle_type: CycleType
    period_key: str
    period_start: date
    period_end: date
    deadline: date
    amount_total: float


class RolloverResponse(BaseModel):
    dry_run: bool
    window_start: date
    window_end: date
    would_create: int
    created: int
    existing: int
    skipped: int
    not_due: int
    warnings: list[RolloverWarning]
    periods: list[RolloverPeriod]
