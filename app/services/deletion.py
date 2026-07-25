"""Destructive entity cleanup workflows."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BenefitDefinition, BenefitPeriod, CardMaster, UsageEvent
from app.services.errors import NotFoundError


def delete_benefit_definition(session: Session, benefit_definition_id: int, *, user_id: int) -> None:
    row = session.execute(
        select(BenefitDefinition)
        .join(CardMaster)
        .where(BenefitDefinition.benefit_definition_id == benefit_definition_id)
        .where(CardMaster.user_id == user_id)
    ).first()
    if row is None:
        raise NotFoundError(
            f"Benefit definition {benefit_definition_id} was not found."
        )
    definition = row[0]

    period_ids = list(
        session.scalars(
            select(BenefitPeriod.benefit_period_id).where(
                BenefitPeriod.benefit_definition_id == benefit_definition_id
            )
        )
    )
    if period_ids:
        session.execute(
            delete(UsageEvent).where(UsageEvent.benefit_period_id.in_(period_ids))
        )

    session.execute(
        delete(BenefitPeriod).where(
            BenefitPeriod.benefit_definition_id == benefit_definition_id
        )
    )
    session.delete(definition)
    session.flush()


def delete_card(session: Session, card_id: int, *, user_id: int) -> None:
    card = session.execute(
        select(CardMaster)
        .where(CardMaster.card_id == card_id)
        .where(CardMaster.user_id == user_id)
    ).scalar_one_or_none()
    if card is None:
        raise NotFoundError(f"Card {card_id} was not found.")

    definition_ids = list(
        session.scalars(
            select(BenefitDefinition.benefit_definition_id).where(
                BenefitDefinition.card_id == card_id
            )
        )
    )
    if definition_ids:
        period_ids = list(
            session.scalars(
                select(BenefitPeriod.benefit_period_id).where(
                    BenefitPeriod.benefit_definition_id.in_(definition_ids)
                )
            )
        )
        if period_ids:
            session.execute(
                delete(UsageEvent).where(UsageEvent.benefit_period_id.in_(period_ids))
            )
        session.execute(
            delete(BenefitPeriod).where(
                BenefitPeriod.benefit_definition_id.in_(definition_ids)
            )
        )
        session.execute(
            delete(BenefitDefinition).where(
                BenefitDefinition.benefit_definition_id.in_(definition_ids)
            )
        )

    session.delete(card)
    session.flush()
