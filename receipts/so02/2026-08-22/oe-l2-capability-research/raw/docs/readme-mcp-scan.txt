Snyk Agent Scan

Discover and scan agent components on your machine for prompt injections

and vulnerabilities (including agents, MCP servers, skills).

> **Note: CLI output is experimental and subject to change**
>
> **Agent Scan v0.5.x (planned for deprecation)**
>
> The raw output of this CLI — including issue codes, field names, severity labels, and response structure — is experimental and may change without notice between releases. We do not recommend building production workflows that depend on specific CLI output fields or issue codes.
>
> **Agent Scan v0.6 and later**
>
> The raw output of this CLI — including risk indicator names, scores, field names, and response structure — is experimental and may change without notice between releases. We do not recommend building production workflows that depend on specific CLI output fields or risk names.
>
> If you are an enterprise customer using Snyk to manage agent security risk at scale, the CLI output may not reflect what is sent to and shown in the Evo platform. The underlying integration, discovery, and risk assessment that powers enterprise deployments is stable and supported — any changes will be communicated in line with standard Snyk product practices. Contact your account team for deployment guidance.

> **NEW** Read our [technical report on the emerging threats of the agent skill eco-system](.github/reports/skills-report.pdf) published together with Agent Scan 0.4, which adds support for scanning agent skills.

### Agent Scan v0.5.x output

> [!WARNING]
> Agent Scan v0.5.x uses issue-code output. This CLI line is planned for deprecation.

### Agent Scan v0.6 and later output

Agent Scan helps you discover all your installed agent components (harnesses, MCP servers, and skills) and scans them for common threats like prompt injections, sensitive data handling, or malware payloads hidden in natural language. Ignore analysis on skills by using `--no-skills`.

## Security Warning

> **⚠️ IMPORTANT: Scanning MCP configurations will execute the commands defined in them.**
>
> When Agent Scan scans an MCP configuration file, it starts the stdio MCP servers by executing the commands and arguments specified in the config. This is necessary to retrieve tool descriptions and perform security analysis.
>
> **Recommendations:**
> - **Run scans inside a sandbox** (Docker container, VM, or disposable environment) when evaluating untrusted or third-party MCP configs
> - **Review the consent prompt carefully** during interactive scans, it shows the exact command and arguments that will be executed for each server
> - **Use `--dangerously-run-mcp-servers`** only in trusted environments where you've verified all MCP server commands
>
> By default, Agent Scan requires explicit user consent (y/n) before starting each stdio MCP server during interactive runs. This gives you control over what gets executed on your system.

## Quick Start

Choose one of two ways to run Agent Scan:

