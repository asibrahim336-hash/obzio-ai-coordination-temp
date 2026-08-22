# Chrome DevTools for agents

[![npm chrome-devtools-mcp package](https://img.shields.io/npm/v/chrome-devtools-mcp.svg)](https://npmjs.org/package/chrome-devtools-mcp)

Chrome DevTools for agents (`chrome-devtools-mcp`) lets your coding agent (such as Antigravity, Claude, Cursor or Copilot)
control and inspect a live Chrome browser. It acts as a Model-Context-Protocol
(MCP) server, giving your AI coding assistant access to the full power of
Chrome DevTools for reliable automation, in-depth debugging, and performance analysis.
A [CLI](docs/cli.md) is also provided for use without MCP.

## [Tool reference](./docs/tool-reference.md) | [Changelog](./CHANGELOG.md) | [Contributing](./CONTRIBUTING.md) | [Troubleshooting](./docs/troubleshooting.md) | [Design Principles](./docs/design-principles.md)

## Key features

- **Get performance insights**: Uses [Chrome
DevTools](https://github.com/ChromeDevTools/devtools-frontend) to record
traces and extract actionable performance insights.
- **Advanced browser debugging**: Analyze network requests, take screenshots and
check browser console messages (with source-mapped stack traces).
- **Reliable automation**. Uses
[puppeteer](https://github.com/puppeteer/puppeteer) to automate actions in
Chrome and automatically wait for action results.

## Disclaimers

`chrome-devtools-mcp` exposes content of the browser instance to the MCP clients
allowing them to inspect, debug, and modify any data in the browser or DevTools.
Avoid sharing sensitive or personal information that you don't want to share with
MCP clients.

`chrome-devtools-mcp` officially supports Google Chrome and [Chrome for Testing](https://developer.chrome.com/blog/chrome-for-testing/) only.
Other Chromium-based browsers may work, but this is not guaranteed, and you may encounter unexpected behavior. Use at your own discretion.
We are committed to providing fixes and support for the latest version of [Extended Stable Chrome](https://chromiumdash.appspot.com/schedule).

Performance tools may send trace URLs to the Google CrUX API to fetch real-user
experience data. This helps provide a holistic performance picture by
presenting field data alongside lab data. This data is collected by the [Chrome
User Experience Report (CrUX)](https://developer.chrome.com/docs/crux). To disable
this, run with the `--no-performance-crux` flag.

## **Usage statistics**

Google collects usage statistics (such as tool invocation success rates, latency, and environment information) to improve the reliability and performance of Chrome DevTools MCP.

Data collection is **enabled by default**. You can opt-out by passing the `--no-usage-statistics` flag when starting the server:

```json
"args": ["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]
```

Google handles this data in accordance with the [Google Privacy Policy](https://policies.google.com/privacy).

Google's collection of usage statistics for Chrome DevTools MCP is independent from the Chrome browser's usage statistics. Opting out of Chrome metrics does not automatically opt you out of this tool, and vice-versa.

Collection is disabled if `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` or `CI` env variables are set.

## Update checks

By default, the server periodically checks the npm registry for updates and logs a notification when a newer version is available.
You can disable these update checks by setting the `CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS` environment variable.

## Requirements

- [Node.js](https://nodejs.org/) [LTS](https://github.com/nodejs/Release#release-schedule) version.
- [Chrome](https://www.google.com/chrome/) current stable version or newer.
- [npm](https://www.npmjs.com/)

## Getting started

Add the following config to your MCP client:

```json
{
"mcpServers": {
"chrome-devtools": {
"command": "npx",
"args": ["-y", "chrome-devtools-mcp@latest"]
}
}
}
```

> [!NOTE]
> Using `chrome-devtools-mcp@latest` ensures that your MCP client will always use the latest version of the Chrome DevTools MCP server.

If you are interested in doing only basic browser tasks, use the `--slim` mode:

```json
{
"mcpServers": {
"chrome-devtools": {
"command": "npx",
"args": ["-y", "chrome-devtools-mcp@latest", "--slim", "--headless"]
}
}
}
```

See [Slim tool reference](./docs/slim-tool-reference.md).

### MCP Client configuration

Amp
Follow https://ampcode.com/manual#mcp and use the config provided above. You can also install the Chrome DevTools MCP server using the CLI:

```bash
amp mcp add chrome-devtools -- npx chrome-devtools-mcp@latest
```

Antigravity

To use the Chrome DevTools MCP server follow the instructions from Antigravity's docs to install a custom MCP server. Add the following config to the MCP servers config:

```bash
{
"mcpServers": {
"chrome-devtools": {
"command": "npx",
"args": [
"-y",
"chrome-devtools-mcp@latest",
"--browser-url=http://127.0.0.1:9222"
]
}
}
}
```

This will make the Chrome DevTools MCP server automatically connect to the browser that Antigravity is using. If you are not using port 9222, make sure to adjust accordingly.

Chrome DevTools MCP will not start the browser instance automatically using this approach because the Chrome DevTools MCP server connects to Antigravity's built-in browser. If the browser is not already running, you have to start it first by clicking the Chrome icon at the top right corner.

Bob

Follow the IBM Bob MCP guide and add the Chrome DevTools MCP server to your Bob MCP configuration. Use the global config (`~/.bob/mcp.json`) to apply it across all workspaces, or a project config (`.bob/mcp.json`) to scope it to one project:

```json
{
"mcpServers": {
"chrome-devtools": {
"command": "npx",
"args": ["-y", "chrome-devtools-mcp@latest"]
}
}
}
```

You can edit these files from **Bob panel → Settings → MCP → Edit Global MCP** (or **Edit Project MCP**). Bob hot-reloads on save. Once the server appears in the MCP tab, switch to the **🌎 Browser Dev** mode to get guided browser debugging directly in Bob.

Claude Code

**Install via CLI (MCP only)**

Use the Claude Code CLI to add the Chrome DevTools MCP server ( guide ):

```bash
claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest
```

**Install as a Plugin (MCP + Skills)**

> [!NOTE]
> If you already had Chrome DevTools MCP installed previously for Claude Code, make sure to remove it first from your installation and configuration files.

To install Chrome DevTools MCP with skills, add the marketplace registry in Claude Code:

```sh
/plugin marketplace add ChromeDevTools/chrome-devtools-mcp
```

Then, install the plugin:

```sh
/plugin install chrome-devtools-mcp@chrome-devtools-plugins
```

Restart Claude Code to have the MCP server and skills load (check with `/skills`).

> [!TIP]
> If the plugin installation fails with a `Failed to clone repository` error (e.g., HTTPS connectivity issues behind a corporate firewall), see the [troubleshooting guide](./docs/troubleshooting.md#claude-code-plugin-installation-fails-with-failed-to-clone-repository) for workarounds, or use the CLI installation method above instead.

Cline
Follow https://docs.cline.bot/mcp/configuring-mcp-servers and use the config provided above.

Codex
Follow the configure MCP guide
using the standard config from above. You can also install the Chrome DevTools MCP server using the Codex CLI:

```bash
codex mcp add chrome-devtools -- npx chrome-devtools-mcp@latest
```

**On Windows 11**

Configure the Chrome install location and increase the startup timeout by updating `.codex/config.toml` and adding the following `env` and `startup_timeout_ms` parameters:

```
[mcp_servers.chrome-devtools]
command = "cmd"
args = [
"/c",
"npx",
"-y",
"chrome-devtools-mcp@latest",
]
env = { SystemRoot="C:\\Windows", PROGRAMFILES="C:\\Program Files" }
startup_timeout_ms = 20_000
```

Command Code

Use the Command Code CLI to add the Chrome DevTools MCP server ( MCP guide ):

```bash
cmd mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest
```

Copilot CLI

Start Copilot CLI:

```
copilot
```

Start the dialog to add a new MCP server by running:

```
/mcp add
```

Configure the following fields and press `CTRL+S` to save the configuration:

- **Server name:** `chrome-devtools`
- **Server Type:** `[1] Local`
- **Command:** `npx -y chrome-devtools-mcp@latest`

Copilot / VS Code

**Install as a Plugin (Recommended)**

The easiest way to get up and running is to install `chrome-devtools-mcp` as an agent plugin.
This bundles the **MCP server** and all **skills** together, so your agent gets both the tools
and the expert guidance it needs to use them effectively.

1. Open the **Command Palette** (`Cmd+Shift+P` on macOS or `Ctrl+Shift+P` on Windows/Linux).
2. Search for and run the **Chat: Install Plugin From Source** command.
3. Paste in our repository name: `ChromeDevTools/chrome-devtools-mcp`.

That's it! Your agent is now supercharged with Chrome DevTools capabilities.

---

**Install as an MCP Server (MCP only)**

**Click the button to install:**

[ ](https://vscode.dev/redirect/mcp/install?name=io.github.ChromeDevTools%2Fchrome-devtools-mcp&config=%7B%22command%22%3A%22npx%22%2C%22args%22%3A%5B%22-y%22%2C%22chrome-devtools-mcp%22%5D%2C%22env%22%3A%7B%7D%7D)

[ ](https://insiders.vscode.dev/redirect?url=vscode-insiders%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522io.github.ChromeDevTools%252Fchrome-devtools-mcp%2522%252C%2522config%2522%253A%257B%2522command%2522%253A%2522npx%2522%252C%2522args%2522%253A%255B%2522-y%2522%252C%2522chrome-devtools-mcp%2522%255D%252C%2522env%2522%253A%257B%257D%257D%257D)

**Or install manually:**

Follow the VS Code [MCP configuration guide](https://code.visualstudio.com/docs/copilot/chat/mcp-servers#_add-an-mcp-server) using the standard config from above, or use the CLI:

For macOS and Linux:

```bash
code --add-mcp '{"name":"io.github.ChromeDevTools/chrome-devtools-mcp","command":"npx","args":["-y","chrome-devtools-mcp"],"env":{}}'
```

For Windows (PowerShell):

```powershell
code --add-mcp '{"""name""":"""io.github.ChromeDevTools/chrome-devtools-mcp""","""command""":"""npx""","""args""":["""-y""","""chrome-devtools-mcp"""]}'
```

Cursor

**Click the button to install:**

[ ](https://cursor.com/en/install-mcp?name=chrome-devtools&config=eyJjb21tYW5kIjoibnB4IC15IGNocm9tZS1kZXZ0b29scy1tY3BAbGF0ZXN0In0%3D)

**Or install manually:**

Go to `Cursor Settings` -> `MCP` -> `New MCP Server`. Use the config provided above.

Devin CLI

**Install via CLI (MCP only)**

Use the Devin CLI to add the Chrome DevTools MCP server ( guide ):

```bash
devin mcp add chrome-devtools -- npx chrome-devtools-mcp@latest
```

Factory CLI
Use the Factory CLI to add the Chrome DevTools MCP server ( guide ):

```bash
droid mcp add chrome-devtools "npx -y chrome-devtools-mcp@latest"
```

Gemini CLI
Install the Chrome DevTools MCP server using the Gemini CLI.

**Project wide:**

```bash
# Either MCP only:
gemini mcp add chrome-devtools npx chrome-devtools-mcp@latest
# Or as a Gemini extension (MCP+Skills):
gemini extensions install --auto-update https://github.com/ChromeDevTools/chrome-devtools-mcp
```

**Globally:**

```bash
gemini mcp add -s user chrome-devtools npx chrome-devtools-mcp@latest
```

Alternatively, follow the MCP guide and use the standard config from above.

Gemini Code Assist
Follow the configure MCP guide
using the standard config from above.

Grok Build CLI

```bash
grok mcp add chrome-devtools npx chrome-devtools-mcp@latest
```

See the docs for more options

JetBrains AI Assistant & Junie

Go to `Settings | Tools | AI Assistant | Model Context Protocol (MCP)` -> `Add`. Use the config provided above.
The same way chrome-devtools-mcp can be configured for JetBrains Junie in `Settings | Tools | Junie | MCP Settings` -> `Add`. Use the config provided above.

Kiro

In **Kiro Settings**, go to `Configure MCP` > `Open Workspace or User MCP Config` > Use the configuration snippet provided above.

Or, from the IDE **Activity Bar** > `Kiro` > `MCP Servers` > `Click Open MCP Config`. Use the configuration snippet provided above.

Katalon Studio

The Chrome DevTools MCP server can be used with Katalon StudioAssist via an MCP proxy.

**Step 1:** Install the MCP proxy by following the MCP proxy setup guide .

**Step 2:** Start the Chrome DevTools MCP server with the proxy:

```bash
mcp-proxy --transport streamablehttp --port 8080 -- npx -y chrome-devtools-mcp@latest
```

**Note:** You may need to pick another port if 8080 is already in use.

**Step 3:** In Katalon Studio, add the server to StudioAssist with the following settings:

- **Connection URL:** `http://127.0.0.1:8080/mcp`
- **Transport type:** `HTTP`

Once connected, the Chrome DevTools MCP tools will be available in StudioAssist.

Mistral Vibe

Add in ~/.vibe/config.toml:

```toml
[[mcp_servers]]
name = "chrome-devtools"
transport = "stdio"
command = "npx"
args = ["chrome-devtools-mcp@latest"]
```

OpenCode

Add the following configuration to your `opencode.json` file. If you don't have one, create it at `~/.config/opencode/opencode.json` ( guide ):

```json
{
"$schema": "https://opencode.ai/config.json",
"mcp": {
"chrome-devtools": {
"type": "local",
"command": ["npx", "-y", "chrome-devtools-mcp@latest"]
}
}
}
```

Qoder

In **Qoder Settings**, go to `MCP Server` > `+ Add` > Use the configuration snippet provided above.

Alternatively, follow the MCP guide and use the standard config from above.

Qoder CLI

Install the Chrome DevTools MCP server using the Qoder CLI ( guide ):

**Project wide:**

```bash
qodercli mcp add chrome-devtools -- npx chrome-devtools-mcp@latest
```

**Globally:**

```bash
qodercli mcp add -s user chrome-devtools -- npx chrome-devtools-mcp@latest
```

Visual Studio

**Click the button to install:**

[ ](https://vs-open.link/mcp-install?%7B%22name%22%3A%22chrome-devtools%22%2C%22command%22%3A%22npx%22%2C%22args%22%3A%5B%22chrome-devtools-mcp%40latest%22%5D%7D)

Warp

Go to `Settings | AI | Manage MCP Servers` -> `+ Add` t