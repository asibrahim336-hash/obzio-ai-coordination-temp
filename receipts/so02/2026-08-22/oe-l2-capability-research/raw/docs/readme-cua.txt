Scale computer-use 2.0 with open-source drivers, cross-OS fleets, and benchmarks for training, evaluation, and data generation.

## Choose Your Path

Building your own agent? Start with Cua ·
Giving a coding agent a computer? Cua Drivers ·
Evaluating or training models? Cua Bench ·
Need macOS VMs? Lume

---

## Cua Drivers - Background computer-use on macOS, Windows, and Linux

Drive native desktop apps **in the background**. Agents click, type, and verify without stealing the cursor or focus. Use the same CLI and MCP server on macOS, Windows, and Linux from Claude Code, Cursor, Codex, OpenClaw, and custom clients. Linux supports X11 and compositor-specific Wayland routes with explicit limits for raw background input.

**macOS / Linux**

```sh
/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"
```

**Windows (PowerShell)**

```powershell
irm https://cua.ai/driver/install.ps1 | iex
```

Then follow the post-install instructions.

**[Drive your first app](https://cua.ai/docs/tutorials/drive-your-first-app)** | **[Installation](https://cua.ai/docs/how-to-guides/driver/install)** | **[CLI Reference](https://cua.ai/docs/reference/cua-driver/cli-reference)**

Source documentation, architecture notes, and the optional agent skill pack live in [`libs/cua-driver/README.md`](libs/cua-driver/README.md).

---

## Cua - Agent-Ready Sandboxes for Any OS

Build agents that see screens, click buttons, and complete tasks autonomously. One API for any VM or container image — cloud or local.

```sh
pip install cua
```

```python
# Requires Python 3.11 or later
from cua import Sandbox, Image

# Same API regardless of OS or runtime
async with Sandbox.ephemeral(Image.linux()) as sb: # or .macos() .windows() .android()
result = await sb.shell.run("echo hello")
screenshot = await sb.screenshot()
await sb.mouse.click(100, 200)
await sb.keyboard.type("Hello from Cua!")
await sb.mobile.gesture((100, 500), (100, 200)) # multi-touch gestures
```

| | Linux container | Linux VM | macOS | Windows | Android | BYOI (.qcow2, .iso) |
| ------------------ | --------------- | -------- | ----- | ------- | ------- | ------------------- |
| **Cloud (cua.ai)** | ✅ | ✅ | ✅ | ✅ | ✅ | 🔜 soon |
| **Local (QEMU)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**[Get Started](https://cua.ai/docs/cua/guide/get-started/set-up-sandbox)** | **[Examples](https://cua.ai/docs/cua/examples)** | **[API Reference](https://cua.ai/docs/cua/reference/agent-sdk)**

---

## Cua-Bench - Benchmarks & RL Environments

Evaluate computer-use agents on OSWorld, ScreenSpot, Windows Arena, and custom tasks. Export trajectories for training.

```bash
# Clone, install, and create base image
git clone https://github.com/trycua/cua && cd cua/cua-bench
uv tool install -e . && cb image create linux-docker

# Run benchmark with agent
cb run dataset datasets/cua-bench-basic --agent cua-agent --max-parallel 4
```

**[Get Started](https://cua.ai/docs/cuabench/guide/getting-started/first-steps)** | **[Partner With Us](https://cuabench.ai/)** | **[Registry](https://cuabench.ai/registry)** | **[CLI Reference](https://cua.ai/docs/cuabench/reference/cli-reference)**

---

## Lume - macOS Virtualization

Create and manage macOS/Linux VMs with near-native performance on Apple Silicon using Apple's Virtualization.Framework.

```bash
# Install Lume
/bin/bash -c "$(curl -fsSL https://cua.ai/lume/install.sh)"

# Create and start a vanilla macOS VM from an Apple restore image
curl -L "$(lume ipsw | tail -n 1)" -o ~/Downloads/macos-tahoe.ipsw
lume create macos-tahoe --ipsw ~/Downloads/macos-tahoe.ipsw --unattended tahoe
lume run macos-tahoe
```

The `--unattended` option prepares the installed guest offline. The built-in
`sequoia` and `tahoe` presets create the `lume` user, enable SSH, configure
autologin, and disable sleep and screen locking. The default credentials are
`lume` / `lume`.

The Tahoe flow is E2E verified. Sequoia may still open the Accessibility step
of Setup Assistant on its first display boot; see [issue #2155](https://github.com/trycua/cua/issues/2155).

**[Get Started](https://cua.ai/docs/lume)** | **[FAQ](https://cua.ai/docs/lume/guide/getting-started/faq)** | **[CLI Reference](https://cua.ai/docs/lume/reference/cli-reference)**

---

## Packages

| Package | Description |
| -------------------------------------------------------------------- | ----------------------------------------------------------- |
| [cua-driver](libs/cua-driver/README.md) | Background computer-use agent for macOS, Windows, and Linux |
| [cua-agent](https://cua.ai/docs/cua/reference/agent-sdk) | AI agent framework for computer-use tasks |
| [cua-sandbox](https://cua.ai/docs/cua/reference/sandbox-sdk) | SDK for creating and controlling sandboxes |
| [cua-computer-server](https://cua.ai/docs/cua/reference/sandbox-sdk) | Driver for UI interactions and code execution in sandboxes |
| [cua-bench](https://cua.ai/docs/cuabench) | Benchmarks and RL environments for computer-use |
| [lume](https://cua.ai/docs/lume) | macOS/Linux VM management on Apple Silicon |
| [lumier](https://cua.ai/docs/lume/guide/advanced/lumier) | Docker-compatible interface for Lume VMs |

## Resources

- [Documentation](https://cua.ai/docs) — Guides, examples, and API reference
- [Blog](https://cua.ai/blog) — Tutorials, updates, and research
- [Discord](https://discord.com/invite/mVnXXpdE85) — Community support and discussions
- [GitHub Issues](https://github.com/trycua/cua/issues) — Bug reports and feature requests
- [Security](SECURITY.md) — Private vulnerability reporting

## Citation

If Cua supports your research, please cite the software:

```bibtex
@software{cua2025,
author = {{Cua AI, Inc.}},
title = {Cua},
year = {2025},
url = {https://github.com/trycua/cua},
license = {MIT}
}
```

For reproducibility, include the Cua release or commit used in your experiments. Citation metadata is also available in [`CITATION.cff`](CITATION.cff).

## Contributing

We welcome contributions! See our [Contributing Guidelines](CONTRIBUTING.md) for details.

## License

MIT License — see [LICENSE](LICENSE.md) for details.

Third-party components have their own licenses:

- [Kasm](libs/kasm/LICENSE) (MIT)
- [OmniParser](https://github.com/microsoft/OmniParser/blob/master/LICENSE) (CC-BY-4.0)
- Optional `cua-agent[omni]` includes ultralytics (AGPL-3.0)

## Trademarks

Apple, macOS, Ubuntu, Canonical, and Microsoft are trademarks of their respective owners. This project is not affiliated with or endorsed by these companies.

---

Thank you to all our [GitHub Sponsors](https://github.com/sponsors/trycua)!