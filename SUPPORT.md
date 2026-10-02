# Support boundary

This recipe is a single-replica evaluation/learning stack. It is not HA, a production finance agent, a payment system, or a multi-tenant service. The deterministic fixture performs lexical policy retrieval; the optional OpenAI path proposes text, not autonomous tools. Do not accept arbitrary executable workflows, contexts, event types or model-controlled SQL.

## Troubleshooting

- **401 everywhere:** use `Authorization: Bearer $API_TOKEN`. Only exact GET `/healthz` and `/readyz` are public. The browser debugger/docs do not gain a session automatically. Rotate the server token and update clients together.
- **405 native mutation:** intentional. Submit runs and approvals only through the validated `/runs` routes. Raw event, cancel, purge and run-start routes are disabled.
- **409:** the UUID already identifies a different request payload, or an approval decision is being changed. Do not reuse request IDs across distinct operations.
- **503/readiness or lease acquisition timeout:** check PostgreSQL connectivity, migration rights, private DNS and old executor ownership. Stop the old API before replacement; allow 10 seconds for crash lease expiry. Do not fix this by changing the executor prefix or running multiple workers.
- **Pending approval after restart:** check the persisted run ID and `/runs/{id}/events`; POST the decision once or retry the same decision. The reconciler reads durable approvals and retries event delivery. Preserve the database and workflow identity. DBOS recovery attempts are capped at 20; investigate persistent failures rather than deleting historical state.
- **Hosted proposal failure:** check server-side credentials, model access, timeout and outbound HTTPS. No provider response body or credential is returned by the provider adapter. Do not set a real key for offline verification. Switching model/code while runs are pending requires an upgrade plan.
- **Database full:** investigate events/journal history and volume metrics. There is no automatic retention policy. Back up before introducing one; deleting tick/run rows can break recovery. The demo reconciler scans its request history and is not optimized for an unbounded production backlog.

Health responses contain only `{ "ok": true/false }`, never database URLs, run IDs, approvals or error details. Authorized clients share one admin-level API token and can read all demo runs. Restrict ingress, use TLS, establish tenant/RBAC controls and proper backup/restore before any production adaptation. Private Railway networking is the default DB boundary; verify encryption requirements separately for your workload.

Local verifier resources are confined to project `rt-llama-cb5c13c4`, loopback port 18211 and its own volume. Never run global Docker prune or remove another template's containers. For upstream defects consult [LlamaIndex](https://github.com/run-llama/llama-agents/issues) and [DBOS](https://github.com/dbos-inc/dbos-transact-py/issues).
