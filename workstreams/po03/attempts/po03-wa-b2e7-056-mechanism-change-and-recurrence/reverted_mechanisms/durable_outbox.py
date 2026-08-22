"""Deliberately reverted report-only fixture used to prove recurrence sensitivity."""

_MEMORY = {}


def write_result(directory, record):
    _MEMORY[record["task_id"]] = dict(record)
    body = repr(record).encode()
    return {"path": str(directory / f"{record['task_id']}.json"), "sha256": "not-verified", "bytes": len(body)}


def read_result(locator):
    task_id = locator["path"].rsplit("/", 1)[-1].removesuffix(".json")
    return _MEMORY[task_id]
