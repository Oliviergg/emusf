"""Redis-backed job queue for async Apex execution."""

from __future__ import annotations

import json
from typing import Optional

from ..sf_runtime import generate_job_id


class RedisJobQueue:
    """
    Async job queue backed by Redis.
    Jobs are serialized and pushed to a Redis list.
    A worker process (utils/worker.py) picks them up via BRPOP.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        import redis
        self._redis = redis.Redis.from_url(redis_url)
        self._queue_key = "emusf:jobs"

    def enqueue(self, queueable_instance: dict) -> str:
        """Enqueue a job to Redis."""
        job_id = generate_job_id()
        class_def = queueable_instance.get("_class")
        class_name = class_def.name if class_def else "Unknown"

        # Serialize the instance state (without non-serializable _class/_chain)
        state = {}
        for k, v in queueable_instance.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (str, int, float, bool, type(None))):
                state[k] = v

        payload = json.dumps({
            "job_id": job_id,
            "class_name": class_name,
            "state": state,
        })

        self._redis.lpush(self._queue_key, payload)
        return job_id

    def has_pending(self) -> bool:
        return self._redis.llen(self._queue_key) > 0

    def flush(self, interpreter):
        """No-op for Redis mode — worker handles execution."""
        pass

    def dequeue(self, timeout: int = 0) -> Optional[dict]:
        """Block-pop a job from Redis. Used by the worker."""
        result = self._redis.brpop(self._queue_key, timeout=timeout)
        if result:
            _, payload = result
            return json.loads(payload)
        return None
