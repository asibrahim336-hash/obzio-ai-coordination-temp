# Execution evidence

Command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-003-nonportable-path-detector/test_nonportable_path_detector.py`

Exit code: `0`

Verbatim combined terminal output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 10.881s

OK
```

The committed-text fixture produced four findings covering a user home,
home-relative path, temporary root and machine root. A NUL-bearing blob and a
file outside `workstreams/po03` were not scanned. A path-, pattern- and
line-specific documentation allowlist suppressed only its declared finding,
and a relative-path control passed.

Observed limitation: the scanner reads UTF-8 text blobs and intentionally skips
binary and non-UTF-8 artifacts; paths encoded inside those formats require a
format-specific extractor.
