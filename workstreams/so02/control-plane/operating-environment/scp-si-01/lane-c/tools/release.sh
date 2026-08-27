#!/usr/bin/env bash
# Rebuild every lane C artifact and receipt in the one order that is acyclic.
#
#   bash workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/release.sh <integration-sha>
#
# Run from the repository root. Exits non-zero on the first failure, so a
# partially built receipt bundle is never presented as a complete one.
#
# The order is forced by what hashes what. Steps 6-9 each depend on the step
# before and nothing depends on step 9, which is why MANIFEST.json can be the
# single declared exclusion from its own closure. See build_receipts.py.
set -euo pipefail

COMMIT="${1:?usage: release.sh <integration-sha>}"
REF="cursor/scp-c-authorship-sidecar-696d"
LANE="workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c"
RAW="receipts/so02/2026-08-27/scp-c/raw"
GATE="workstreams/so02/control-plane/operating-environment/tools/write_admission.py"
SIDECAR="$LANE/sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json"
DECL="workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-C.json"

mkdir -p "$RAW"

echo "== 1. test suite"
python3 -I "$LANE/tools/test_authorship_sidecar.py" > "$RAW/unittest-verbose.txt" 2>&1
tail -3 "$RAW/unittest-verbose.txt"

echo "== 2. prior defect, against the estate's live provctl.py"
python3 -I "$LANE/tools/reproduce_prior_defect.py" --repo-root . > "$RAW/defect-reproduction.txt" 2>&1
tail -2 "$RAW/defect-reproduction.txt"

echo "== 3. rebuild the sidecar over the real slice"
python3 -I "$LANE/tools/run_slice.py" --repo-root . --commit "$COMMIT" > "$RAW/slice-run.txt" 2>&1
tail -6 "$RAW/slice-run.txt"

echo "== 4. recompute the committed sidecar against its pinned sources"
python3 -I "$LANE/tools/authorship_sidecar.py" verify "$SIDECAR" --repo-root . > "$RAW/sidecar-verify.txt" 2>&1
tail -2 "$RAW/sidecar-verify.txt"

echo "== 5. read-back: hash and parse every structured artifact"
python3 -I "$LANE/tools/build_receipts.py" --repo-root . --commit "$COMMIT" --stage read-back

echo "== 6. write declaration, hashes generated from disk"
python3 -I "$LANE/tools/build_declaration.py" --repo-root . --ref "$REF" --commit "$COMMIT" --ref-absent

echo "== 7. is the declaration's evidence true of the disk"
python3 -I "$LANE/tools/verify_declaration_evidence.py" --repo-root . | tee "$RAW/declaration-evidence-check.txt"

echo "== 8. the write admission gate, invoked explicitly"
set +e
python3 -I "$GATE" "$DECL" --repo "$PWD" > "$RAW/admission-summary.txt" 2>&1
GATE_STATUS=$?
python3 -I "$GATE" "$DECL" --repo "$PWD" --json > receipts/so02/2026-08-27/scp-c/ADMISSION.json 2>"$RAW/admission-json-stderr.txt"
set -e
cat "$RAW/admission-summary.txt"

echo "== 8b. the gap in the gate's own evidence check, reproduced against the live gate"
# After step 6, because the reproduction needs a declaration that is currently
# true of the disk in order to isolate the gate's blindness from ordinary
# staleness. Before step 9, because its output is a receipt the manifest covers.
python3 -I "$LANE/tools/reproduce_gate_blindness.py" --repo-root . > "$RAW/gate-blindness-reproduction.txt" 2>&1
tail -3 "$RAW/gate-blindness-reproduction.txt"

echo "== 9. manifest closure over everything above"
python3 -I "$LANE/tools/build_receipts.py" --repo-root . --commit "$COMMIT" --stage manifest

if [ "$GATE_STATUS" -ne 0 ]; then
    echo "WRITE_REFUSED - the gate refused; its verdict is recorded in ADMISSION.json and this"
    echo "script exits non-zero so a refusal is not mistaken for an admission."
    exit "$GATE_STATUS"
fi
echo "WRITE_ADMITTED"
