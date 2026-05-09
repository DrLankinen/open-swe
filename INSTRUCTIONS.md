# Open SWE Polling Setup Instructions

These instructions are for the polling-based setup. In this mode, Open SWE fetches GitHub and Linear comments directly instead of receiving GitHub or Linear webhooks.

You do not need ngrok.

You do not need GitHub or Linear webhook URLs.

## How It Works

1. You run the Open SWE LangGraph server.
2. You run a separate poller process.
3. The poller checks GitHub and Linear on a timer.
4. If it finds a new comment containing `@openswe`, it creates a LangGraph agent run.
5. The agent creates or reconnects to a sandbox.
6. The agent works on the target repository, pushes changes, opens or updates a PR, and replies back.

## What You Need To Run

You need two running processes:

```text
Process 1: LangGraph/Open SWE server
Process 2: Open SWE poller worker
```

The server hosts the agent graph.

The poller repeatedly checks GitHub and Linear for new comments.

## 1. Install Dependencies

```bash
uv venv
source .venv/bin/activate
uv sync --all-extras
```

## 2. Set Up A GitHub App

You still need a GitHub App so Open SWE can read repositories, push branches, and open PRs.

You do not need to configure GitHub webhooks.

Create a GitHub App with these repository permissions:

```text
Contents: Read and write
Pull requests: Read and write
Issues: Read and write
Metadata: Read-only
```

Install the GitHub App on the repositories Open SWE should access.

Save these values:

```bash
GITHUB_APP_ID=""
GITHUB_APP_PRIVATE_KEY=""
GITHUB_APP_INSTALLATION_ID=""
```

You can skip `GITHUB_WEBHOOK_SECRET` unless you also want to keep webhook support enabled.

## 3. Set Up Linear

You do not need a Linear webhook.

Create a Linear API key and set:

```bash
LINEAR_API_KEY=""
```

The poller fetches comments directly from Linear through the Linear GraphQL API.

## 4. Set Up LangSmith

Open SWE uses LangSmith for tracing and, by default, cloud sandboxes.

Set these values:

```bash
LANGSMITH_API_KEY_PROD=""
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT=""
LANGSMITH_TENANT_ID_PROD=""
LANGSMITH_TRACING_PROJECT_ID_PROD=""
LANGSMITH_URL_PROD="https://smith.langchain.com"
```

Create or reuse a LangSmith sandbox snapshot and set:

```bash
DEFAULT_SANDBOX_SNAPSHOT_ID=""
```

The sandbox image should include GitHub CLI because Open SWE uses `gh` inside the sandbox.

## 5. Set Up The Model API Key

The repo defaults to:

```text
openai:gpt-5.5
```

So set:

```bash
OPENAI_API_KEY=""
```

To call OpenAI-compatible models through Azure AI Foundry instead of OpenAI directly, set your Azure OpenAI v1 endpoint and key:

```bash
LLM_MODEL_ID="openai:gpt-5.5"
AZURE_OPENAI_ENDPOINT="https://YOUR-RESOURCE.openai.azure.com"
AZURE_OPENAI_API_KEY=""
```

You can also set `AZURE_OPENAI_BASE_URL` directly, for example `https://YOUR-RESOURCE.openai.azure.com/openai/v1/`.

Or override the model:

```bash
LLM_MODEL_ID="anthropic:claude-sonnet-4-6"
ANTHROPIC_API_KEY=""
```

## 6. Configure Polling

Set these environment variables:

```bash
TRIGGER_MODE="poll"

ENABLE_GITHUB_POLLER="true"
ENABLE_LINEAR_POLLER="true"

GITHUB_POLL_REPOS="owner/repo,another-owner/another-repo"

POLL_INTERVAL_SECONDS="30"
```

Important behavior:

```text
TRIGGER_MODE=poll is required.
GITHUB_POLL_REPOS is required if ENABLE_GITHUB_POLLER=true.
ENABLE_GITHUB_POLLER defaults to true.
ENABLE_LINEAR_POLLER defaults to true.
POLL_INTERVAL_SECONDS defaults to 30.
```

If you only want Linear polling:

```bash
TRIGGER_MODE="poll"
ENABLE_GITHUB_POLLER="false"
ENABLE_LINEAR_POLLER="true"
POLL_INTERVAL_SECONDS="30"
```

If you only want GitHub polling:

```bash
TRIGGER_MODE="poll"
ENABLE_GITHUB_POLLER="true"
ENABLE_LINEAR_POLLER="false"
GITHUB_POLL_REPOS="owner/repo"
POLL_INTERVAL_SECONDS="30"
```

## 7. Configure Repository Access

Set the default repository:

```bash
DEFAULT_REPO_OWNER="your-org"
DEFAULT_REPO_NAME="your-repo"
```

Optionally restrict what the agent can access:

```bash
ALLOWED_GITHUB_ORGS="your-org"
ALLOWED_GITHUB_REPOS="your-org/your-repo,your-org/another-repo"
```

For Linear, configure team/project to repo mapping in:

```text
agent/utils/linear_team_repo_map.py
```

Users can also specify the repo directly in a Linear comment:

```text
@openswe fix this repo:owner/repo
```

## 8. Configure GitHub User Mapping

GitHub-triggered runs require the commenter GitHub username to map to an email.

Edit:

```text
agent/utils/github_user_email_map.py
```

Example:

```python
GITHUB_USER_EMAIL_MAP = {
    "github-username": "person@example.com",
}
```

If this mapping is missing, GitHub comments from that user will be skipped.

## 9. Configure Token Encryption

Set this once and keep it stable:

```bash
TOKEN_ENCRYPTION_KEY=""
```

