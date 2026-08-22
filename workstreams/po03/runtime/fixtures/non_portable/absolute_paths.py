"""Planted defect fixture: absolute filesystem paths.

Never imported and never executed.  It exists so the ABS_PATH_LITERAL rule can
be proved to fire.  A detector that has never fired is not evidence.
"""

CONFIG_PATH = "/etc/obzio/po03.json"
LEDGER_PATH = "/srv/obzio/ledger.jsonl"
WINDOWS_PATH = "C:\\obzio\\state"


def load_config():
    return open(CONFIG_PATH, encoding="utf-8").read()
