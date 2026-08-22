# A13 authorship freeze declaration

I, `po03-worker-a13`, declare that the introducing commit of this file is the
blind-authorship freeze for the evaluator-held suite.

Before that commit:

- I did not read any file under `workstreams/po03/successor/`.
- I did not fetch or inspect
  `cursor/po03-a8-successor-generations-ed20`.
- I did not read cohort a8's generations, harness, scoring code, tests or
  conclusions.
- I authored the cases from PO-03 commission revision v002, its transactional
  contracts, the immutable a13 holdout dispatches, the recorded producer
  custody defects and the binding snapshot-coupling rule.
- I did not compare these cases with the public suite, because doing so before
  freeze would violate the independence requirement.

The suite contains 32 executable cases.  Each has an explicit commission
citation, preregistered input and pass oracle, plus a stated independently
devised variation that a plausible broken implementation can fail.

`FREEZE_MANIFEST.json` binds the exact source and evaluator-test bytes.  The
freeze commit is the first commit containing both this declaration and that
manifest; its SHA is recorded in the a13-u01 result document after the commit
exists.  Files frozen by that commit are not edited after a8 material is read.
Any evaluator adapters, transcripts, novelty comparison or verdict created
later are separate post-freeze evidence.
