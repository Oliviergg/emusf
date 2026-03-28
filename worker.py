"""
Redis worker — picks up Apex Queueable jobs and executes them.

Usage:
    docker compose up -d redis
    python worker.py
"""

import os
import sys
import signal

from emusf import ApexParser
from emusf.interpreter import ApexInterpreter
from emusf.pg_test_org import PgTestOrg
from emusf.queue.redis_queue import RedisJobQueue
from emusf.sf_runtime import make_queueable_context
from emusf.sfdx_loader import configure_pg_org

# Config
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DSN = os.environ.get("DSN",
    "host=localhost port=6000 user=postgres "
    "password=dcc948df3501919f709cb976fa2cb24000be8b12 dbname=biup")
SF_CLASSES = os.environ.get("SF_CLASSES",
    "/Users/olivier/Dev/btp/sf-btp/force-app/main/default/classes")
SFDX_OBJECTS = os.environ.get("SFDX_OBJECTS",
    "/Users/olivier/Dev/btp/sf-btp/force-app/main/default/objects")

# Colors
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_source_classes(parser):
    """Load all Apex source classes."""
    import re
    classes = {}
    prefixes = ["XPL", "ILG", "ParQueJob", "ParallelQueueableJob",
                "QueueableJob", "QueueManager"]
    for fname in sorted(os.listdir(SF_CLASSES)):
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        if re.search(r'test', name, re.IGNORECASE):
            continue
        if not any(name.startswith(p) for p in prefixes):
            continue
        path = os.path.join(SF_CLASSES, fname)
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            classes[class_def.name] = class_def
        except Exception:
            pass
    return classes


def execute_job(job_data, org, all_classes, parser):
    """Execute a single job."""
    class_name = job_data["class_name"]
    job_id = job_data["job_id"]
    state = job_data.get("state", {})

    interp = ApexInterpreter(org)
    interp.job_queue = RedisJobQueue(REDIS_URL)  # Jobs can enqueue more jobs

    # Load classes
    for name, cls in all_classes.items():
        interp.classes[name] = cls
        for cname, (ctype, expr) in cls.constants.items():
            try:
                interp.variables["{}.{}".format(name, cname)] = interp._eval(expr)
            except Exception:
                pass

    # Resolve the job class
    class_def = interp._resolve_class(class_name)
    if not class_def:
        raise Exception("Class '{}' not found".format(class_name))

    # Create instance and restore state
    instance = interp._create_instance(class_def, [])
    for k, v in state.items():
        instance[k] = v

    # Find execute(QueueableContext) method
    execute_method = interp._resolve_method_in_chain(class_def, "execute")
    if not execute_method:
        raise Exception("No execute() method in '{}'".format(class_name))

    # Run
    context = make_queueable_context(job_id)
    interp._invoke_instance_method(instance, execute_method, [context])


def main():
    print("{}emusf worker{} — Redis job processor".format(BOLD, RESET))

    # Setup
    parser = ApexParser()
    print(DIM + "Loading source classes..." + RESET)
    all_classes = load_source_classes(parser)
    print("  {} classes loaded".format(len(all_classes)))

    org = PgTestOrg(DSN, schema="test")
    print(DIM + "Loading SFDX metadata..." + RESET)
    sfdx_objects = [d for d in os.listdir(SFDX_OBJECTS)
                    if os.path.isdir(os.path.join(SFDX_OBJECTS, d))]
    configure_pg_org(org, SFDX_OBJECTS, sfdx_objects)

    queue = RedisJobQueue(REDIS_URL)
    print("{}Connected to Redis{}\n".format(GREEN, RESET))

    # Graceful shutdown
    running = True
    def shutdown(sig, frame):
        nonlocal running
        print("\n{}Shutting down...{}".format(DIM, RESET))
        running = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Main loop
    print("Waiting for jobs... (Ctrl+C to stop)\n")
    while running:
        job_data = queue.dequeue(timeout=1)
        if job_data is None:
            continue

        class_name = job_data.get("class_name", "?")
        job_id = job_data.get("job_id", "?")
        print("{}JOB{} {} (id={})".format(YELLOW, RESET, class_name, job_id))

        try:
            execute_job(job_data, org, all_classes, parser)
            print("  {}✓ Completed{}".format(GREEN, RESET))
        except Exception as e:
            print("  {}✗ Failed: {}{}".format(RED, e, RESET))


if __name__ == "__main__":
    main()
