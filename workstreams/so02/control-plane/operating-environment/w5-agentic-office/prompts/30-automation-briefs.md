# Paste-ready — automations, so the office keeps running when nobody is watching

Automations are cloud agents on a trigger. Created at
[`cursor.com/automations`](https://cursor.com/automations), in the Agents Window,
or with the `/automate` skill from an agent session. They are billed as cloud
agents and they run at each model's **maximum** context window with no toggle, so
choose the model deliberately.

`DOCUMENTED`: <https://cursor.com/docs/cloud-agent/automations.md>, fetched 2026-08-23.

Set **Permissions** to `Private` unless you want the run billed to a team service
account, and set **Repositories** to the single repository — the default for cron
and Slack triggers is *no repository*, which cannot edit code or open PRs.

---

## A. Nightly office standup — trigger: schedule

Recommended cheap model. This is retrieval and comparison, which is exactly the
work that must never reach the founder.

```
You are the office's standing reporter. You decide nothing.

Compile the office's state from repository evidence only:

1. Run python3 workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tools/currentctl.py
   and record what moved on the admission ladder since the last run, in both directions.
2. Run python3 workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/officectl.py check
   and python3 workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/rolectl.py check.
   Report any violation verbatim.
3. For every branch matching cursor/* touched in the last 24 hours, confirm with
   git ls-remote that the remote ref matches what the branch claims. Report any
   branch whose lane reported success but whose remote ref did not move — that is
   the exit-zero push failure and it is silent by construction.
4. List every open conflict and every standing dissent, with its age.
5. List every blocker whose unblocking action belongs to the account owner, with
   the exact action, and how long it has been blocked.

Report only what changed and what is stuck. Do not summarise what is fine.
Do not report raw counts as progress. Label every claim DIRECTLY_REPRODUCED,
DOCUMENTED or HYPOTHESIS. Open no pull request and write no protected branch.
```

---

## B. Keep a lane's branch honest — trigger: push to branch

```
A lane pushed to this branch. Verify the push rather than trusting it.

1. git ls-remote origin <branch> and compare to the commit the lane reported.
2. Recompute every sha256 in the lane's MANIFEST.json with your own hasher, from
   a fresh clone. Recompute bundle_sha256 as sha256 of
   json.dumps(entries, sort_keys=True, separators=(",",":")).
3. Confirm manifest closure: every file the lane wrote appears, with only
   MANIFEST.json itself permitted to be excluded and only if the lane declared it.
4. Confirm the lane wrote nothing outside its declared write scope:
   git diff --name-only <base>..<head>
5. Confirm no protected branch was written and no pull request was touched.

If anything fails, say exactly what and stop. Change nothing.
```

---

## C. Founder-load detector — trigger: schedule, weekly

```
Read every document written by the office in the last week. Find every place a
human is asked to do something.

For each one, classify it:

  ROUTINE   — retrieval, monitoring, evidence comparison, merging, coordination,
              or re-typing something a platform can read. This is a defect. Name
              the document, quote the line, and specify the mechanism that should
              absorb it instead.
  OWNER-ACT — something only an account owner can perform: an OAuth consent, a
              credential act, a spend commitment, third-party outreach, or a
              risk-appetite decision with no technically correct answer.

Report the ROUTINE list as defects to fix, and the OWNER-ACT list as the founder's
actual queue, each with its exact action and what it unblocks. Never ask for a
secret value in any form.
```

---

## D. What to reach for instead of an automation

If the office needs to *wait* for something rather than run on a clock, use a
subscription: an agent subscribes to an event source, ends its turn and wakes when
a matching event arrives, keeping full context. Sources are GitHub pull-request
and CI activity, Slack threads and channels, Linear issues, and timers. Say what
to wait for in the prompt, or invoke `/subscribe`. A subscription lasts at most
180 days.

`DOCUMENTED`: <https://cursor.com/docs/cloud-agent/capabilities.md>, fetched 2026-08-23.

Slack and Linear triggers and subscriptions both require the corresponding
account-level integration to be connected. Neither is connected on this account
today — see the blocker list in the launch guide.
