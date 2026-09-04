"""Database access for the console.

Converted to a genuinely async engine. The previous version declared ``async
def`` around synchronous SQLModel sessions, which does not make a query
non-blocking — it blocks the event loop while claiming not to, and under any
real concurrency that is worse than being honestly synchronous. Here the driver
is psycopg3 in async mode, so a query actually yields.

Every method takes and returns model objects rather than exposing sessions, so
no route handler holds a transaction open across a model call that might take
forty seconds.
"""

import uuid
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import (
    Any,
    Optional,
    Sequence,
)
from urllib.parse import quote_plus

from sqlalchemy import (
    delete,
    func,
    select,
    update,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import (
    Environment,
    settings,
)
from app.core.logging import logger
from app.models.admin import Admin
from app.models.analysis import (
    AnalysisFeedback,
    AnalysisRun,
    AnalysisStatus,
    FeedbackVerdict,
)
from app.models.base import utcnow
from app.models.password_reset_token import (
    PasswordResetToken,
    hash_reset_token,
)
from app.models.refresh_token import (
    RecoveryCode,
    RefreshToken,
    hash_token,
)


class DatabaseService:
    """All database operations, as async methods."""

    def __init__(self):
        """Create the async engine and session factory."""
        try:
            connection_url = (
                "postgresql+psycopg://"
                f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            )

            self.engine = create_async_engine(
                connection_url,
                pool_pre_ping=True,
                pool_size=settings.POSTGRES_POOL_SIZE,
                max_overflow=settings.POSTGRES_MAX_OVERFLOW,
                pool_timeout=30,
                pool_recycle=1800,
                # SQL is never echoed. Query logs from this service would carry
                # redacted policy text into the application log, which is a
                # second copy of data we promised to keep in one place.
                echo=False,
            )

            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            logger.info(
                "database_initialized",
                environment=settings.ENVIRONMENT.value,
                pool_size=settings.POSTGRES_POOL_SIZE,
            )
        except SQLAlchemyError as e:
            logger.error("database_initialization_error", error=str(e))
            if settings.ENVIRONMENT != Environment.PRODUCTION:
                raise

    # ------------------------------------------------------------------
    # Admins
    # ------------------------------------------------------------------

    async def get_admin_by_email(self, email: str) -> Optional[Admin]:
        """Look up an admin by email.

        Args:
            email: The email, matched case-insensitively.

        Returns:
            Optional[Admin]: The account, or None.
        """
        async with self.session_factory() as session:
            result = await session.execute(select(Admin).where(Admin.email == email.strip().lower()))
            return result.scalar_one_or_none()

    async def get_admin_by_id(self, admin_id: uuid.UUID) -> Optional[Admin]:
        """Look up an admin by id.

        Args:
            admin_id: The account id.

        Returns:
            Optional[Admin]: The account, or None.
        """
        async with self.session_factory() as session:
            return await session.get(Admin, admin_id)

    async def save_admin(self, admin: Admin) -> Admin:
        """Persist changes to an admin row.

        Args:
            admin: The modified account.

        Returns:
            Admin: The refreshed account.
        """
        async with self.session_factory() as session:
            merged = await session.merge(admin)
            await session.commit()
            await session.refresh(merged)
            return merged

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    async def create_refresh_token(
        self,
        admin_id: uuid.UUID,
        raw_token: str,
        expires_at: datetime,
        family_id: Optional[uuid.UUID] = None,
        client_fingerprint: Optional[str] = None,
    ) -> RefreshToken:
        """Store a newly issued refresh token.

        Args:
            admin_id: Owner.
            raw_token: The token handed to the client. Only its hash is stored.
            expires_at: Absolute expiry.
            family_id: Rotation family. A new login starts a new family.
            client_fingerprint: Advisory client binding.

        Returns:
            RefreshToken: The stored record.
        """
        record = RefreshToken(
            admin_id=admin_id,
            token_hash=hash_token(raw_token),
            family_id=family_id or uuid.uuid4(),
            expires_at=expires_at,
            client_fingerprint=client_fingerprint,
        )

        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_refresh_token(self, raw_token: str) -> Optional[RefreshToken]:
        """Find a refresh token record by the raw token.

        Args:
            raw_token: The token from the cookie.

        Returns:
            Optional[RefreshToken]: The record, or None if unknown.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
            )
            return result.scalar_one_or_none()

    async def mark_refresh_token_used(self, token_id: uuid.UUID) -> None:
        """Mark a refresh token as exchanged.

        Args:
            token_id: The record id.
        """
        async with self.session_factory() as session:
            await session.execute(
                update(RefreshToken).where(RefreshToken.id == token_id).values(used_at=utcnow())
            )
            await session.commit()

    async def revoke_token_family(self, family_id: uuid.UUID, reason: str) -> int:
        """Revoke every live token descended from one login.

        Called on logout and — importantly — when a already-used token is
        presented again, which means the token was stolen.

        Args:
            family_id: The family to kill.
            reason: Recorded for audit.

        Returns:
            int: How many tokens were revoked.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow(), revoked_reason=reason[:64])
            )
            await session.commit()
            return result.rowcount or 0

    async def revoke_all_admin_tokens(self, admin_id: uuid.UUID, reason: str) -> int:
        """Revoke every refresh token an admin holds.

        Args:
            admin_id: The account.
            reason: Recorded for audit.

        Returns:
            int: How many tokens were revoked.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.admin_id == admin_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow(), revoked_reason=reason[:64])
            )
            await session.commit()
            return result.rowcount or 0

    async def purge_expired_tokens(self) -> int:
        """Delete refresh tokens that expired more than a week ago.

        Keeping them briefly past expiry preserves the audit trail for a
        post-incident look; keeping them forever grows a table nothing reads.

        Returns:
            int: Rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=7)
        async with self.session_factory() as session:
            result = await session.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
            await session.commit()
            return result.rowcount or 0

    # ------------------------------------------------------------------
    # Password reset tokens
    # ------------------------------------------------------------------

    async def create_password_reset_token(
        self,
        admin_id: uuid.UUID,
        raw_token: str,
        expires_at: datetime,
        requested_fingerprint: Optional[str] = None,
    ) -> PasswordResetToken:
        """Issue a reset token, retiring any the account already holds.

        Both happen in one transaction: an operator who clicks "send it again"
        must end up with exactly one working link, and a window where the old
        one is dead but the new one is not yet stored would be a window where
        neither works.

        Args:
            admin_id: Owner of the token.
            raw_token: The token going into the email. Only its hash is stored.
            expires_at: Absolute expiry.
            requested_fingerprint: Advisory record of who asked.

        Returns:
            PasswordResetToken: The stored record.
        """
        record = PasswordResetToken(
            admin_id=admin_id,
            token_hash=hash_reset_token(raw_token),
            expires_at=expires_at,
            requested_fingerprint=requested_fingerprint,
        )

        async with self.session_factory() as session:
            await session.execute(
                update(PasswordResetToken)
                .where(
                    PasswordResetToken.admin_id == admin_id,
                    PasswordResetToken.used_at.is_(None),
                )
                .values(used_at=utcnow())
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_password_reset_token(self, raw_token: str) -> Optional[PasswordResetToken]:
        """Find a reset token record by the raw token from the link.

        Args:
            raw_token: The token from the email link.

        Returns:
            Optional[PasswordResetToken]: The record, or None if unknown.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_reset_token(raw_token))
            )
            return result.scalar_one_or_none()

    async def consume_password_reset_tokens(self, admin_id: uuid.UUID) -> int:
        """Mark every outstanding reset token for an account as spent.

        Called on redemption rather than marking only the token presented: a
        second link that is still live after a password change is a second way
        in for whoever caused the operator to reset in the first place.

        Args:
            admin_id: The account.

        Returns:
            int: How many tokens were retired.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                update(PasswordResetToken)
                .where(
                    PasswordResetToken.admin_id == admin_id,
                    PasswordResetToken.used_at.is_(None),
                )
                .values(used_at=utcnow())
            )
            await session.commit()
            return result.rowcount or 0

    async def purge_expired_password_reset_tokens(self) -> int:
        """Delete reset tokens that expired more than a day ago.

        Returns:
            int: Rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=1)
        async with self.session_factory() as session:
            result = await session.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff))
            await session.commit()
            return result.rowcount or 0

    # ------------------------------------------------------------------
    # Recovery codes
    # ------------------------------------------------------------------

    async def replace_recovery_codes(self, admin_id: uuid.UUID, code_hashes: Sequence[str]) -> None:
        """Replace an admin's recovery codes with a fresh set.

        Args:
            admin_id: The account.
            code_hashes: bcrypt hashes of the new codes.
        """
        async with self.session_factory() as session:
            await session.execute(delete(RecoveryCode).where(RecoveryCode.admin_id == admin_id))
            for code_hash in code_hashes:
                session.add(RecoveryCode(admin_id=admin_id, code_hash=code_hash))
            await session.commit()

    async def get_unused_recovery_codes(self, admin_id: uuid.UUID) -> list[RecoveryCode]:
        """Fetch an admin's unspent recovery codes.

        Args:
            admin_id: The account.

        Returns:
            list[RecoveryCode]: Unused codes.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(RecoveryCode).where(
                    RecoveryCode.admin_id == admin_id,
                    RecoveryCode.used_at.is_(None),
                )
            )
            return list(result.scalars().all())

    async def consume_recovery_code(self, code_id: uuid.UUID) -> None:
        """Mark a recovery code as spent.

        Args:
            code_id: The code record.
        """
        async with self.session_factory() as session:
            await session.execute(
                update(RecoveryCode).where(RecoveryCode.id == code_id).values(used_at=utcnow())
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Analyses
    # ------------------------------------------------------------------

    async def create_analysis_run(self, run: AnalysisRun) -> AnalysisRun:
        """Store one analysis run.

        Args:
            run: The populated record.

        Returns:
            AnalysisRun: The stored record.
        """
        async with self.session_factory() as session:
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run

    async def get_analysis_run(self, run_id: uuid.UUID) -> Optional[AnalysisRun]:
        """Fetch one analysis run.

        Args:
            run_id: The record id.

        Returns:
            Optional[AnalysisRun]: The run, or None.
        """
        async with self.session_factory() as session:
            return await session.get(AnalysisRun, run_id)

    async def list_analysis_runs(
        self,
        limit: int = 25,
        offset: int = 0,
        patient_id: Optional[str] = None,
    ) -> tuple[list[tuple[AnalysisRun, Optional[FeedbackVerdict]]], int]:
        """Page through stored runs, newest first, with each one's verdict.

        The verdict is joined here rather than fetched per row, because a list
        screen that issues one extra query per line is a list screen that gets
        slower every week it is used.

        Args:
            limit: Page size.
            offset: How many rows to skip.
            patient_id: Restrict to one patient. Matched case-insensitively as a
                substring, because the operator is typing a remembered
                identifier into a search box, not pasting a primary key.

        Returns:
            tuple: ``(rows, total)`` where each row is ``(run, verdict|None)``
            and ``total`` counts every run matching the filter, not just the
            page — the pager needs to know what it is paging through.
        """
        filters = []
        if patient_id:
            filters.append(AnalysisRun.patient_id.ilike(f"%{patient_id}%"))

        async with self.session_factory() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(AnalysisRun).where(*filters)
                )
            ).scalar_one()

            rows = (
                await session.execute(
                    select(AnalysisRun, AnalysisFeedback.verdict)
                    .outerjoin(AnalysisFeedback, AnalysisFeedback.analysis_id == AnalysisRun.id)
                    .where(*filters)
                    .order_by(AnalysisRun.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()

        return [(row[0], row[1]) for row in rows], int(total or 0)

    async def count_patient_analyses(self, patient_id: str) -> int:
        """How many runs are filed under exactly this patient id.

        Exact match, unlike the list filter's substring search: this figure is
        what the console shows before an erasure ("delete all 4 analyses for
        this patient"), and a count that included neighbouring ids would
        understate or overstate what the button is about to destroy.

        Args:
            patient_id: The identifier as it was stored.

        Returns:
            int: The number of runs.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(AnalysisRun)
                .where(AnalysisRun.patient_id == patient_id)
            )
            return int(result.scalar_one() or 0)

    async def delete_analysis_run(self, run_id: uuid.UUID) -> tuple[int, int]:
        """Erase one run and the verdict attached to it.

        Both deletes happen in one transaction, and the feedback goes first:
        ``analysis_feedback.analysis_id`` is a foreign key onto the run, so the
        other order fails on the constraint. A verdict that outlived its run
        would also be an orphan the golden-set builder joins to nothing.

        Args:
            run_id: The run to erase.

        Returns:
            tuple: ``(runs_deleted, feedback_deleted)``. ``(0, 0)`` when the run
            does not exist, which is how the route tells a 404 from a deletion.
        """
        async with self.session_factory() as session:
            feedback_deleted = (
                await session.execute(
                    delete(AnalysisFeedback).where(AnalysisFeedback.analysis_id == run_id)
                )
            ).rowcount or 0

            runs_deleted = (
                await session.execute(delete(AnalysisRun).where(AnalysisRun.id == run_id))
            ).rowcount or 0

            await session.commit()

        return int(runs_deleted), int(feedback_deleted)

    async def delete_patient_analyses(self, patient_id: str) -> tuple[int, int]:
        """Erase every run filed under one patient id, and their verdicts.

        The match is **exact**. The list screen searches patient ids as a
        substring because an operator is typing a remembered identifier into a
        search box; erasure cannot work that way — ``ilike('%12%')`` would take
        patient 12 and also patients 120, 312 and 1234 with it.

        Args:
            patient_id: The identifier as it was stored.

        Returns:
            tuple: ``(runs_deleted, feedback_deleted)``.
        """
        async with self.session_factory() as session:
            # A subquery rather than "read the ids, then delete them": the ids
            # are never needed in Python, and reading them first would open a
            # window in which a run added between the two statements survives an
            # erasure that reported it gone.
            feedback_deleted = (
                await session.execute(
                    delete(AnalysisFeedback).where(
                        AnalysisFeedback.analysis_id.in_(
                            select(AnalysisRun.id).where(AnalysisRun.patient_id == patient_id)
                        )
                    )
                )
            ).rowcount or 0

            runs_deleted = (
                await session.execute(
                    delete(AnalysisRun).where(AnalysisRun.patient_id == patient_id)
                )
            ).rowcount or 0

            await session.commit()

        return int(runs_deleted), int(feedback_deleted)

    async def document_seen_before(self, document_sha256: str) -> bool:
        """Whether this exact document has been analysed already.

        Args:
            document_sha256: Digest of the upload.

        Returns:
            bool: True when a prior run exists.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(AnalysisRun)
                .where(AnalysisRun.document_sha256 == document_sha256)
            )
            return (result.scalar_one() or 0) > 0

    async def create_feedback(self, feedback: AnalysisFeedback) -> AnalysisFeedback:
        """Store a reviewer's verdict.

        Args:
            feedback: The populated record.

        Returns:
            AnalysisFeedback: The stored record.
        """
        async with self.session_factory() as session:
            session.add(feedback)
            await session.commit()
            await session.refresh(feedback)
            return feedback

    async def update_feedback(
        self,
        feedback_id: uuid.UUID,
        admin_id: uuid.UUID,
        verdict: FeedbackVerdict,
        field_corrections: dict[str, Any],
        notes: str,
    ) -> None:
        """Revise an existing verdict in place.

        A reviewer changing their mind should leave one verdict on the run, not
        two. Appending a second row would double-count the analysis in
        ``evals/build_golden_set.py`` — which joins runs to feedback — and give
        the dashboard's accuracy rate a denominator larger than the number of
        analyses actually reviewed.

        Args:
            feedback_id: The verdict being revised.
            admin_id: Who is revising it — recorded as the current reviewer.
            verdict: The new overall call.
            field_corrections: The new field-level corrections.
            notes: The new free text.
        """
        async with self.session_factory() as session:
            await session.execute(
                update(AnalysisFeedback)
                .where(AnalysisFeedback.id == feedback_id)
                .values(
                    admin_id=admin_id,
                    verdict=verdict,
                    field_corrections=field_corrections,
                    notes=notes,
                    created_at=utcnow(),
                )
            )
            await session.commit()

    async def get_feedback_for_run(self, run_id: uuid.UUID) -> Optional[AnalysisFeedback]:
        """Fetch the most recent verdict for a run.

        Args:
            run_id: The analysis.

        Returns:
            Optional[AnalysisFeedback]: The verdict, or None.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(AnalysisFeedback)
                .where(AnalysisFeedback.analysis_id == run_id)
                .order_by(AnalysisFeedback.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Dashboard aggregates
    # ------------------------------------------------------------------

    async def dashboard_metrics(self, recent_limit: int = 15) -> dict[str, Any]:
        """Compute every figure the dashboard shows, in the database.

        Aggregating here rather than pulling rows into Python keeps the
        dashboard a constant number of queries as the table grows.

        Args:
            recent_limit: How many recent runs to return.

        Returns:
            dict: Raw aggregates for the route to shape into a response.
        """
        week_ago = datetime.now(UTC) - timedelta(days=7)

        async with self.session_factory() as session:
            totals = (
                await session.execute(
                    select(
                        func.count(AnalysisRun.id),
                        func.count(func.distinct(AnalysisRun.patient_id)),
                        func.count(AnalysisRun.id).filter(AnalysisRun.created_at >= week_ago),
                        func.count(AnalysisRun.id).filter(AnalysisRun.status == AnalysisStatus.SUCCEEDED),
                        func.count(AnalysisRun.id).filter(
                            AnalysisRun.status == AnalysisStatus.BLOCKED_BY_REDACTION
                        ),
                        func.percentile_cont(0.5)
                        .within_group(AnalysisRun.latency_ms)
                        .filter(AnalysisRun.status == AnalysisStatus.SUCCEEDED),
                    )
                )
            ).one()

            verdicts = (
                await session.execute(
                    select(AnalysisFeedback.verdict, func.count(AnalysisFeedback.id)).group_by(
                        AnalysisFeedback.verdict
                    )
                )
            ).all()

            recent_rows = (
                await session.execute(
                    select(AnalysisRun, AnalysisFeedback.verdict)
                    .outerjoin(AnalysisFeedback, AnalysisFeedback.analysis_id == AnalysisRun.id)
                    .order_by(AnalysisRun.created_at.desc())
                    .limit(recent_limit)
                )
            ).all()

            # Redaction counts live in a JSONB column, so they are summed by
            # walking the recent window rather than with a SQL aggregate — the
            # figure is illustrative, not billing-grade.
            summaries = (
                await session.execute(
                    select(AnalysisRun.redaction_summary)
                    .order_by(AnalysisRun.created_at.desc())
                    .limit(500)
                )
            ).scalars().all()

        redaction_totals: dict[str, int] = {}
        for summary in summaries:
            for category, count in (summary or {}).items():
                redaction_totals[category] = redaction_totals.get(category, 0) + int(count)

        return {
            "total": totals[0] or 0,
            "distinct_patients": totals[1] or 0,
            "last_7_days": totals[2] or 0,
            "succeeded": totals[3] or 0,
            "blocked": totals[4] or 0,
            "median_latency_ms": int(totals[5] or 0),
            "verdicts": {verdict: count for verdict, count in verdicts},
            "recent": recent_rows,
            "redaction_totals": redaction_totals,
        }

    async def reviewed_counts(self) -> tuple[int, int]:
        """Count reviewed runs and correct ones.

        Returns:
            tuple: ``(reviewed, correct)``.
        """
        async with self.session_factory() as session:
            result = (
                await session.execute(
                    select(
                        func.count(AnalysisFeedback.id),
                        func.count(AnalysisFeedback.id).filter(
                            AnalysisFeedback.verdict == FeedbackVerdict.CORRECT
                        ),
                    )
                )
            ).one()
            return int(result[0] or 0), int(result[1] or 0)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check database connectivity.

        Returns:
            bool: True when a trivial query succeeds.
        """
        try:
            async with self.session_factory() as session:
                await session.execute(select(1))
                return True
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Dispose of the connection pool on shutdown."""
        await self.engine.dispose()


database_service = DatabaseService()
