"""Sync job queue — collects Queueable instances, executes on flush()."""

from __future__ import annotations

from ..sf_runtime import make_queueable_context, generate_job_id


class SyncJobQueue:
    """
    In-process job queue for test execution.

    Mirrors Salesforce behavior:
    - System.enqueueJob(queueable) → stores instance
    - Test.stopTest() → calls flush() → executes all pending jobs
    - Jobs enqueued during execution are processed in the same flush (chaining)
    """

    def __init__(self):
        self._pending = []  # list of (instance_dict, job_id)

    def enqueue(self, queueable_instance: dict) -> str:
        """
        Enqueue a Queueable instance for later execution.
        Returns a fake job Id.
        """
        job_id = generate_job_id()
        self._pending.append((queueable_instance, job_id))
        return job_id

    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def flush(self, interpreter):
        """
        Execute all pending Queueable jobs.
        Called by Test.stopTest() in the test runner.

        Each job's execute(QueueableContext) method is called.
        Jobs enqueued during execution are added to the queue (chaining).
        """
        max_iterations = 50  # Safety limit for chaining
        iteration = 0

        while self._pending and iteration < max_iterations:
            instance, job_id = self._pending.pop(0)
            iteration += 1

            class_def = instance.get("_class")
            if not class_def:
                continue

            # Find execute(QueueableContext) method — attention aux surcharges :
            # ces jobs implémentent aussi Finalizer (execute(FinalizerContext)),
            # donc methods['execute'] peut être la mauvaise variante ; on
            # cherche la bonne signature dans methods ET overloads.
            execute_method = None
            chain = interpreter._resolve_class_chain(class_def)
            for cls in chain:
                candidates = list(getattr(cls, "overloads", {}).get("execute", []))
                if "execute" in cls.methods:
                    candidates.append(cls.methods["execute"])
                for m in candidates:
                    if m.params and m.params[0][0] == "QueueableContext":
                        execute_method = m
                        break
                if execute_method:
                    break

            if not execute_method:
                continue

            # Create QueueableContext
            context = make_queueable_context(job_id)

            try:
                interpreter._invoke_instance_method(
                    instance, execute_method, [context]
                )
            except Exception as e:
                # Job failed — log but don't crash the test
                print("JOB FAILED: {} — {}".format(class_def.name, e))

        if iteration >= max_iterations:
            print("WARNING: Job queue hit max iterations ({})".format(max_iterations))
