"""Safe, disposable Redis cursor cache for manual adjudication."""

import json
import logging

logger = logging.getLogger(__name__)


class ReviewStateStore:
    """Store scalar cursor state; database rows remain the source of truth."""

    ttl_seconds = 60 * 60 * 12

    @staticmethod
    def _key(project_id: str, user_id: str, run_id: str) -> str:
        return f"cedars:review:{project_id}:{user_id}:{run_id}"

    @staticmethod
    def load_from_patient(
        patient, user_id: str, run_id: str, generation: int
    ) -> dict | None:
        """Recover a validated scalar cursor snapshot from the patient row."""
        cursors = (patient.metadata_ or {}).get("manual_review_cursors", {})
        value = cursors.get(user_id) if isinstance(cursors, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("run_id") != run_id
            or value.get("generation") != generation
            or not isinstance(value.get("ordered_ids"), list)
            or not all(isinstance(item, str) for item in value["ordered_ids"])
            or not isinstance(value.get("current_id"), (str, type(None)))
        ):
            return None
        return value

    @staticmethod
    def save_to_patient(
        patient,
        user_id: str,
        run_id: str,
        generation: int,
        ordered_ids: list[str],
        current_id: str | None,
    ) -> None:
        """Persist only scalar cursor state; annotation rows remain authoritative."""
        metadata = dict(patient.metadata_ or {})
        cursors = dict(metadata.get("manual_review_cursors") or {})
        cursors[user_id] = {
            "run_id": run_id,
            "generation": int(generation),
            "ordered_ids": [str(item) for item in ordered_ids],
            "current_id": str(current_id) if current_id is not None else None,
        }
        metadata["manual_review_cursors"] = cursors
        patient.metadata_ = metadata

    async def load(self, project_id: str, user_id: str, run_id: str) -> dict | None:
        redis = None
        try:
            from arq import create_pool

            from app.worker import parse_redis_settings

            redis = await create_pool(parse_redis_settings())
            raw = await redis.get(self._key(project_id, user_id, run_id))
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or value.get("run_id") != run_id
                or not isinstance(value.get("ordered_ids"), list)
                or not all(isinstance(item, str) for item in value["ordered_ids"])
                or not isinstance(value.get("current_id"), (str, type(None)))
            ):
                return None
            return value
        except Exception:
            logger.debug("Review cursor cache unavailable; rebuilding from database")
            return None
        finally:
            if redis is not None:
                try:
                    await redis.aclose()
                except Exception:
                    pass

    async def save(
        self,
        project_id: str,
        user_id: str,
        run_id: str,
        generation: int,
        ordered_ids: list[str],
        current_id: str | None,
    ) -> None:
        redis = None
        payload = json.dumps({
            "run_id": run_id,
            "generation": int(generation),
            "ordered_ids": [str(item) for item in ordered_ids],
            "current_id": str(current_id) if current_id is not None else None,
        })
        try:
            from arq import create_pool

            from app.worker import parse_redis_settings

            redis = await create_pool(parse_redis_settings())
            await redis.set(
                self._key(project_id, user_id, run_id), payload, ex=self.ttl_seconds
            )
        except Exception:
            logger.debug("Review cursor cache unavailable; database state remains authoritative")
        finally:
            if redis is not None:
                try:
                    await redis.aclose()
                except Exception:
                    pass
