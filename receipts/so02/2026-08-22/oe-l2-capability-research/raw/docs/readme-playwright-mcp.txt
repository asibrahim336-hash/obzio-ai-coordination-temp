## Playwright MCP

A Model Context Protocol (MCP) server that provides browser automation capabilities using [Playwright](https://playwright.dev). This server enables LLMs to interact with web pages through structured accessibility snapshots, bypassing the need for screenshots or visually-tuned models.

### Playwright MCP vs Playwright CLI

This package provides MCP interface into Playwright. If you are using a **coding agent**, you might benefit from using the [CLI+SKILLS](https://github.com/microsoft/playwright-cli) instead.

- **CLI**: Modern **coding agents** increasingly favor CLI–based workflows exposed as SKILLs over MCP because CLI invocations are more token-efficient: they avoid loading large tool schemas and verbose accessibility trees into the model context, allowing agents to act through concise, purpose-built commands. This makes CLI + SKILLs better suited for high-throughput coding agents that must balance browser automation with large codebases, tests, and reasoning within limited context windows.
**Learn more about [Playwright CLI with SKILLS](https://github.com/microsoft/playwright-cli)**.

- **MCP**: MCP remains relevant for specialized agentic loops that benefit from persistent state, rich introspection, and iterative reasoning over page structure, such as exploratory automation, self-healing tests, or long-running autonomous workflows where maintaining continuous browser context outweighs token cost concerns.

### Key Features

- **Fast and lightweight**. Uses Playwright's accessibility tree, not pixel-based input.
- **LLM-friendly**. No vision models needed, operates purely on structured data.
- **Deterministic tool application**. Avoids ambiguity common with screenshot-based approaches.

### Requirements
- Node.js 18 or newer
- VS Code, Cursor, Windsurf, Claude Desktop, Goose, Grok, Junie or any other MCP client

### Getting started

First, install the Playwright MCP server with your client.

**Standard config** works in most of the tools:

```js
{
"mcpServers": {
"playwright": {
"command": "npx",
"args": [
"@playwright/mcp@latest"
]
}
}
}
```

[ ](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522playwright%2522%252C%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522%2540playwright%252Fmcp%2540latest%2522%255D%257D) [ ](https://insiders.vscode.dev/redirect?url=vscode-insiders%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522playwright%2522%252C%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522%2540playwright%252Fmcp%2540latest%2522%255D%257D)

Amp

Add via the Amp VS Code extension settings screen or by updating your settings.json file:

```json
"amp.mcpServers": {
"playwright": {
"command": "npx",
"args": [
"@playwright/mcp@latest"
]
}
}
```

**Amp CLI Setup:**

Add via the `amp mcp add` command below

```bash
amp mcp add playwright -- npx @playwright/mcp@latest
```

Antigravity

Add via the Antigravity settings or by updating your configuration file:

```json
{
"mcpServers": {
"playwright": {
"command": "npx",
"args": [
"@playwright/mcp@latest"
]
}
}
}
```

Claude Code

Use the Claude Code CLI to add the Playwright MCP server:

```bash
claude mcp add playwright npx @playwright/mcp@latest
```

Claude Desktop

Follow the MCP install [guide](https://modelcontextprotocol.io/quickstart/user), use the standard config above.

Cline

Follow the instruction in the section [Configuring MCP Servers](https://docs.cline.bot/mcp/configuring-mcp-servers)

**Example: Local Setup**

Add the following to your [`cline_mcp_settings.json`](https://docs.cline.bot/mcp/configuring-mcp-servers#editing-mcp-settings-files) file:

```json
{
"mcpServers": {
"playwright": {
"type": "stdio",
"command": "npx",
"timeout": 30,
"args": [
"-y",
"@playwright/mcp@latest"
],
"disabled": false
}
}
}
```

Codex

Use the Codex CLI to add the Playwright MCP server:

```bash
codex mcp add playwright npx "@playwright/mcp@latest"
```

Alternatively, create or edit the configuration file `~/.codex/config.toml` and add:

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]
```

For more information, see the [Codex MCP documentation](https://github.com/openai/codex/blob/main/codex-rs/config.md#mcp_servers).

Copilot

Use the Copilot CLI to interactively add the Playwright MCP server:

```bash
/mcp add
```

Alternatively, create or edit the configuration file `~/.copilot/mcp-config.json` and add:

```json
{
"mcpServers": {
"playwright": {
"type": "local",
"command": "npx",
"tools": [
"*"
],
"args": [
"@playwright/mcp@latest"
]
}
}
}
```

For more information, see the [Copilot CLI documentation](https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli).

Cursor

#### Click the button to install:

[ ](https://cursor.com/en/install-mcp?name=Playwright&config=eyJjb21tYW5kIjoibnB4IEBwbGF5d3JpZ2h0L21jcEBsYXRlc3QifQ%3D%3D)

#### Or install manually:

Go to `Cursor Settings` -> `MCP` -> `Add new MCP Server`. Name to your liking, use `command` type with the command `npx @playwright/mcp@latest`. You can also verify config or add command like arguments via clicking `Edit`.

Factory

Use the Factory CLI to add the Playwright MCP server:

```bash
droid mcp add playwright "npx @playwright/mcp@latest"
```

Alternatively, type `/mcp` within Factory droid to open an interactive UI for managing MCP servers.

For more information, see the [Factory MCP documentation](https://docs.factory.ai/cli/configuration/mcp).

Gemini CLI

Follow the MCP install [guide](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md#configure-the-mcp-server-in-settingsjson), use the standard config above.

Goose

#### Click the button to install:

[![Install in Goose](https://block.github.io/goose/img/extension-install-dark.svg)](https://block.github.io/goose/extension?cmd=npx&arg=%40playwright%2Fmcp%40latest&id=playwright&name=Playwright&description=Interact%20with%20web%20pages%20through%20structured%20accessibility%20snapshots%20using%20Playwright)

#### Or install manually:

Go to `Advanced settings` -> `Extensions` -> `Add custom extension`. Name to your liking, use type `STDIO`, and set the `command` to `npx @playwright/mcp`. Click "Add Extension".

Grok

Use the Grok CLI to add the Playwright MCP server:

```bash
grok mcp add playwright -- npx @playwright/mcp@latest
```

Alternatively, create or edit the configuration file `~/.grok/config.toml` and add:

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]
```

For more information, see the [Grok MCP documentation](https://docs.x.ai/build/features/mcp-servers).

Junie

To add the Playwright MCP server in Junie CLI:

1. Type `/mcp`
2. Press `Ctrl+A` to add a new MCP server
3. Select **Playwright** from the list

Alternatively, add to `.junie/mcp/mcp.json`:

```json
{
"mcpServers": {
"Playwright": {
"command": "npx",
"args": [
"-y",
"@playwright/mcp@latest"
]
}
}
}
```

For more information, see the [Junie MCP configuration documentation](https://junie.jetbrains.com/docs/junie-cli-mcp-configuration.html).

Kiro

[![Add to Kiro](https://kiro.dev/images/add-to-kiro.svg)](https://kiro.dev/launch/mcp/add?name=playwright&config=%7B%22command%22%3A%22npx%22%2C%22args%22%3A%5B%22%40playwright%2Fmcp%40latest%22%5D%7D)

Follow the MCP Servers [documentation](https://kiro.dev/docs/mcp/). For example in `.kiro/settings/mcp.json`:

```json
{
"mcpServers": {
"playwright": {
"command": "npx",
"args": [
"@playwright/mcp@latest"
]
}
}
}
```

LM Studio

#### Click the button to install:

[![Add MCP Server playwright to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=playwright&config=eyJjb21tYW5kIjoibnB4IiwiYXJncyI6WyJAcGxheXdyaWdodC9tY3BAbGF0ZXN0Il19)

#### Or install manually:

Go to `Program` in the right sidebar -> `Install` -> `Edit mcp.json`. Use the standard config above.

opencode

Follow the MCP Servers [documentation](https://opencode.ai/docs/mcp-servers/). For example in `~/.config/opencode/opencode.json`:

```json
{
"$schema": "https://opencode.ai/config.json",
"mcp": {
"playwright": {
"type": "local",
"command": [
"npx",
"@playwright/mcp@latest"
],
"enabled": true
}
}
}

```

Qodo Gen

Open [Qodo Gen](https://docs.qodo.ai/qodo-documentation/qodo-gen) chat panel in VSCode or IntelliJ → Connect more tools → + Add new MCP → Paste the standard config above.

Click Save .

VS Code

#### Click the button to install:

[ ](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522playwright%2522%252C%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522%2540playwright%252Fmcp%2540latest%2522%255D%257D) [ ](https://insiders.vscode.dev/redirect?url=vscode-insiders%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522playwright%2522%252C%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522%2540playwright%252Fmcp%2540latest%2522%255D%257D)

#### Or install manually:

Follow the MCP install [guide](https://code.visualstudio.com/docs/copilot/chat/mcp-servers#_add-an-mcp-server), use the standard config above. You can also install the Playwright MCP server using the VS Code CLI:

```bash
# For VS Code
code --add-mcp '{"name":"playwright","command":"npx","args":["@playwright/mcp@latest"]}'
```

After installation, the Playwright MCP server will be available for use with your GitHub Copilot agent in VS Code.

Warp

Go to `Settings` -> `AI` -> `Manage MCP Servers` -> `+ Add` to [add an MCP Server](https://docs.warp.dev/knowledge-and-collaboration/mcp#adding-an-mcp-server). Use the standard config above.

Alternatively, use the slash command `/add-mcp` in the Warp prompt and paste the standard config from above:
```js
{
"mcpServers": {
"playwright": {
"command": "npx",
"args": [
"@playwright/mcp@latest"
]
}
}
}
```

Windsurf

Follow Windsurf MCP [documentation](https://docs.windsurf.com/windsurf/cascade/mcp). Use the standard config above.

### Configuration

Playwright MCP server supports following arguments. They can be provided in the JSON configuration above, as a part of the `"args"` list:

| Option | Description |
|--------|-------------|
| --allowed-hosts | comma-separated list of hosts this server is allowed to serve from. Defaults to the host the server is bound to. Pass '*' to disable the host check.
*env* `PLAYWRIGHT_MCP_ALLOWED_HOSTS` |
| --allowed-origins | semicolon-separated list of TRUSTED origins to allow the browser to request. Default is to allow all. Important: *does not* serve as a security boundary and *does not* affect redirects.
*env* `PLAYWRIGHT_MCP_ALLOWED_ORIGINS` |
| --allow-unrestricted-file-access | allow access to files outside of the workspace roots. Also allows unrestricted access to file:// URLs. By default access to file system is restricted to workspace root directories (or cwd if no roots are configured) only, and navigation to file:// URLs is blocked.
*env* `PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS` |
| --blocked-origins | semicolon-separated list of origins to block the browser from requesting. Blocklist is evaluated before allowlist. If used without the allowlist, requests not matching the blocklist are still allowed. Important: *does not* serve as a security boundary and *does not* affect redirects.
*env* `PLAYWRIGHT_MCP_BLOCKED_ORIGINS` |
| --block-service-workers | block service workers
*env* `PLAYWRIGHT_MCP_BLOCK_SERVICE_WORKERS` |
| --browser | browser or chrome channel to use, possible values: chrome, firefox, webkit, msedge.
*env* `PLAYWRIGHT_MCP_BROWSER` |
| --caps | comma-separated list of additional capabilities to enable, possible values: vision, pdf, devtools.
*env* `PLAYWRIGHT_MCP_CAPS` |
| --cdp-endpoint | CDP endpoint to connect to.
*env* `PLAYWRIGHT_MCP_CDP_ENDPOINT` |
| --cdp-header | CDP headers to send with the connect request, multiple can be specified.
*env* `PLAYWRIGHT_MCP_CDP_HEADERS` |
| --cdp-timeout | timeout in milliseconds for connecting to CDP endpoint, defaults to 30000ms
*env* `PLAYWRIGHT_MCP_CDP_TIMEOUT` |
| --codegen | specify the language to use for code generation, possible values: "typescript", "python", "java", "csharp", "none". Default is "typescript".
*env* `PLAYWRIGHT_MCP_CODEGEN` |
| --config | path to the configuration file.
*env* `PLAYWRIGHT_MCP_CONFIG` |
| --console-level | level of console messages to return: "error", "warning", "info", "debug". Each level includes the messages of more severe levels.
*env* `PLAYWRIGHT_MCP_CONSOLE_LEVEL` |
| --device | device to emulate, for example: "iPhone 15"
*env* `PLAYWRIGHT_MCP_DEVICE` |
| --mobile | emulate a generic mobile device (Pixel 10 for Chromium, iPhone 17 for WebKit). Mobile pages are usually lighter, which saves tokens. Cannot be combined with --device.
*env* `PLAYWRIGHT_MCP_MOBILE` |
| --executable-path | path to the browser executable.
*env* `PLAYWRIGHT_MCP_EXECUTABLE_PATH` |
| --extension | Connect to a running browser instance (Edge/Chrome only). Requires the "Playwright Extension" to be installed.
*env* `PLAYWRIGHT_MCP_EXTENSION` |
| --endpoint | Bound browser endpoint to connect to.
*env* `PLAYWRIGHT_MCP_ENDPOINT` |
| --grant-permissions | List of permissions to grant to the browser context, for example "geolocation", "clipboard-read", "clipboard-write".
*env* `PLAYWRIGHT_MCP_GRANT_PERMISSIONS` |
| --headless | run browser in headless mode, headed by default
*env* `PLAYWRIGHT_MCP_HEADLESS` |
| --host | host to bind server to. Default is localhost. Use 0.0.0.0 to bind to all interfaces.
*env* `PLAYWRIGHT_MCP_HOST` |
| --ignore-https-errors | ignore https errors
*env* `PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS` |
| --init-page | path to TypeScript file to evaluate on Playwright page object
*env* `PLAYWRIGHT_MCP_INIT_PAGE` |
| --init-script | path to JavaScript file to add as an initialization script. The script will be evaluated in every page before any of the page's scripts. Can be specified multiple times.
*env* `PLAYWRIGHT_MCP_INIT_SCR