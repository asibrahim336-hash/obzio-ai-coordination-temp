lms - Command Line Tool for LM Studio

Built with lmstudio.js

# Installation

`lms` ships with [LM Studio](https://lmstudio.ai/) 0.2.22 and newer.

If you have trouble running the command, try running `npx lmstudio install-cli` to add it to path.

To check if the bootstrapping was successful, run the following in a **👉 new terminal window 👈**:

```shell
lms
```

# Usage

You can use `lms --help` to see a list of all available subcommands.

For details about each subcommand, run `lms --help`.

Here are some frequently used commands:

- `lms status` - To check the status of LM Studio.
- `lms server start` - To start the local API server.
- `lms server stop` - To stop the local API server.
- `lms ls` - To list all downloaded models.
- `lms ls --json` - To list all downloaded models in machine-readable JSON format.
- `lms ps` - To list all loaded models available for inferencing.
- `lms ps --json` - To list all loaded models available for inferencing in machine-readable JSON format.
- `lms load` - To load a model
- `lms load -y` - To load a model with maximum GPU acceleration without confirmation
- `lms unload ` - To unload a model
- `lms unload --all` - To unload all models
- `lms create` - To create a new project with LM Studio SDK
- `lms log stream` - To stream logs from LM Studio

# Contributing

The CLI is part of the [lmstudio.js monorepo](https://github.com/lmstudio-ai/lmstudio.js) and cannot be built standalone.

## Building and Testing the CLI

```bash
# Clone and build the entire monorepo
git clone https://github.com/lmstudio-ai/lmstudio-js.git --recursive
cd lmstudio-js
npm install
npm run build

# Test your CLI changes
node publish/cli/dist/index.js
```

**Example:**

```bash
node publish/cli/dist/index.js --help
node publish/cli/dist/index.js status
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for more information.