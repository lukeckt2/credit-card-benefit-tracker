"""Catalog service — browse and add cards from global templates."""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BenefitDefinition,
    BenefitSourceConfig,
    CardMaster,
    CardSourceConfig,
)
from app.services.rollover import apply_rollover
from app.schemas import RolloverRequest
from app.utils.text import normalize_name


class DuplicateCardError(Exception):
    """Raised when the user already owns a card with this template slug."""
    def __init__(self, existing_slug: str, card_id: int):
        self.existing_slug = existing_slug
        self.card_id = card_id
        super().__init__(f"Card '{existing_slug}' already exists (card_id={card_id})")


def list_issuers(session: Session) -> list[str]:
    """Return distinct issuer names from the catalog, sorted."""
    rows = session.execute(
        select(CardSourceConfig.issuer)
        .distinct()
        .order_by(CardSourceConfig.issuer)
    ).scalars().all()
    return list(rows)


def list_cards_by_issuer(session: Session, issuer: str) -> list[CardSourceConfig]:
    """Return all catalog cards for the given issuer."""
    return list(
        session.execute(
            select(CardSourceConfig)
            .where(CardSourceConfig.issuer == issuer)
            .order_by(CardSourceConfig.display_name)
        ).scalars().all()
    )


def get_card_detail(session: Session, source_id: int) -> CardSourceConfig | None:
    """Return a catalog card with its benefit templates."""
    return session.execute(
        select(CardSourceConfig).where(CardSourceConfig.source_id == source_id)
    ).scalar_one_or_none()


def _next_slug(session: Session, base_slug: str, user_id: int) -> str:
    """Generate the next available slug for a user.

    If the base slug is unused, return it. Otherwise find the highest
    numeric suffix matching ^{base_slug}(-\\d+)?$ and increment.
    """
    pattern = re.compile(rf"^{re.escape(base_slug)}(?:-(\d+))?$")
    existing_slugs = list(
        session.execute(
            select(CardMaster.slug).where(
                CardMaster.user_id == user_id,
                CardMaster.slug.like(f"{base_slug}%"),
            )
        ).scalars().all()
    )
    max_suffix = 0
    has_base = False
    for slug in existing_slugs:
        match = pattern.match(slug)
        if match:
            if match.group(1) is None:
                has_base = True
            else:
                max_suffix = max(max_suffix, int(match.group(1)))

    if not has_base:
        return base_slug
    return f"{base_slug}-{max(max_suffix + 1, 2)}"


def add_card_from_catalog(
    session: Session,
    *,
    user_id: int,
    source_id: int,
    open_date: date | None = None,
    force: bool = False,
) -> CardMaster:
    """Copy a catalog template into the user's wallet.

    Creates CardMaster + BenefitDefinitions + triggers rollover for
    the current period. Atomic — all within the caller's transaction.

    Raises DuplicateCardError if the user already has this card and
    force=False.
    """
    template = session.execute(
        select(CardSourceConfig).where(CardSourceConfig.source_id == source_id)
    ).scalar_one_or_none()
    if template is None:
        raise ValueError(f"Catalog card source_id={source_id} not found")

    # Duplicate check
    existing = session.execute(
        select(CardMaster).where(
            CardMaster.user_id == user_id,
            CardMaster.slug == template.slug,
        )
    ).scalar_one_or_none()

    if existing and not force:
        raise DuplicateCardError(existing.slug, existing.card_id)

    # Determine slug
    slug = _next_slug(session, template.slug, user_id) if existing else template.slug

    # Derive open_month and open_day
    open_month = open_date.month if open_date else None
    open_day = open_date.day if open_date else None

    # Create CardMaster
    card = CardMaster(
        user_id=user_id,
        source_id=source_id,
        slug=slug,
        display_name=template.display_name,
        card_name=template.card_name,
        issuer=template.issuer,
        annual_fee=template.annual_fee,
        status="active",
        open_date=open_date,
        open_month=open_month,
        open_day=open_day,
        source_url=template.source_url,
    )
    session.add(card)
    session.flush()  # Get card_id

    # Copy benefit templates
    benefit_templates = list(
        session.execute(
            select(BenefitSourceConfig).where(
                BenefitSourceConfig.source_id == source_id
            )
        ).scalars().all()
    )

    definition_ids = []
    for bt in benefit_templates:
        definition = BenefitDefinition(
            card_id=card.card_id,
            name=bt.name,
            normalized_name=bt.normalized_name,
            cycle_type=bt.cycle_type,
            unit=bt.unit,
            default_amount_total=bt.default_amount_total,
            amount_overrides=bt.amount_overrides,
            notes=bt.notes,
            active=True,
            # default_deadline_rule and default_period_rule intentionally left as NULL
            # so the rollover service processes these benefits normally.
        )
        session.add(definition)
        session.flush()
        definition_ids.append(definition.benefit_definition_id)

    # Auto-rollover for current period only
    # window_start = first of current month, window_end = end of current month
    if definition_ids:
        today = date.today()
        _, last_day = calendar.monthrange(today.year, today.month)
        rollover_request = RolloverRequest(
            window_start=date(today.year, today.month, 1),
            window_end=date(today.year, today.month, last_day),
            definition_ids=definition_ids,
        )
        apply_rollover(session, rollover_request, user_id=user_id)

    return card
