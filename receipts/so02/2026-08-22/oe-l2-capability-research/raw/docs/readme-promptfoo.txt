# Promptfoo: LLM evals & red teaming

promptfoo is a CLI and library for evaluating and red-teaming LLM apps. Stop the trial-and-error approach - start shipping secure, reliable AI apps.

Website ·
Getting Started ·
Red Teaming ·
Documentation ·
Discord

> Promptfoo is now part of OpenAI. Promptfoo remains open source and MIT licensed. Read the [company update](https://www.promptfoo.dev/blog/promptfoo-joining-openai/).

## Quick Start

Requires [Node.js](https://nodejs.org/en/download) `>=22.22.0` for npm and npx usage. Node.js 24 LTS
is recommended; see the [runtime support guide](https://www.promptfoo.dev/docs/installation/#nodejs-runtime-support).

```sh
npm install -g promptfoo
promptfoo init --example getting-started
```

Also available via `brew install promptfoo` and `pip install promptfoo`. You can also use `npx promptfoo@latest` to run any command without installing.

Most LLM providers require an API key. Set yours as an environment variable:

```sh
export OPENAI_API_KEY=sk-abc123
```

Once you're in the example directory, run an eval and view results:

```sh
cd getting-started
promptfoo eval
promptfoo view
```

See [Getting Started](https://www.promptfoo.dev/docs/getting-started/) (evals) or [Red Teaming](https://www.promptfoo.dev/docs/red-team/) (vulnerability scanning) for more.

## What can you do with Promptfoo?

- **Test your prompts and models** with [automated evaluations](https://www.promptfoo.dev/docs/getting-started/)
- **Secure your LLM apps** with [red teaming](https://www.promptfoo.dev/docs/red-team/) and vulnerability scanning
- **Compare models** side-by-side (OpenAI, Anthropic, Azure, Bedrock, Ollama, and [more](https://www.promptfoo.dev/docs/providers/))
- **Automate checks** in [CI/CD](https://www.promptfoo.dev/docs/integrations/ci-cd/)
- **Review pull requests** for LLM-related security and compliance issues with [code scanning](https://www.promptfoo.dev/docs/code-scanning/)
- **Share results** with your team

Here's what it looks like in action:

It works on the command line too:

It also can generate [security vulnerability reports](https://www.promptfoo.dev/docs/red-team/):

## Why Promptfoo?

- **Developer-first**: Fast, with features like live reload and caching
- **Private**: LLM evals run 100% locally - your prompts never leave your machine
- **Flexible**: Works with any LLM API or programming language
- **Battle-tested**: Powers LLM apps serving 10M+ users in production
- **Data-driven**: Make decisions based on metrics, not gut feel
- **Open source**: MIT licensed, with an active community

## Learn More

- [Getting Started](https://www.promptfoo.dev/docs/getting-started/)
- [Full Documentation](https://www.promptfoo.dev/docs/intro/)
- [Red Teaming Guide](https://www.promptfoo.dev/docs/red-team/)
- [CLI Usage](https://www.promptfoo.dev/docs/usage/command-line/)
- [Node.js Package](https://www.promptfoo.dev/docs/usage/node-package/)
- [Supported Models](https://www.promptfoo.dev/docs/providers/)
- [Code Scanning Guide](https://www.promptfoo.dev/docs/code-scanning/)

## Contributing

We welcome contributions! Check out our [contributing guide](https://www.promptfoo.dev/docs/contributing/) to get started.

Join our [Discord community](https://discord.gg/promptfoo) for help and discussion.