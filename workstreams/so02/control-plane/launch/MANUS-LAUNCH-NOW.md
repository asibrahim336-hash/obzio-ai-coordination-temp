# Manus owner-gated launch now

Edge Function version 9 is active. The authorised connector can deploy and inspect
the function but cannot invoke it; invocation additionally requires the founder-held
`x-ops-gate`, which must never be pasted into chat or committed.

## Exact owner clicks

1. Open Supabase Dashboard project `wsnyawtbhspbkwuckpam` → **Edge Functions** →
   `aoi-manus-admin-20260821` → **Invoke**.
2. Select `POST`. Add `Content-Type: application/json` and add `x-ops-gate` using
   the saved gate value. Do not reveal or copy that value anywhere else.
3. Paste the body below and click **Send**.

```json
{
  "action": "launch",
  "operation_key": "aoi:20260822:manus-multi-account-admin-v1",
  "agent_profile": "manus-1.6-max",
  "interactive_mode": true,
  "prompt": "Start substantive work now. Build and execute a multi-account administrative enablement plan across the accounts and connectors actually visible to you. For every account or connector, record its visible capability, requested scope, configured state, verification effect, owner-only action, failure, recovery and stop condition. Use only the access necessary for each action. Surface an exact OAuth, installation, approval, authentication, download or account-owner step immediately when it is the efficient next action, while continuing unaffected work. Do not conduct outreach, purchase, publish, delete, expose secrets or make production changes. Return a manifest and hashes, actual configured effects, task lifecycle evidence, and the exact provider blocker for anything you cannot complete. Provider completion alone is not acceptance."
}
```

4. A `201` response must contain `task_id`; open that task and approve/authenticate
   only the exact surfaced scopes. A non-201 response is the provider/route blocker;
   preserve the safe error body and request ID. Do not retry the same operation key
   with a different payload.

