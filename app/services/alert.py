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

    from collections import defaultdict

    expiring_periods: Sequence[BenefitPeriod] = session.scalars(stmt).all()

    user_alerts = defaultdict(list)

    for period in expiring_periods:
        amount_remaining = remaining_amount_for_period(session, period)
        if amount_remaining <= 0:
            continue

        definition = period.benefit_definition
        card = definition.card
        user = card.user

        if not user.email:
            continue

        user_alerts[user].append({
            "card_name": card.card_name,
            "benefit_name": definition.name,
            "deadline": period.deadline.isoformat(),
            "amount_remaining": amount_remaining,
        })

    for user, alerts in user_alerts.items():
        if len(alerts) == 1:
            subject = f"Alert: 1 benefit expiring in {days_ahead} days"
        else:
            subject = f"Alert: {len(alerts)} benefits expiring in {days_ahead} days"

        body = f"Hello {user.username},\n\n"
        body += f"You have {len(alerts)} benefit(s) expiring in {days_ahead} days:\n\n"

        for alert in alerts:
            body += f"- Card: {alert['card_name']}\n"
            body += f"  Benefit: {alert['benefit_name']}\n"
            body += f"  Deadline: {alert['deadline']}\n"
            body += f"  Remaining Amount: {alert['amount_remaining']}\n\n"

        body += "Please remember to use them!\n"

        send_email(user.email, subject, body)
