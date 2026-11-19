# Instructions for coding agents

- When continuing this bridge work, read [`docs/HANDOFF.md`](docs/HANDOFF.md) first. It records the verified state, the local changes, the test evidence and the next safe steps; preserve the existing working tree.
- The France Student API contract is **public**: <https://api.francestudent.ai/v3/api-docs>. Implement only what that specification describes, and keep a copy in [`docs/francestudent-openapi.json`](docs/francestudent-openapi.json). Never guess an endpoint, a header or a request shape.
- Read [`docs/FS_CLIENT_TOOLS.md`](docs/FS_CLIENT_TOOLS.md) before touching the tool loop. France Student has a native client-tool protocol (`clientTools` → `function_call` → `toolResults`); the bridge uses it. The pseudo-tool protocol of the first version is **refused** by the models.
- Read [`docs/FS_API_ACCESS.md`](docs/FS_API_ACCESS.md) before any live France Student request. Authentication is either the official API key (`/user/@me/api-key`, currently not enabled for this account) or the browser session exported by `scripts/fs_session_login.js`.
- Do not create accounts or multiply conversations to evade an authentication refusal, a rate limit, a moderation flag or an anti-abuse block. Stop live tests and ask for official API access instead.
- Never guess France Student model names or IDs. Use the canonical `id` returned by the bridge's live `/v1/models` endpoint; treat `fs_agent_id` as the upstream routing ID, not an OpenCode selector name.
- A model refresh replaces the `providers.france-student.models` map with the currently active catalog. Preserve every unrelated OpenCode setting, provider, plugin and default model.
- Do not read, print, copy into configs, or commit `.env`, `.fs-session.json`, `store.json`, or session database contents. They contain credentials or session metadata.
- Stay below the published France Student quotas: 50 new chats per day and 100 chat messages per hour. The bridge guards itself with `FS_MAX_MESSAGES_PER_HOUR` and `FS_MAX_NEW_CHATS_PER_DAY`; do not raise them above the published limits, and keep auxiliary requests (session titles) local.
- Keep the message sent to France Student flat. The models refuse to act when the request is dressed up as another agent's harness, so the OpenCode system prompt is dropped by default (`FS_FORWARD_SYSTEM_PROMPT`).
- Before applying a config change, show the provider model diff and validate the generated JSON. Restart OpenCode after changing its config.