Generate it with:

```bash
openssl rand -base64 32
```

Do not casually rotate this value. Encrypted user OAuth tokens depend on it.

## 10. Example `.env`

```bash
# Mode
TRIGGER_MODE="poll"
POLL_INTERVAL_SECONDS="30"

# Pollers
ENABLE_GITHUB_POLLER="true"
ENABLE_LINEAR_POLLER="true"
GITHUB_POLL_REPOS="your-org/your-repo"

# LangGraph
LANGGRAPH_URL="http://localhost:2024"

# LangSmith
LANGSMITH_API_KEY_PROD=""
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT=""
LANGSMITH_TENANT_ID_PROD=""
LANGSMITH_TRACING_PROJECT_ID_PROD=""
LANGSMITH_URL_PROD="https://smith.langchain.com"

# Model
OPENAI_API_KEY=""

# GitHub App
GITHUB_APP_ID=""
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
"
GITHUB_APP_INSTALLATION_ID=""

# Linear
LINEAR_API_KEY=""

# Repo defaults and allowlist
DEFAULT_REPO_OWNER="your-org"
DEFAULT_REPO_NAME="your-repo"
ALLOWED_GITHUB_ORGS="your-org"
ALLOWED_GITHUB_REPOS="your-org/your-repo"

# Sandbox
DEFAULT_SANDBOX_SNAPSHOT_ID=""

# Encryption
TOKEN_ENCRYPTION_KEY=""
```

## 11. Start The LangGraph Server

In one terminal:

```bash
uv run langgraph dev --no-browser
```

By default, this runs at:

```text
http://localhost:2024
```

If deployed, set `LANGGRAPH_URL` to your deployed LangGraph server URL.

## 12. Start The Poller

In a second terminal:

```bash
uv run python -m agent.poller_main
```

The poller will:

```text
check GitHub repositories from GITHUB_POLL_REPOS
check Linear comments using LINEAR_API_KEY
look for @openswe
dedupe already processed comments
create LangGraph runs
sleep for POLL_INTERVAL_SECONDS
repeat
```

## 13. Trigger Open SWE

GitHub issue comment:

```text
@openswe what files are in this repo?
```

GitHub PR conversation comment:

```text
@openswe address this feedback
```

GitHub inline PR review comment:

```text
@openswe fix this line
```

Linear comment:

```text
@openswe implement this issue
```

Linear comment with explicit repo:

```text
@openswe implement this repo:your-org/your-repo
```

## 14. Important Poller Behavior

The poller starts with a short lookback window.

If there is no saved cursor yet, it looks back about 5 minutes. After starting the poller for the first time, create a fresh `@openswe` comment instead of expecting it to process old comments.

Processed comments and cursors are stored in the LangGraph store.

## Production Setup

For production, run both processes continuously:

```text
Process 1: LangGraph/Open SWE server
Process 2: poller worker
```

Set:

```bash
LANGGRAPH_URL="https://your-langgraph-server-url"
TRIGGER_MODE="poll"
```

You do not need public GitHub or Linear webhook URLs.

You do need outbound internet access from the poller to:

```text
api.github.com
api.linear.app
smith.langchain.com
model provider API
```

## Maintenance

1. Keep both processes running.

If the server stops, the agent cannot run. If the poller stops, new GitHub and Linear comments are not detected.

2. Run one poller instance unless you intentionally design for multiple workers.

Multiple pollers can race and may duplicate work.

3. Keep `GITHUB_POLL_REPOS` updated.

The GitHub poller only checks repositories listed in `GITHUB_POLL_REPOS`.

4. Keep Linear mappings updated.

Maintain:

```text
agent/utils/linear_team_repo_map.py
```

or ask users to include:

```text
repo:owner/repo
```

5. Keep GitHub user email mapping updated.

Maintain:

```text
agent/utils/github_user_email_map.py
```

6. Monitor logs.

Watch for:

```text
GitHub polling failed
Linear polling failed
No email mapping for GitHub user
Repository not in allowlist
Cannot poll Linear: LINEAR_API_KEY is not configured
Cannot poll GitHub: GitHub App installation token is unavailable
```

7. Monitor LangSmith.

Use LangSmith to inspect failed agent runs, tool errors, model errors, and sandbox failures.

8. Protect persistent state.

Poller cursors and dedupe state live in the LangGraph store. If that store is wiped, the poller may reprocess recent comments or lose its position.

9. Rotate secrets carefully.

Rotate if compromised:

```text
GITHUB_APP_PRIVATE_KEY
LINEAR_API_KEY
LANGSMITH_API_KEY_PROD
OPENAI_API_KEY or ANTHROPIC_API_KEY
```

Do not casually rotate:

```text
TOKEN_ENCRYPTION_KEY
```

10. Rebuild sandbox snapshots when tooling changes.

If your repositories need new system dependencies or dev tools, rebuild the sandbox snapshot and update:

```bash
DEFAULT_SANDBOX_SNAPSHOT_ID=""
```

## Shortest Working Version

1. Set up the GitHub App and install it on your repo.
2. Set `LINEAR_API_KEY` if using Linear.
3. Set LangSmith, model, sandbox, GitHub App, and encryption env vars.
4. Set:

```bash
TRIGGER_MODE="poll"
GITHUB_POLL_REPOS="your-org/your-repo"
LANGGRAPH_URL="http://localhost:2024"
```

5. Start the server:

```bash
uv run langgraph dev --no-browser
```

6. Start the poller:

```bash
uv run python -m agent.poller_main
```

7. Comment on GitHub or Linear:

```text
@openswe what files are in this repo?
```
