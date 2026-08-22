#!/usr/bin/env python3
"""A real worker process that can be killed and must resume, not restart.

This exists as a separate executable because a resume claim tested by catching
an exception inside one process proves very little: the interpreter unwound
cleanly, flushed what it had and kept its memory.  Here the parent sends
``SIGKILL``, so there is no unwinding, no flush and no memory — exactly the
provider-runtime loss the commission requires as a fault case.

Everything the resumed process is allowed to know comes from the ledger:

* ``resume_point`` gives the last monotonic checkpoint and the set of steps
  already committed, so work restarts at N rather than at zero;
* a step is skipped when either witness says it is done, because a kill can
  land between the ``STEP_COMMITTED`` row and the ``CHECKPOINTED`` row;
* the outbox still guards the effect, so even a wrong resume decision could
  not produce a second external effect. Belt and braces on purpose: the
  checkpoint is what makes resume *efficient*, the outbox is what makes it
  *correct*.

``attempts.jsonl`` is written before each step is attempted and is never read
by the worker.  It is the parent's independent witness: if a committed step
were ever re-executed, that line would exist even if the ledger were tidy.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

PO03_ROOT = Path(__file__).resolve().parents[1]
if str(PO03_ROOT) not in sys.path:
    sys.path.insert(0, str(PO03_ROOT))

from engine.canonical import append_line_durably, atomic_write_json, canonical, utc_now  # noqa: E402
from engine.ledger import HashChainedLedger  # noqa: E402
from engine.lease import CheckpointRegression, LeaseManager, lease_from_dict  # noqa: E402
from engine.outbox import FileEffectSink, Outbox  # noqa: E402

DIE_MODES = ("after-checkpoint", "mid-step-append", "mid-checkpoint-append", "none")


def _suicide() -> None:
    """Leave no chance to flush, unwind or report."""
    os.kill(os.getpid(), signal.SIGKILL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="killable, resumable PO-03 work unit")
    parser.add_argument("--unit", required=True)
    parser.add_argument("--root", required=True, help="durable state directory")
    parser.add_argument("--lease", required=True, help="path to the granted lease document")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--run-label", default="run-1")
    parser.add_argument("--die-after", type=int, default=0, help="step number to die after; 0 disables")
    parser.add_argument("--die-mode", choices=DIE_MODES, default="after-checkpoint")
    parser.add_argument(
        "--ignore-checkpoints",
        action="store_true",
        help=(
            "negative control: behave like the pre-checkpoint implementation, restarting from zero "
            "and tolerating the checkpoint regression that monotonicity would otherwise refuse"
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    ledger = HashChainedLedger(root / "ledger.jsonl")
    leases = LeaseManager(ledger)
    lease = lease_from_dict(json.loads(Path(args.lease).read_text(encoding="utf-8")))
    outbox = Outbox(root / "outbox", ledger)
    sink = FileEffectSink(root / "effects")
    attempts = root / "attempts.jsonl"

    resume = leases.resume_point(args.unit)
    append_line_durably(
        attempts,
        canonical(
            {
                "kind": "RESUME",
                "run_label": args.run_label,
                "pid": os.getpid(),
                "fence_token": lease.fence_token,
                "resume_point": resume.as_dict(),
                "ignore_checkpoints": args.ignore_checkpoints,
                "at": utc_now(),
            }
        ),
    )

    executed: list[str] = []
    skipped: list[str] = []
    for seq in range(1, args.steps + 1):
        step_id = f"step-{seq:02d}"
        if not args.ignore_checkpoints and not resume.should_execute(step_id, seq):
            skipped.append(step_id)
            append_line_durably(
                attempts,
                canonical({"kind": "SKIP", "run_label": args.run_label, "step_id": step_id, "seq": seq}),
            )
            continue

        append_line_durably(
            attempts,
            canonical(
                {
                    "kind": "ATTEMPT",
                    "run_label": args.run_label,
                    "step_id": step_id,
                    "seq": seq,
                    "pid": os.getpid(),
                    "at": utc_now(),
                }
            ),
        )

        lease = leases.heartbeat(lease)
        record_id = f"{args.unit}-{step_id}"
        outbox.enqueue(
            record_id,
            unit_id=args.unit,
            idempotency_key=f"{args.unit}:{step_id}",
            effect_name="apply-step",
            payload={"step_id": step_id, "seq": seq},
        )
        delivery = outbox.deliver(record_id, sink, worker_id=lease.worker_id, fence_token=lease.fence_token)

        if args.die_after == seq and args.die_mode == "mid-step-append":
            ledger.set_fault_hook(lambda point: _suicide() if point == "after_append_before_seal" else None)
        leases.commit_step(lease, step_id, payload={"delivery_status": delivery.status})
        ledger.set_fault_hook(None)

        if args.die_after == seq and args.die_mode == "mid-checkpoint-append":
            ledger.set_fault_hook(lambda point: _suicide() if point == "after_append_before_seal" else None)
        try:
            leases.checkpoint(lease, seq, payload={"step_id": step_id})
        except CheckpointRegression:
            # Only the negative control reaches here.  Monotonicity is a third
            # independent guard: a naive restart is refused outright unless the
            # run explicitly asks to behave like the implementation that had no
            # checkpoints at all.
            if not args.ignore_checkpoints:
                raise
            append_line_durably(
                attempts,
                canonical(
                    {
                        "kind": "CHECKPOINT_REGRESSION_TOLERATED",
                        "run_label": args.run_label,
                        "step_id": step_id,
                        "seq": seq,
                    }
                ),
            )
        finally:
            ledger.set_fault_hook(None)

        executed.append(step_id)
        if args.die_after == seq and args.die_mode == "after-checkpoint":
            append_line_durably(
                attempts,
                canonical({"kind": "DIE", "run_label": args.run_label, "step_id": step_id, "mode": args.die_mode}),
            )
            _suicide()

    atomic_write_json(
        root / f"report-{args.run_label}.json",
        {
            "unit_id": args.unit,
            "run_label": args.run_label,
            "worker_id": lease.worker_id,
            "fence_token": lease.fence_token,
            "resume_point_at_start": resume.as_dict(),
            "executed": executed,
            "skipped": skipped,
            "finished_at": utc_now(),
        },
    )
    print(canonical({"run_label": args.run_label, "executed": executed, "skipped": skipped}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
