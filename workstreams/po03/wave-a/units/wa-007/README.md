# PO03-WA-007 portable-path scanner

This unit implements and measures `H-PO03-WA-007`: declared portable
artifacts can be checked for absolute, home-relative, temporary, and
checkout-specific path leakage with negligible measured false positives.

## CLI

The scanner uses only the Python standard library.

```text
python3 -I -B workstreams/po03/wave-a/units/wa-007/portable_path_scanner.py \
  --checkout-root /var/lib/ci/checkouts/run-9281/repo \
  portable-artifacts/
```

It emits deterministic JSON to standard output and returns:

- `0` when the complete declared closure is clean;
- `1` when one or more path findings exist;
- `2` when the closure or configuration is invalid.

No path is implicitly excluded. Repeat `--exclude ROOT_RELATIVE_GLOB` for
intentional exclusions. The report records the matched pattern and each
excluded path. A symlink, binary file, invalid UTF-8 file, special file,
missing root, or duplicate file reached through overlapping roots is an error
unless the node is explicitly excluded.

The exact machine-readable closure, exclusion, detection, suppression, and
exit-status rules are frozen in `scan-closure-contract.json`.

## Detection

Each finding includes one-based coordinates, the verbatim token, all matched
categories, and stable rule IDs. A path below a supplied checkout root is both
absolute and checkout-specific. Temporary checkout paths can match absolute,
temporary, and checkout-specific categories at once.

The scanner is conservative around common non-filesystem slash syntax. It
suppresses network URL bodies, URI fragments, regex anchors, versioned service
routes, templated routes, common JSON Pointer roots, and unknown
single-component slash tokens. These bounded suppressions reduce false
positives but are also explicit false-negative limits; ambiguous
multi-component slash-rooted strings remain findings.

## Fixtures and measurement

`fixtures/case-manifest.json` labels every physical line in the positive,
negative, and adversarial corpora. The measurement executable fails if a
label is missing, a required category is absent, a false positive occurs, a
false negative occurs, or scan closure is incomplete.

```text
python3 -I -B workstreams/po03/wave-a/units/wa-007/measure_false_positives.py --pretty
python3 -I -B -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-007/tests -p 'test_*.py' -v
```

The fixtures are test specimens containing intentional non-portable strings;
they are not declared production-portable artifacts.
