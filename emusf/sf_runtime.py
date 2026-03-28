"""Salesforce runtime primitives — interfaces, contexts, system types."""

from __future__ import annotations

import time
import uuid

# Marker interfaces — no logic, just recognized by the runtime
MARKER_INTERFACES = {
    "Queueable", "Database.AllowsCallouts", "Finalizer",
    "Schedulable", "Batchable", "HttpCalloutMock",
}


def make_queueable_context(job_id: str) -> dict:
    """Creates a QueueableContext passed to Queueable.execute()."""
    return {
        "_type": "QueueableContext",
        "jobId": job_id,
    }


def make_finalizer_context(job_id: str, success: bool) -> dict:
    """Creates a FinalizerContext for Finalizer.execute()."""
    return {
        "_type": "FinalizerContext",
        "asyncApexJobId": job_id,
        "result": "SUCCESS" if success else "FAILURE",
    }


def generate_job_id() -> str:
    """Generates a fake Salesforce async job Id."""
    return "707" + str(int(time.time() * 1000))[-12:]


def generate_uuid() -> str:
    return str(uuid.uuid4())
