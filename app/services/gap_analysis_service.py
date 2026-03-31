"""Gap analysis service — readiness scan against degree baselines."""

import json
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_gap_job_repo import GapAnalysisJobRepository
from app.repositories.mysql_gap_analysis_repo import GapAnalysisRepository
from app.repositories.mysql_profile_repo import ProfileRepository
from app.repositories.mysql_profile_normalized_repo import ProfileNormalizedRepository
from app.services.llm_service import LLMService
from app.utils.exceptions import NotFoundError

logger = get_logger(__name__)


class GapAnalysisService:
    """Identifies readiness gaps for a student's target degree level."""

    def __init__(self):
        self.profile_repo = ProfileRepository()
        self.normalized_repo = ProfileNormalizedRepository()
        self.gap_job_repo = GapAnalysisJobRepository()
        self.gap_repo = GapAnalysisRepository()
        self.llm_service = LLMService()

    async def analyze(self, profile_id: str) -> dict[str, Any]:
        """Run gap analysis on an existing profile."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        # Fetch latest profile version snapshot (source of truth for profile state)
        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}

        target_degree = row.get("target_degree_level", "unknown")
        if target_degree == "unknown":
            result = {
                "target_degree_level": "unknown",
                "readiness_score": None,
                "readiness_signals": [
                    {
                        "category": "target_degree",
                        "requirement": "Target degree must be specified",
                        "status": "missing",
                        "severity": "high",
                        "recommendation": "Please specify your target degree level",
                    }
                ],
                "signal_summary": {"meets": 0, "partial": 0, "missing": 1},
                "recommendations": [
                    {
                        "area": "target_degree",
                        "action": "Please specify your target degree level",
                        "priority": "high",
                    }
                ],
            }
            await self._persist_analysis(profile_id=profile_id, target_degree=target_degree, result=result)
            logger.info("gap_analysis_completed", profile_id=profile_id)
            return result

        raw_result = await self.llm_service.run_gap_analysis(profile_json, target_degree, profile_id=profile_id)
        result = self._normalize_gap_result(raw_result, target_degree)

        await self._persist_analysis(profile_id=profile_id, target_degree=target_degree, result=result)

        logger.info("gap_analysis_completed", profile_id=profile_id)
        return result

    async def get_latest_analysis(self, profile_id: str) -> dict[str, Any]:
        """Return latest persisted gap-analysis snapshot for a profile."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        analysis = await self.gap_repo.get_latest_by_profile(profile_id)
        if not analysis:
            raise NotFoundError("GapAnalysis")

        return {
            "analysis_id": analysis["id"],
            "profile_id": analysis["profile_id"],
            "target_degree_level": analysis.get("target_degree_level"),
            "readiness_score": analysis.get("readiness_score"),
            "gaps_identified": self._parse_json_field(analysis.get("gaps_identified")) or [],
            "recommendations": self._parse_json_field(analysis.get("recommendations")) or [],
            "baseline_template": analysis.get("baseline_template"),
            "analyzed_at": analysis.get("analyzed_at"),
        }

    async def _persist_analysis(self, profile_id: str, target_degree: str, result: dict[str, Any]) -> None:
        """Persist analysis snapshot for downstream reporting and auditing."""
        try:
            await self.gap_repo.create_analysis(
                {
                    "profile_id": profile_id,
                    "target_degree_level": target_degree,
                    "readiness_score": result.get("readiness_score"),
                    "gaps_identified": result.get("readiness_signals", []),
                    "recommendations": result.get("recommendations", []),
                    "baseline_template": f"baseline_{target_degree}_v1",
                }
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("gap_analysis_persist_failed", profile_id=profile_id, error=str(exc))

    @staticmethod
    def _normalize_gap_result(raw_result: dict[str, Any], target_degree: str) -> dict[str, Any]:
        """Normalize LLM output into stable readiness signal schema."""
        result = dict(raw_result or {})
        signals = result.get("readiness_signals")

        if not isinstance(signals, list):
            signals = []

        normalized_signals: list[dict[str, Any]] = []
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            status = str(signal.get("status") or "").strip().lower()
            if status not in {"meets", "partial", "missing"}:
                score = signal.get("score")
                try:
                    parsed_score = float(score)
                    if parsed_score >= 0.7:
                        status = "meets"
                    elif parsed_score >= 0.4:
                        status = "partial"
                    else:
                        status = "missing"
                except (TypeError, ValueError):
                    status = "partial"

            normalized_signals.append(
                {
                    "category": str(signal.get("category") or "general"),
                    "requirement": str(signal.get("requirement") or "baseline requirement"),
                    "status": status,
                    "severity": str(signal.get("severity") or "medium"),
                    "recommendation": str(signal.get("recommendation") or "").strip(),
                }
            )

        # Backward-compatible conversion when older output uses gaps_identified/recommendations.
        if not normalized_signals:
            gaps = result.get("gaps_identified") if isinstance(result.get("gaps_identified"), list) else []
            recs = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []

            recommendation_map: dict[str, str] = {}
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                area = str(rec.get("area") or "general")
                action = str(rec.get("action") or "").strip()
                if action:
                    recommendation_map[area] = action

            for gap in gaps:
                if not isinstance(gap, dict):
                    continue
                area = str(gap.get("area") or "general")
                severity = str(gap.get("severity") or "medium")
                detail = str(gap.get("detail") or gap.get("description") or "baseline signal needs improvement")
                normalized_signals.append(
                    {
                        "category": area,
                        "requirement": detail,
                        "status": "missing",
                        "severity": severity,
                        "recommendation": recommendation_map.get(area, ""),
                    }
                )

        signal_summary = {
            "meets": sum(1 for s in normalized_signals if s.get("status") == "meets"),
            "partial": sum(1 for s in normalized_signals if s.get("status") == "partial"),
            "missing": sum(1 for s in normalized_signals if s.get("status") == "missing"),
        }

        recommendations = []
        for signal in normalized_signals:
            action = signal.get("recommendation")
            if not action:
                continue
            recommendations.append(
                {
                    "area": signal.get("category"),
                    "action": action,
                    "priority": "high" if signal.get("status") == "missing" else "medium",
                }
            )

        normalized = {
            "target_degree_level": target_degree,
            "readiness_score": result.get("readiness_score"),
            "readiness_signals": normalized_signals,
            "signal_summary": signal_summary,
            "recommendations": recommendations,
        }
        return normalized

    async def create_gap_job(self, profile_id: str) -> dict[str, Any]:
        """Create an async job record for gap analysis."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        # Fetch latest profile version to check clarification_queue
        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}
        queue = profile_json.get("clarification_queue") or []

        if queue:
            status = "blocked"
            error_message = "Profile requires clarification before gap analysis"
        else:
            status = "queued"
            error_message = None

        job_id = await self.gap_job_repo.create_job(
            {
                "profile_id": profile_id,
                "status": status,
                "error_message": error_message,
            }
        )

        return {
            "job_id": job_id,
            "profile_id": profile_id,
            "status": status,
            "error_message": error_message,
            "result": None,
        }

    async def get_gap_job(self, job_id: str) -> dict[str, Any]:
        """Return current async gap-analysis job snapshot."""
        row = await self.gap_job_repo.get_job(job_id)
        if not row:
            raise NotFoundError("GapAnalysisJob")

        return {
            "job_id": row["id"],
            "profile_id": row["profile_id"],
            "status": row["status"],
            "error_message": row.get("error_message"),
            "result": row.get("result_json"),
        }

    async def process_gap_job(self, job_id: str, profile_id: str) -> None:
        """Execute queued gap-analysis job in background."""
        now = datetime.now(timezone.utc)
        await self.gap_job_repo.update_job(job_id, {"status": "running", "started_at": now})

        try:
            result = await self.analyze(profile_id)
            await self.gap_job_repo.update_job(
                job_id,
                {
                    "status": "completed",
                    "result_json": result,
                    "completed_at": datetime.now(timezone.utc),
                },
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self.gap_job_repo.update_job(
                job_id,
                {
                    "status": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            logger.error("gap_analysis_job_failed", job_id=job_id, profile_id=profile_id, error=str(exc))

    @staticmethod
    def _parse_json_field(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
