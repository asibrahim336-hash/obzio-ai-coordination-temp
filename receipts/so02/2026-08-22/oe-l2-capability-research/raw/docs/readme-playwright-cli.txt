# playwright-cli

Playwright CLI with SKILLS

### Playwright CLI vs Playwright MCP

This package provides CLI interface into Playwright. If you are using **coding agents**, that is the best fit.

- **CLI**: Modern **coding agents** increasingly favor CLI–based workflows exposed as SKILLs over MCP because CLI invocations are more token-efficient: they avoid loading large tool schemas and verbose accessibility trees into the model context, allowing agents to act through concise, purpose-built commands. This makes CLI + SKILLs better suited for high-throughput coding agents that must balance browser automation with large codebases, tests, and reasoning within limited context windows.

- **MCP**: MCP remains relevant for specialized agentic loops that benefit from persistent state, rich introspection, and iterative reasoning over page structure, such as exploratory automation, self-healing tests, or long-running autonomous workflows where maintaining continuous browser context outweighs token cost concerns. Learn more about [Playwright MCP](https://github.com/microsoft/playwright-mcp).

### Key Features

- **Token-efficient**. Does not force page data into LLM.

### Requirements
- Node.js 18 or newer
- Claude Code, GitHub Copilot, or any other coding agent.

## Getting Started

## Installation

```bash
npm install -g @playwright/cli@latest
playwright-cli --help
```

### Installing skills

Claude Code, GitHub Copilot and others will use the locally installed skills.

```bash
playwright-cli install --skills
```

### Skills-less operation

Point your agent at the CLI and let it cook. It'll read the skill off `playwright-cli --help` on its own:

```
Test the "add todo" flow on https://demo.playwright.dev/todomvc using playwright-cli.
Check playwright-cli --help for available commands.
```

## Demo

```
> Use playwright skills to test https://demo.playwright.dev/todomvc/.
Take screenshots for all successful and failing scenarios.
```

Your agent will be running commands, but it does not mean you can't play with it manually:

```
playwright-cli open https://demo.playwright.dev/todomvc/ --headed
playwright-cli type "Buy groceries"
playwright-cli press Enter
playwright-cli type "Water flowers"
playwright-cli press Enter
playwright-cli check e21
playwright-cli check e35
playwright-cli screenshot
```

## Headed operation

Playwright CLI is headless by default. If you'd like to see the browser, pass `--headed` to `open`:

```bash
playwright-cli open https://playwright.dev --headed
```

## Sessions

Playwright CLI keeps the browser profile in memory by default. Your cookies and storage state
are preserved between CLI calls within the session, but lost when the browser closes. Use
`--persistent` to save the profile to disk for persistence across browser restarts.

You can use different instances of the browser for different projects with sessions. Pass `-s=` to
the invocation to talk to a specific browser.

```bash
playwright-cli open https://playwright.dev
playwright-cli -s=example open https://example.com --persistent
playwright-cli list
```

You can run your coding agent with the `PLAYWRIGHT_CLI_SESSION` environment variable:

```bash
PLAYWRIGHT_CLI_SESSION=todo-app claude .
```

Or instruct it to prepend `-s=` to the calls.

Manage your sessions as follows:

```bash
playwright-cli list # list all sessions
playwright-cli close-all # close all browsers
playwright-cli kill-all # forcefully kill all browser processes
```

## Monitoring

Use `playwright-cli show` to open a visual dashboard that lets you see and control all running
browser sessions. This is useful when your coding agents are running browser automation in the
background and you want to observe their progress or step in to help.

```bash
playwright-cli show
```

The dashboard opens a window with two views:

- **Session grid** — shows all active sessions grouped by workspace, each with a live screencast
preview, session name, current URL, and page title. Click any session to zoom in.
- **Session detail** — shows a live view of the selected session with a tab bar, navigation
controls (back, forward, reload, address bar), and full remote control. Click into the viewport
to take over mouse and keyboard input; press Escape to release.

From the grid you can also close running sessions or delete data for inactive ones.

## Commands

### Core

```bash
playwright-cli open [url] # open browser, optionally navigate to url
playwright-cli goto # navigate to a url
playwright-cli close # close the page
playwright-cli type # type text into editable element
playwright-cli click [button] # perform click on a web page
playwright-cli dblclick [button] # perform double click on a web page
playwright-cli fill # fill text into editable element
playwright-cli fill --submit # fill and press Enter
playwright-cli drag # perform drag and drop between two elements
playwright-cli drop --path= # drop files onto an element (from outside the page)
playwright-cli drop --data="k=v" # drop data onto an element
playwright-cli hover # hover over element on page
playwright-cli select # select an option in a dropdown
playwright-cli upload # upload one or multiple files
playwright-cli check # check a checkbox or radio button
playwright-cli uncheck # uncheck a checkbox or radio button
playwright-cli snapshot # capture page snapshot to obtain element ref
playwright-cli snapshot --filename=f # save snapshot to specific file
playwright-cli snapshot # snapshot a specific element
playwright-cli snapshot --depth=N # limit snapshot depth for efficiency
playwright-cli find # search the snapshot for text, returns matching nodes
playwright-cli find --regex # search the snapshot with a regexp
playwright-cli eval [ref] # evaluate javascript expression on page or element
playwright-cli dialog-accept [prompt] # accept a dialog
playwright-cli dialog-dismiss # dismiss a dialog
playwright-cli resize # resize the browser window
```

### Navigation

```bash
playwright-cli go-back # go back to the previous page
playwright-cli go-forward # go forward to the next page
playwright-cli reload # reload the current page
```

### Keyboard

```bash
playwright-cli press # press a key on the keyboard, `a`, `arrowleft`
playwright-cli keydown # press a key down on the keyboard
playwright-cli keyup # press a key up on the keyboard
```

### Mouse

```bash
playwright-cli mousemove # move mouse to a given position
playwright-cli mousedown [button] # press mouse down
playwright-cli mouseup [button] # press mouse up
playwright-cli mousewheel # scroll mouse wheel
```

### Save as

```bash
playwright-cli screenshot [ref] # screenshot of the current page or element
playwright-cli screenshot --filename=f # save screenshot with specific filename
playwright-cli screenshot --hires # capture at full device pixel ratio
playwright-cli pdf # save page as pdf
playwright-cli pdf --filename=page.pdf # save pdf with specific filename
```

### Tabs

```bash
playwright-cli tab-list # list all tabs
playwright-cli tab-new [url] # create a new tab
playwright-cli tab-close [index] # close a browser tab
playwright-cli tab-select # select a browser tab
```

### Storage

```bash
playwright-cli state-save [filename] # save storage state
playwright-cli state-load # load storage state

# Cookies
playwright-cli cookie-list [--domain] # list cookies
playwright-cli cookie-get # get a cookie
playwright-cli cookie-set # set a cookie
playwright-cli cookie-delete # delete a cookie
playwright-cli cookie-clear # clear all cookies

# LocalStorage
playwright-cli localstorage-list # list localStorage entries
playwright-cli localstorage-get # get localStorage value
playwright-cli localstorage-set # set localStorage value
playwright-cli localstorage-delete # delete localStorage entry
playwright-cli localstorage-clear # clear all localStorage

# SessionStorage
playwright-cli sessionstorage-list # list sessionStorage entries
playwright-cli sessionstorage-get # get sessionStorage value
playwright-cli sessionstorage-set # set sessionStorage value
playwright-cli sessionstorage-delete # delete sessionStorage entry
playwright-cli sessionstorage-clear # clear all sessionStorage
```

### Network

```bash
playwright-cli route [opts] # mock network requests
playwright-cli route-list # list active routes
playwright-cli unroute [pattern] # remove route(s)
```

### DevTools

```bash
playwright-cli console [min-level] # list console messages
playwright-cli requests # list all network requests since loading the page
playwright-cli request # show details for a specific request
playwright-cli run-code # run playwright code snippet
playwright-cli run-code --filename=f # run playwright code from a file
playwright-cli tracing-start # start trace recording
playwright-cli tracing-stop # stop trace recording
playwright-cli video-start [filename] # start video recording
playwright-cli video-chapter # add a chapter marker to the video
playwright-cli video-show-actions # annotate each action with a callout in the video
playwright-cli video-hide-actions # stop annotating actions in the video
playwright-cli video-stop # stop video recording
playwright-cli show # open the visual dashboard
playwright-cli show --annotate # launch dashboard for UI review / design feedback
playwright-cli generate-locator # generate a playwright locator for an element
playwright-cli highlight # show a persistent highlight overlay
playwright-cli highlight --style= # highlight with a custom CSS style
playwright-cli highlight --hide # hide highlight on a specific element
playwright-cli highlight --hide # hide all page highlights
```

### Open parameters

```bash
playwright-cli open --browser=chrome # use specific browser
playwright-cli open --mobile # emulate a generic mobile device
playwright-cli open --device="iPhone 15" # emulate a specific device
playwright-cli attach --extension=chrome # connect via Playwright Extension
playwright-cli attach --cdp=chrome # attach to running Chrome/Edge by channel
playwright-cli attach --cdp= # attach via CDP endpoint
playwright-cli detach # detach an attached session, leaves the external browser running
playwright-cli open --persistent # use persistent profile
playwright-cli open --profile= # use custom profile directory
playwright-cli open --config=file.json # use config file
playwright-cli close # close the browser
playwright-cli delete-data # delete user data for default session
```

### Snapshots

After each command, playwright-cli provides a snapshot of the current browser state.

```bash
> playwright-cli goto https://example.com
### Page
- Page URL: https://example.com/
- Page Title: Example Domain
### Snapshot
[Snapshot](.playwright-cli/page-2026-02-14T19-22-42-679Z.yml)
```

You can also take a snapshot on demand using `playwright-cli snapshot` command. All the options below can be combined as needed.

```bash
# default - save to a file with timestamp-based name
playwright-cli snapshot

# save to file, use when snapshot is a part of the workflow result
playwright-cli snapshot --filename=after-click.yaml

# snapshot an element instead of the whole page
playwright-cli snapshot "#main"

# limit snapshot depth for efficiency, take a partial snapshot afterwards
playwright-cli snapshot --depth=4
playwright-cli snapshot e34

# include each element's bounding box as [box=x,y,width,height]
playwright-cli snapshot --boxes

# search a large snapshot instead of capturing it all — returns matching nodes
# with 3 lines of context around each match (like grep -C)
playwright-cli find "Add to cart"
playwright-cli find --regex "\\$[0-9]+\\.[0-9]{2}"
# wrap the regexp in slashes to add flags, e.g. /i for case-insensitive
playwright-cli find --regex "/sign (in|up)/i"
```

### Targeting elements

By default, use refs from the snapshot to interact with page elements.

```bash
# get snapshot with refs
playwright-cli snapshot

# interact using a ref
playwright-cli click e15
```

You can also use css selectors or Playwright locators.

```bash
# css selector
playwright-cli click "#main > button.submit"

# role locator
playwright-cli click "getByRole('button', { name: 'Submit' })"

# test id
playwright-cli click "getByTestId('submit-button')"
```

### Sessions

```bash
playwright-cli -s=name # run command in named session
playwright-cli -s=name close # stop a named browser
playwright-cli -s=name delete-data # delete user data for named browser
playwright-cli list # list all sessions
playwright-cli close-all # close all browsers
playwright-cli kill-all # forcefully kill all browser processes
```

### Local installation

If global `playwright-cli` command is not available, try a local version via `npx playwright cli`:

```bash
npx --no-install playwright --version
```

When local version is available, use `npx playwright cli` in all commands. Otherwise, install `playwright-cli` as a global command:

```bash
npm install -g @playwright/cli@latest
```

## Configuration file

The Playwright CLI can be configured using a JSON configuration file. You can specify the configuration file using the `--config` command line option:

```bash
playwright-cli --config path/to/config.json open example.com
```

Playwright CLI will load config from `.playwright/cli.config.json` by default so that you did not need to specify it every time.

Configuration file schema

```typescript
{
/**
* The browser to use.
*/
browser?: {
/**
* The type of browser to use.
*/
browserName?: 'chromium' | 'firefox' | 'webkit';

/**
* Keep the browser profile in memory, do not save it to disk.
*/
isolated?: boolean;

/**
* Path to a user data directory for browser profile persistence.
* Temporary directory is created by default.
*/
userDataDir?: string;

/**
* Launch options passed to
* @see https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context
*
* This is useful for settings options like `channel`, `headless`, `executablePath`, etc.
*/
launchOptions?: playwright.LaunchOptions;

/**
* Context options for the browser context.
*
* This is useful f