1. **Run the Python package with `uvx`** using the instructions below.
2. **Download a standalone binary** for your platform from [GitHub Releases](https://github.com/snyk/agent-scan/releases). Releases also include the SBOM, checksums, signed checksums, and source code archives.

Before using either option:

1. **Sign up at [Snyk](https://snyk.io)** and get an API token from [https://app.snyk.io/account](https://app.snyk.io/account) (API Token → KEY → click to show).
2. **Set the token as an environment variable** before running any scan:
```bash
export SNYK_TOKEN=your-api-token-here
```

### Run with `uvx`

Have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed on your system. Choose the instructions for your CLI version.

#### Agent Scan v0.5.x

The examples pin v0.5.17 as a concrete v0.5.x release:

```bash
# Scan the whole machine
uvx snyk-agent-scan@0.5.17

# Scan a specific MCP configuration
uvx snyk-agent-scan@0.5.17 ~/.vscode/mcp.json

# Scan a single agent skill
uvx snyk-agent-scan@0.5.17 ~/path/to/my/SKILL.md

# Scan all Claude skills
uvx snyk-agent-scan@0.5.17 ~/.claude/skills
```

> [!WARNING]
> v0.5.x uses issue-code output and the `2025-09-02` analysis API. This CLI line is planned for deprecation.

#### Agent Scan v0.6 and later

```bash
# Scan the whole machine
uvx snyk-agent-scan@latest

# Scan a specific MCP configuration
uvx snyk-agent-scan@latest ~/.vscode/mcp.json

# Scan a single agent skill
uvx snyk-agent-scan@latest ~/path/to/my/SKILL.md

# Scan all Claude skills
uvx snyk-agent-scan@latest ~/.claude/skills
```

v0.6 and later use the risk-based output and the `2026-07-10` analysis API.

Both versions scan MCP servers, tools, prompts, resources, and skills, and automatically discover supported agent configurations such as Claude Code/Desktop, Cursor, Gemini CLI, and Windsurf.

### Run with a standalone binary

Download the binary for your operating system and architecture from the [latest GitHub Release](https://github.com/snyk/agent-scan/releases/latest). The release page also provides an SBOM (`sbom- .json`), checksum files, and GitHub-generated source code archives. See [Verifying Standalone Binaries](#verifying-standalone-binaries) to verify your download.

### Agent Scan v0.5.x example run

[![Agent Scan v0.5 security vulnerabilities demo](demo.svg)](https://asciinema.org/a/716858)

For the v0.6 risk-based output, see the v0.6 image at the top of this README.

## Highlights

- Auto-discover MCP configurations, agent tools, skills
- Scanning of Claude, Cursor, Windsurf, Gemini CLI, Amp, Amazon Q, and other agents.

### Agent Scan v0.5.x

- Detects [15+ distinct security risks](docs/issue-codes.md) across MCP servers and agent skills:
- MCP: [Prompt Injection](docs/issue-codes.md#E001), [Tool Poisoning](docs/issue-codes.md#E001), [Tool Shadowing](docs/issue-codes.md#E002), [Toxic Flows](docs/issue-codes.md#ToxicFlows)
- Skills: [Prompt Injection](docs/issue-codes.md#E004), [Malware Payloads](docs/issue-codes.md#E006), [Untrusted Content](docs/issue-codes.md#W011), [Credential Handling](docs/issue-codes.md#W007), [Hardcoded Secrets](docs/issue-codes.md#W008)

### Agent Scan v0.6 and later

- Detects [15 distinct security risks](docs/risks.md) across MCP servers and agent skills:
- MCP: [Prompt injection](docs/risks.md#prompt_injection_tool_desc), [dangerous words](docs/risks.md#dangerous_words), [untrusted content](docs/risks.md#untrusted_content), [private data](docs/risks.md#private_data), and [destructive capabilities](docs/risks.md#destructive_capabilities)
- Skills: [prompt injection](docs/risks.md#prompt_injection_skill_instructions), [suspicious downloads](docs/risks.md#suspicious_download_url), [malicious code](docs/risks.md#malicious_code), [credential handling](docs/risks.md#insecure_credential_handling), [secret detection](docs/risks.md#secret_detection), and more

## Supported agents and capabilities

Agent Scan auto-discovers agents and their capabilities (MCP servers or skills) when their install paths exist. The table below shows on which operating systems each agent is scanned.

- **✓**: at least one path is defined for that capability.
- **✗**: the agent is listed for that OS but has no paths for that capability.
- **—**: that agent is not included for that OS.
- **Skills** Skills can be ignored by using `--no-skills`

| Agent | macOS MCP | macOS Skills | Linux MCP | Linux Skills | Windows MCP | Windows Skills |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Windsurf | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cursor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| VS Code | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Claude Desktop | ✓ | ✗ | — | — | ✓ | ✗ |
| Claude Code | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Gemini CLI | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| OpenClaw | ✗ | ✓ | ✗ | ✓ | ✗ | ✓ |
| Amp | ✗ | ✓ | ✗ | ✓ | ✗ | ✓ |
| Kiro | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| OpenCode | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Antigravity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Codex | ✓ | ✓ | ✓ | ✓ | — | — |
| Amazon Q | ✓ | ✗ | ✓ | ✗ | ✓ (WSL) | ✗ |

### Detection coverage by scope

The matrix above shows on which operating systems each agent is scanned. This one breaks detection down by **configuration scope** and **component type** (skills vs MCP servers), combined across operating systems. "Servers" means MCP servers.

The four scopes:

- **System** — machine-wide / admin-managed / enterprise config that applies to all users (e.g. `managed-mcp.json`, files under `/etc`, `/Library/Application Support`, or `ProgramData`).
- **User** — the user's home-directory config (applies across all their projects).
- **Project / workspace** — config scoped to an opened project or workspace.
- **Extension / plugin** — components bundled inside installed extensions or plugins.

Legend: **✓** detected · **✗** the agent supports this but Agent Scan does not scan it yet · **N/A** the agent has no such component at this scope.

| Agent | System
skills | System
servers | User
skills | User
servers | Project / WS
skills | Project / WS
servers | Ext / plugin
skills | Ext / plugin
servers |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Windsurf | ✓ | N/A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cursor | N/A | N/A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| VS Code | N/A | N/A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Claude Desktop | N/A | N/A | ✗ | ✓ | N/A | N/A | N/A | ✗ |
| Claude Code | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Gemini CLI | N/A | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| OpenClaw | N/A | N/A | ✓ | ✗ | ✓ † | N/A | ✗ | ✗ |
| Amp | N/A | ✗ | ✓ | ✗ | ✗ ‡ | ✗ | ✗ | ✗ |
| Kiro | N/A | N/A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| OpenCode | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N/A | N/A |
| Antigravity | N/A | N/A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Codex | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Amazon Q | N/A | N/A | N/A | ✓ | N/A | ✗ | N/A | N/A |

† OpenClaw has no opened-project enumeration: its project/workspace skills are found only at the fixed `~/.openclaw/workspace/skills`

‡ Amp stores project/workspace skills at `.agents/skills` (and the `.claude/skills` compatibility path); only the user-scope `~/.config/agents/skills` is detected today, so project-scope skills are supported but not yet scanned.

## Verifying Standalone Binaries

We use GPG signing on the release checksums file to ensure distribution integrity and authenticity.

### Step-by-Step Verification Guide

1. **Download the release assets:**
Download the binary for your platform (e.g., `agent-scan- - - `) and the signed checksums file (`sha256sums.txt.asc`) from the [GitHub Releases](https://github.com/snyk/agent-scan/releases) page into the same directory.

2. **Verify GPG signature of the checksums file:**
Download the [GPG public key](https://github.com/snyk/agent-scan/blob/main/help/_about-this-project/snyk-code-signing-public.pgp) into the same directory, then run:
```bash
gpg --import snyk-code-signing-public.pgp
gpg --verify sha256sums.txt.asc
```
Look for a line in the output saying `gpg: Good signature from "Snyk Limited "`.

3. **Verify the binary's integrity:**
After confirming the signature is valid, check that your downloaded binary matches the checksum:
* **On Linux (or macOS with `coreutils`):**
```bash
grep agent-scan- - - sha256sums.txt.asc | sha256sum -c -
```
* **On macOS (using default `shasum`):**
```bash
grep agent-scan- - - sha256sums.txt.asc | shasum -a 256 -c -
```
This will output `agent-scan- - - : OK`.

## Scanner Capabilities

### Agent Scan v0.5.x

Agent Scan is a security scanning tool to both scan and inspect the supply chain of agent components on your machine. It scans for common security vulnerabilities like prompt injections, tool poisoning, toxic flows, or vulnerabilities in agent skills.

### Agent Scan v0.6 and later

Agent Scan reports scored risk indicators for threats such as prompt injection, exposure to untrusted or private data, destructive capabilities, and malicious agent skills.

Agent Scan operates in two main modes which can be used jointly or separately:

1. **Scan Mode**: The CLI command `snyk-agent-scan` scans the current machine for agents and agent components such as skills and MCP servers. Upon completion, it will output a comprehensive report for the user to review.

2. **Background Mode** (MDM). Agent Scan scans the machine in regular intervals in the background, and reports the results to a [Snyk Evo](https://evo.ai.snyk.io) instance. This can be used by security teams to monitor the company-wide agent supply chain in a central location. To set this up, please [contact us](https://evo.ai.snyk.io/#contact-us).

## How It Works

### Scanning

Agent Scan searches through your local agent's configuration files to find agents, skills, and MCP servers. For MCP, it connects to servers and retrieves tool descriptions.

#### Interactive Consent for MCP Servers

> **⚠️ Security Note**: Scanning an MCP config executes the commands defined in it. Always review what will be executed before approving.

By default, Agent Scan prompts for user consent before starting each stdio MCP server during interactive runs. This consent flow:

- Shows the server name, command, and environment variables (redacted) that will be executed
- Allows you to approve or decline each server individually
- Prevents potentially untrusted servers from running without your explicit permission
- Records declined servers with a `user_declined` error (they are never started)

**Best Practices:**
- Review the command and arguments carefully before approving
- When scanning untrusted or third-party MCP configs, run Agent Scan inside a sandbox (Docker, VM, or disposable environment)
- Decline any servers with unfamiliar or suspicious commands

For non-interactive environments (e.g., CI/CD pipelines), you must use the `--dangerously-run-mcp-servers` flag to bypass the consent prompt and start all servers automatically. **Only use this flag in trusted environments where all MCP server commands have been verified.**

#### Analysis and Validation

Agent Scan validates discovered components with local checks and the Agent Scan API. It sends the component inform