"""Email alert workflows for expiring benefit periods."""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenefitDefinition, BenefitPeriod, CardMaster, User
from app.services.usage import remaining_amount_for_period

logger = logging.getLogger(__name__)

def send_email(to_address: str, subject: str, body: str) -> None:
    smtp_server = os.environ.get("SMTP_SERVER", "localhost")
    smtp_port = int(os.environ.get("SMTP_PORT", "1025"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    from_address = os.environ.get("SMTP_FROM", "alerts@creditcardbenefits.local")

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if smtp_port == 587 or smtp_port == 25:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logger.info(f"Sent expiration alert to {to_address}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_address}: {e}")

def check_and_send_expiration_alerts(session: Session, days_ahead: int = 15) -> None:
    target_date = date.today() + timedelta(days=days_ahead)

    stmt = (
        select(BenefitPeriod)
        .join(BenefitDefinition)
        .join(CardMaster)
        .join(User)
        .where(BenefitPeriod.deadline == target_date)
        .where(BenefitPeriod.status == "pending")
    )

    expiring_periods: Sequence[BenefitPeriod] = session.scalars(stmt).all()

    for period in expiring_periods:
        amount_remaining = remaining_amount_for_period(session, period)
        if amount_remaining <= 0:
            continue

        definition = period.benefit_definition
        card = definition.card
        user = card.user

        if not user.email:
            continue

        subject = f"Alert: Benefit expiring in {days_ahead} days for {card.card_name}"
        body = (
            f"Hello {user.username},\n\n"
            f"Your benefit '{definition.name}' for the card '{card.card_name}' "
            f"is expiring on {period.deadline.isoformat()}.\n\n"
            f"Amount remaining: {amount_remaining}\n"
            f"Please remember to use it!\n"
        )

        send_email(user.email, subject, body)
