# PO03-WA-024 bounded source capsule
# claim_id:  sc-wa024-02-checkout-readme.txt
# url:       https://raw.githubusercontent.com/actions/checkout/11bd71901bbe5b1630ceea73d27597364c9af683/README.md
# commit:    11bd71901bbe5b1630ceea73d27597364c9af683
# sha256:    5b1198a8e20cbdd5c484f23d01755884f4d53da10b26f179599517bbe695f91b
# bytes:     9359
# locator:   lines 5-9
# excerpt:   verbatim, bounded; the full document is retrievable at the url above
# ---
This action checks-out your repository under `$GITHUB_WORKSPACE`, so your workflow can access it.

Only a single commit is fetched by default, for the ref/SHA that triggered the workflow. Set `fetch-depth: 0` to fetch all history for all branches and tags. Refer [here](https://docs.github.com/actions/using-workflows/events-that-trigger-workflows) to learn which commit `$GITHUB_SHA` points to for different events.

The auth token is persisted in the local git config. This enables your scripts to run authenticated git commands. The token is removed during post-job cleanup. Set `persist-credentials: false` to opt-out.
