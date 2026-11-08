import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import func, select

from fraud_api.config import get_settings
from fraud_api.contracts import Contract, Transaction
from fraud_api.errors import ApiError
from fraud_api.models import Alert, DemoSession, ScoredTransaction
from fraud_api.scoring import Scorer, ScoreResult, get_scorer
from fraud_api.sessions import Database, require_session

router = APIRouter(prefix="/v1", tags=["transactions"])
CurrentSession = Annotated[DemoSession, Depends(require_session)]


@router.post("/transactions/score", response_model=ScoreResult)
def score_transaction(
    body: Transaction,
    db: Database,
    session: CurrentSession,
    scorer: Annotated[Scorer, Depends(get_scorer)],
) -> ScoreResult:
    # Serialize writes per session: history, cap checks and retries see one order.
    locked = db.scalar(select(DemoSession).where(DemoSession.id == session.id).with_for_update())
    if locked is None or locked.expires_at <= datetime.now(UTC):
        raise ApiError(401, "SESSION_EXPIRED", "Session is invalid or expired")
    existing = db.scalar(
        select(ScoredTransaction).where(
            ScoredTransaction.session_id == session.id,
            ScoredTransaction.client_transaction_id == body.client_transaction_id,
        )
    )
    payload = body.model_dump(mode="json")
    if existing:
        if existing.payload != payload:
            raise ApiError(
                409, "IDEMPOTENCY_CONFLICT", "Transaction ID was used with different input"
            )
        return ScoreResult.model_validate(existing.result)
    count = db.scalar(
        select(func.count())
        .select_from(ScoredTransaction)
        .where(
            ScoredTransaction.session_id == session.id,
        )
    )
    if count is not None and count >= get_settings().max_transactions_per_session:
        raise ApiError(429, "SESSION_LIMIT", "This session has reached its transaction limit")
    history = db.scalars(
        select(ScoredTransaction).where(
            ScoredTransaction.session_id == session.id,
            ScoredTransaction.account_id == body.account_id,
            ScoredTransaction.run_id == body.run_id,
            ScoredTransaction.event_at < body.timestamp,
        )
    ).all()
    result = scorer.score(
        body, [Transaction.model_validate(row.payload) for row in history], uuid4()
    )
    if result.recommendation == "review":
        result = result.model_copy(update={"alert_id": uuid4()})
    row = ScoredTransaction(
        id=result.transaction_id,
        session_id=session.id,
        client_transaction_id=body.client_transaction_id,
        account_id=body.account_id,
        run_id=body.run_id,
        event_at=body.timestamp,
        received_at=datetime.now(UTC),
        payload=payload,
        result=result.model_dump(mode="json"),
        risk_score=result.risk_score,
        recommendation=result.recommendation,
    )
    db.add(row)
    db.flush()
    if result.alert_id:
        db.add(Alert(id=result.alert_id, transaction_sequence=row.sequence))
    db.commit()
    return result


class TransactionItem(Contract):
    transaction: Transaction
    received_at: datetime
    score: ScoreResult
    feedback: Literal["fraud", "legitimate"] | None


class Page(Contract):
    items: list[TransactionItem]
    next_cursor: str | None


def cursor_sequence(cursor: str) -> int:
    try:
        value = int(base64.b64decode(cursor, altchars=b"-_", validate=True).decode())
        if not 0 < value <= 2**63 - 1:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(422, "INVALID_CURSOR", "Pagination cursor is invalid") from exc


@router.get("/transactions", response_model=Page)
@router.get("/alerts", response_model=Page)
def list_transactions(
    db: Database,
    session: CurrentSession,
    # A shared implementation keeps transaction and alert filtering consistent.
    request: Request,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    recommendation: Literal["clear", "review"] | None = None,
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    max_score: Annotated[int, Query(ge=0, le=100)] = 100,
    account_id: str | None = None,
    run_id: UUID | None = None,
    feedback: Literal["fraud", "legitimate", "unlabeled"] | None = None,
    start_time: AwareDatetime | None = None,
    end_time: AwareDatetime | None = None,
) -> Page:
    query = (
        select(ScoredTransaction, Alert)
        .outerjoin(
            Alert,
            Alert.transaction_sequence == ScoredTransaction.sequence,
        )
        .where(ScoredTransaction.session_id == session.id)
    )
    if request.url.path.endswith("/alerts"):
        query = query.where(Alert.id.is_not(None))
    if min_score > max_score or (start_time and end_time and start_time > end_time):
        raise ApiError(422, "INVALID_RANGE", "Filter range is reversed")
    query = query.where(ScoredTransaction.risk_score.between(min_score, max_score))
    if cursor:
        query = query.where(ScoredTransaction.sequence < cursor_sequence(cursor))
    if recommendation:
        query = query.where(ScoredTransaction.recommendation == recommendation)
    if account_id:
        query = query.where(ScoredTransaction.account_id == account_id)
    if run_id:
        query = query.where(ScoredTransaction.run_id == run_id)
    if feedback:
        query = query.where(Alert.id.is_not(None))
        query = query.where(
            Alert.feedback.is_(None) if feedback == "unlabeled" else Alert.feedback == feedback
        )
    if start_time:
        query = query.where(ScoredTransaction.event_at >= start_time)
    if end_time:
        query = query.where(ScoredTransaction.event_at <= end_time)
    rows = db.execute(query.order_by(ScoredTransaction.sequence.desc()).limit(limit + 1)).all()
    items = [
        TransactionItem(
            transaction=Transaction.model_validate(row.payload),
            received_at=row.received_at,
            score=ScoreResult.model_validate(row.result),
            feedback=alert.feedback if alert else None,
        )
        for row, alert in rows[:limit]
    ]
    next_cursor = (
        base64.urlsafe_b64encode(str(rows[limit - 1][0].sequence).encode()).decode()
        if len(rows) > limit
        else None
    )
    return Page(items=items, next_cursor=next_cursor)


class Feedback(Contract):
    label: Literal["fraud", "legitimate"]


@router.patch("/alerts/{alert_id}/feedback", response_model=Feedback)
def update_feedback(
    alert_id: UUID, body: Feedback, db: Database, session: CurrentSession
) -> Feedback:
    alert = db.scalar(
        select(Alert)
        .join(ScoredTransaction)
        .where(
            Alert.id == alert_id,
            ScoredTransaction.session_id == session.id,
        )
        .with_for_update()
    )
    if alert is None:
        raise ApiError(404, "ALERT_NOT_FOUND", "Alert was not found in this session")
    alert.feedback = body.label
    alert.feedback_at = datetime.now(UTC)
    db.commit()
    return body
