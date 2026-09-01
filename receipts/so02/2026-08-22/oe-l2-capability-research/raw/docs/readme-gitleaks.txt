# Gitleaks

```
┌─○───┐
│ │╲ │
│ │ ○ │
│ ○ ░ │
└─░───┘
```

> [!WARNING]
> Gitleaks is feature complete. I'm not merging new features into Gitleaks. Future releases will be security patches only. I'm shifting my focus to [Betterleaks](https://github.com/betterleaks/betterleaks)

[license]: ./LICENSE
[badge-license]: https://img.shields.io/github/license/gitleaks/gitleaks.svg
[go-docs-badge]: https://pkg.go.dev/badge/github.com/gitleaks/gitleaks/v8?status
[go-docs]: https://pkg.go.dev/github.com/zricethezav/gitleaks/v8
[badge-build]: https://github.com/gitleaks/gitleaks/actions/workflows/test.yml/badge.svg
[build]: https://github.com/gitleaks/gitleaks/actions/workflows/test.yml
[go-report-card-badge]: https://goreportcard.com/badge/github.com/gitleaks/gitleaks/v8
[go-report-card]: https://goreportcard.com/report/github.com/gitleaks/gitleaks/v8
[dockerhub]: https://hub.docker.com/r/zricethezav/gitleaks
[dockerhub-badge]: https://img.shields.io/docker/pulls/zricethezav/gitleaks.svg
[gitleaks-action]: https://github.com/gitleaks/gitleaks-action
[gitleaks-badge]: https://img.shields.io/badge/protected%20by-gitleaks-blue

[![GitHub Action Test][badge-build]][build]
[![Docker Hub][dockerhub-badge]][dockerhub]
[![Gitleaks Action][gitleaks-badge]][gitleaks-action]
[![GoDoc][go-docs-badge]][go-docs]
[![GoReportCard][go-report-card-badge]][go-report-card]
[![License][badge-license]][license]

Gitleaks is a tool for **detecting** secrets like passwords, API keys, and tokens in git repos, files, and whatever else you wanna throw at it via `stdin`. If you wanna learn more about how the detection engine works check out this blog: [Regex is (almost) all you need](https://lookingatcomputer.substack.com/p/regex-is-almost-all-you-need).

```
➜ ~/code(master) gitleaks git -v

○
│╲
│ ○
○ ░
░ gitleaks

Finding: "export BUNDLE_ENTERPRISE__CONTRIBSYS__COM=cafebabe:deadbeef",
Secret: cafebabe:deadbeef
RuleID: sidekiq-secret
Entropy: 2.609850
File: cmd/generate/config/rules/sidekiq.go
Line: 23
Commit: cd5226711335c68be1e720b318b7bc3135a30eb2
Author: John
Email: john@users.noreply.github.com
Date: 2022-08-03T12:31:40Z
Fingerprint: cd5226711335c68be1e720b318b7bc3135a30eb2:cmd/generate/config/rules/sidekiq.go:sidekiq-secret:23
```

## Getting Started

Gitleaks can be installed using Homebrew, Docker, or Go. Gitleaks is also available in binary form for many popular platforms and OS types on the [releases page](https://github.com/gitleaks/gitleaks/releases). In addition, Gitleaks can be implemented as a pre-commit hook directly in your repo or as a GitHub action using [Gitleaks-Action](https://github.com/gitleaks/gitleaks-action).

### Installing

```bash
# MacOS
brew install gitleaks

# Docker (DockerHub)
docker pull zricethezav/gitleaks:latest
docker run -v ${path_to_host_folder_to_scan}:/path zricethezav/gitleaks:latest [COMMAND] [OPTIONS] [SOURCE_PATH]

# Docker (ghcr.io)
docker pull ghcr.io/gitleaks/gitleaks:latest
docker run -v ${path_to_host_folder_to_scan}:/path ghcr.io/gitleaks/gitleaks:latest [COMMAND] [OPTIONS] [SOURCE_PATH]

# From Source (make sure `go` is installed)
git clone https://github.com/gitleaks/gitleaks.git
cd gitleaks
make build
```

### Pre-Commit

1. Install pre-commit from https://pre-commit.com/#install
2. Create a `.pre-commit-config.yaml` file at the root of your repository with the following content:

```
repos:
- repo: https://github.com/gitleaks/gitleaks
rev: v8.24.2
hooks:
- id: gitleaks
```

for a [native execution of gitleaks](https://github.com/gitleaks/gitleaks/releases) or use the [`gitleaks-docker` pre-commit ID](https://github.com/gitleaks/gitleaks/blob/master/.pre-commit-hooks.yaml) for executing gitleaks using the [official Docker images](#docker)

3. Auto-update the config to the latest repos' versions by executing `pre-commit autoupdate`
4. Install with `pre-commit install`
5. Now you're all set!

```
➜ git commit -m "this commit contains a secret"
Detect hardcoded secrets.................................................Failed
```

Note: to disable the gitleaks pre-commit hook you can prepend `SKIP=gitleaks` to the commit command
and it will skip running gitleaks

```
➜ SKIP=gitleaks git commit -m "skip gitleaks check"
Detect hardcoded secrets................................................Skipped
```

## Usage

```
Gitleaks scans code, past or present, for secrets

Usage:
gitleaks [command]

Available Commands:
completion Generate the autocompletion script for the specified shell
dir scan directories or files for secrets
git scan git repositories for secrets
help Help about any command
stdin detect secrets from stdin
version display gitleaks version

Flags:
-b, --baseline-path string path to baseline with issues that can be ignored
-c, --config string config file path
order of precedence:
1. --config/-c
2. env var GITLEAKS_CONFIG
3. env var GITLEAKS_CONFIG_TOML with the file content
4. (target path)/.gitleaks.toml
If none of the four options are used, then gitleaks will use the default config
--diagnostics string enable diagnostics (http OR comma-separated list: cpu,mem,trace). cpu=CPU prof, mem=memory prof, trace=exec tracing, http=serve via net/http/pprof
--diagnostics-dir string directory to store diagnostics output files when not using http mode (defaults to current directory)
--enable-rule strings only enable specific rules by id
--exit-code int exit code when leaks have been encountered (default 1)
-i, --gitleaks-ignore-path string path to .gitleaksignore file or folder containing one (default ".")
-h, --help help for gitleaks
--ignore-gitleaks-allow ignore gitleaks:allow comments
-l, --log-level string log level (trace, debug, info, warn, error, fatal) (default "info")
--max-archive-depth int allow scanning into nested archives up to this depth (default "0", no archive traversal is done)
--max-decode-depth int allow recursive decoding up to this depth (default "0", no decoding is done)
--max-target-megabytes int files larger than this will be skipped
--no-banner suppress banner
--no-color turn off color for verbose output
--redact uint[=100] redact secrets from logs and stdout. To redact only parts of the secret just apply a percent value from 0..100. For example --redact=20 (default 100%)
-f, --report-format string output format (json, csv, junit, sarif, template)
-r, --report-path string report file
--report-template string template file used to generate the report (implies --report-format=template)
--timeout int set a timeout for gitleaks commands in seconds (default "0", no timeout is set)
-v, --verbose show verbose output from scan
--version version for gitleaks

Use "gitleaks [command] --help" for more information about a command.
```

### Commands

⚠️ v8.19.0 introduced a change that deprecated `detect` and `protect`. Those commands are still available but
are hidden in the `--help` menu. Take a look at this [gist](https://gist.github.com/zricethezav/b325bb93ebf41b9c0b0507acf12810d2) for easy command translations.
If you find v8.19.0 broke an existing command (`detect`/`protect`), please open an issue.

There are three scanning modes: `git`, `dir`, and `stdin`.

#### Git

The `git` command lets you scan local git repos. Under the hood, gitleaks uses the `git log -p` command to scan patches.
You can configure the behavior of `git log -p` with the `log-opts` option.
For example, if you wanted to run gitleaks on a range of commits you could use the following
command: `gitleaks git -v --log-opts="--all commitA..commitB" path_to_repo`. See the [git log](https://git-scm.com/docs/git-log) documentation for more information.
If there is no target specified as a positional argument, then gitleaks will attempt to scan the current working directory as a git repo.

#### Dir

The `dir` (aliases include `files`, `directory`) command lets you scan directories and files. Example: `gitleaks dir -v path_to_directory_or_file`.
If there is no target specified as a positional argument, then gitleaks will scan the current working directory.

#### Stdin

You can also stream data to gitleaks with the `stdin` command. Example: `cat some_file | gitleaks -v stdin`

### Creating a baseline

When scanning large repositories or repositories with a long history, it can be convenient to use a baseline. When using a baseline,
gitleaks will ignore any old findings that are present in the baseline. A baseline can be any gitleaks report. To create a gitleaks report, run gitleaks with the `--report-path` parameter.

```
gitleaks git --report-path gitleaks-report.json # This will save the report in a file called gitleaks-report.json
```

Once as baseline is created it can be applied when running the detect command again:

```
gitleaks git --baseline-path gitleaks-report.json --report-path findings.json
```

After running the detect command with the --baseline-path parameter, report output (findings.json) will only contain new issues.

## Pre-Commit hook

You can run Gitleaks as a pre-commit hook by copying the example `pre-commit.py` script into
your `.git/hooks/` directory.

## Load Configuration

The order of precedence is:

1. `--config/-c` option:
```bash
gitleaks git --config /home/dev/customgitleaks.toml .
```
2. Environment variable `GITLEAKS_CONFIG` with the file path:
```bash
export GITLEAKS_CONFIG="/home/dev/customgitleaks.toml"
gitleaks git .
```
3. Environment variable `GITLEAKS_CONFIG_TOML` with the file content:
```bash
export GITLEAKS_CONFIG_TOML=`cat customgitleaks.toml`
gitleaks git .
```
4. A `.gitleaks.toml` file within the target path:
```bash
gitleaks git .
```

If none of the four options are used, then gitleaks will use the default config.

## Configuration

Gitleaks offers a configuration format you can follow to write your own secret detection rules:

```toml
# Title for the gitleaks configuration file.
title = "Custom Gitleaks configuration"

# You have basically two options for your custom configuration:
#
# 1. define your own configuration, default rules do not apply
#
# use e.g., the default configuration as starting point:
# https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml
#
# 2. extend a configuration, the rules are overwritten or extended
#
# When you extend a configuration the extended rules take precedence over the
# default rules. I.e., if there are duplicate rules in both the extended
# configuration and the default configuration the extended rules or
# attributes of them will override the default rules.
# Another thing to know with extending configurations is you can chain
# together multiple configuration files to a depth of 2. Allowlist arrays are
# appended and can contain duplicates.

# useDefault and path can NOT be used at the same time. Choose one.
[extend]
# useDefault will extend the default gitleaks config built in to the binary
# the latest version is located at:
# https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml
useDefault = true
# or you can provide a path to a configuration to extend from.
# The path is relative to where gitleaks was invoked,
# not the location of the base config.
# path = "common_config.toml"
# If there are any rules you don't want to inherit, they can be specified here.
disabledRules = [ "generic-api-key"]

# An array of tables that contain information that define instructions
# on how to detect secrets
[[rules]]
# Unique identifier for this rule
id = "awesome-rule-1"

# Short human-readable description of the rule.
description = "awesome rule 1"

# Golang regular expression used to detect secrets. Note Golang's regex engine
# does not support lookaheads.
regex = '''one-go-style-regex-for-this-rule'''

# Int used to extract secret from regex match and used as the group that will have
# its entropy checked if `entropy` is set.
secretGroup = 3

# Float representing the minimum shannon entropy a regex group must have to be considered a secret.
entropy = 3.5

# Golang regular expression used to match paths. This can be used as a standalone rule or it can be used
# in conjunction with a valid `regex` entry.
path = '''a-file-path-regex'''

# Keywords are used for pre-regex check filtering. Rules that contain
# keywords will perform a quick string compare check to make sure the
# keyword(s) are in the content being scanned. Ideally these values should
# either be part of the identiifer or unique strings specific to the rule's regex
# (introduced in v8.6.0)
keywords = [
"auth",
"password",
"token",
]

# Array of strings used for metadata and reporting purposes.
tags = ["tag","another tag"]

# ⚠️ In v8.21.0 `[rules.allowlist]` was replaced with `[[rules.allowlists]]`.
# This change was backwards-compatible: instances of `[rules.allowlist]` still work.
#
# You can define multiple allowlists for a rule to reduce false positives.
# A finding will be ignored if _ANY_ `[[rules.allowlists]]` matches.
[[rules.allowlists]]
description = "ignore commit A"
# When multiple criteria are defined the default condition is "OR".
# e.g., this can match on |commits| OR |paths| OR |stopwords|.
condition = "OR"
commits = [ "commit-A", "commit-B"]
paths = [
'''go\.mod''',
'''go\.sum'''
]
# note: stopwords targets the extracted secret, not the entire regex match
# like 'regexes' does. (stopwords introduced in 8.8.0)
stopwords = [
'''client''',
'''endpoint''',
]

[[rules.allowlists]]
# The "AND" condition can be used to make sure all criteria match.
# e.g., this matches if |regexes| AND |paths| are satisfied.
condition = "AND"
# note: |regexes| defaults to check the _Secret_ in the finding.
# Acceptable values for |regexTarget| are "secret" (default), "match", and "line".
regexTarget = "match"
regexes = [ '''(?i)parseur[il]''' ]
paths = [ '''package-lock\.json''' ]

# You can extend a particular rule from the default config. e.g., gitlab-pat
# if you have defined a custom token prefix on your GitLab instance
[[rules]]
id = "gitlab-pat"
# all the other attributes from the default rule are inherited

[[rules.allowlists]]
regexTarget = "line"
regexes = [ '''MY-gl