# Language Model Evaluation Harness

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.10256836.svg)](https://doi.org/10.5281/zenodo.10256836)

---

## Latest News 📣
- [2025/12] **CLI refactored** with subcommands (`run`, `ls`, `validate`) and YAML config file support via `--config`. See the [CLI Reference](./docs/interface.md) and [Configuration Guide](./docs/config_files.md).
- [2025/12] **Lighter install**: Base package no longer includes `transformers`/`torch`. Install model backends separately: `pip install lm_eval[hf]`, `lm_eval[vllm]`, etc.
- [2025/07] Added `think_end_token` arg to `hf` (token/str), `vllm` and `sglang` (str) for stripping CoT reasoning traces from models that support it.
- [2025/03] Added support for steering HF models!
- [2025/02] Added [SGLang](https://docs.sglang.ai/) support!
- [2024/09] We are prototyping allowing users of LM Evaluation Harness to create and evaluate on text+image multimodal input, text output tasks, and have just added the `hf-multimodal` and `vllm-vlm` model types and `mmmu` task as a prototype feature. We welcome users to try out this in-progress feature and stress-test it for themselves, and suggest they check out [`lmms-eval`](https://github.com/EvolvingLMMs-Lab/lmms-eval), a wonderful project originally forking off of the lm-evaluation-harness, for a broader range of multimodal tasks, models, and features.
- [2024/07] [API model](docs/API_guide.md) support has been updated and refactored, introducing support for batched and async requests, and making it significantly easier to customize and use for your own purposes. **To run Llama 405B, we recommend using VLLM's OpenAI-compliant API to host the model, and use the `local-completions` model type to evaluate the model.**
- [2024/07] New Open LLM Leaderboard tasks have been added ! You can find them under the [leaderboard](lm_eval/tasks/leaderboard/README.md) task group.

---

## Announcement

**A new v0.4.0 release of lm-evaluation-harness is available** !

New updates and features include:

- **New Open LLM Leaderboard tasks have been added ! You can find them under the [leaderboard](lm_eval/tasks/leaderboard/README.md) task group.**
- Internal refactoring
- Config-based task creation and configuration
- Easier import and sharing of externally-defined task config YAMLs
- Support for Jinja2 prompt design, easy modification of prompts + prompt imports from Promptsource
- More advanced configuration options, including output post-processing, answer extraction, and multiple LM generations per document, configurable fewshot settings, and more
- Speedups and new modeling libraries supported, including: faster data-parallel HF model usage, vLLM support, MPS support with HuggingFace, and more
- Logging and usability changes
- New tasks including CoT BIG-Bench-Hard, Belebele, user-defined task groupings, and more

Please see our updated documentation pages in `docs/` for more details.

Development will be continuing on the `main` branch, and we encourage you to give us feedback on what features are desired and how to improve the library further, or ask questions, either in issues or PRs on GitHub, or in the [EleutherAI discord](https://discord.gg/eleutherai)!

---

## Overview

This project provides a unified framework to test generative language models on a large number of different evaluation tasks.

**Features:**

- Over 60 standard academic benchmarks for LLMs, with hundreds of subtasks and variants implemented.
- Support for models loaded via [transformers](https://github.com/huggingface/transformers/) (including quantization via [GPTQModel](https://github.com/ModelCloud/GPTQModel) and [AutoGPTQ](https://github.com/PanQiWei/AutoGPTQ)), [GPT-NeoX](https://github.com/EleutherAI/gpt-neox), and [Megatron-DeepSpeed](https://github.com/microsoft/Megatron-DeepSpeed/), with a flexible tokenization-agnostic interface.
- Support for fast and memory-efficient inference with [vLLM](https://github.com/vllm-project/vllm).
- Support for commercial APIs including [OpenAI](https://openai.com), and [TextSynth](https://textsynth.com/).
- Support for evaluation on adapters (e.g. LoRA) supported in [HuggingFace's PEFT library](https://github.com/huggingface/peft).
- Support for local models and benchmarks.
- Evaluation with publicly available prompts ensures reproducibility and comparability between papers.
- Easy support for custom prompts and evaluation metrics.

The Language Model Evaluation Harness is the backend for 🤗 Hugging Face's popular [Open LLM Leaderboard](https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard), has been used in [hundreds of papers](https://scholar.google.com/scholar?oi=bibs&hl=en&authuser=2&cites=15052937328817631261,4097184744846514103,1520777361382155671,17476825572045927382,18443729326628441434,14801318227356878622,7890865700763267262,12854182577605049984,15641002901115500560,5104500764547628290), and is used internally by dozens of organizations including NVIDIA, Cohere, BigScience, BigCode, Nous Research, and Mosaic ML.

## Install

To install the `lm-eval` package from the github repository, run:

```bash
git clone --depth 1 https://github.com/EleutherAI/lm-evaluation-harness
cd lm-evaluation-harness
pip install -e .
```

### Installing Model Backends

The base installation provides the core evaluation framework. **Model backends must be installed separately** using optional extras:

For HuggingFace transformers models:

```bash
pip install "lm_eval[hf]"
```

For vLLM inference:

```bash
pip install "lm_eval[vllm]"
```

For API-based models (OpenAI, Anthropic, etc.):

```bash
pip install "lm_eval[api]"
```

Multiple backends can be installed together:

```bash
pip install "lm_eval[hf,vllm,api]"
```

A detailed table of all optional extras is available at the end of this document.

## Basic Usage

### Documentation

| Guide | Description |
|-------|-------------|
| [CLI Reference](./docs/interface.md) | Command-line arguments and subcommands |
| [Configuration Guide](./docs/config_files.md) | YAML config file format and examples |
| [Python API](./docs/python-api.md) | Programmatic usage with `simple_evaluate()` |
| [Task Guide](./lm_eval/tasks/README.md) | Available tasks and task configuration |

Use `lm-eval -h` to see available options, or `lm-eval run -h` for evaluation options.

List available tasks with:

```bash
lm-eval ls tasks
```

### Hugging Face `transformers`

> [!Important]
> To use the HuggingFace backend, first install: `pip install "lm_eval[hf]"`

To evaluate a model hosted on the [HuggingFace Hub](https://huggingface.co/models) (e.g. GPT-J-6B) on `hellaswag` you can use the following command (this assumes you are using a CUDA-compatible GPU):

```bash
lm_eval --model hf \
--model_args pretrained=EleutherAI/gpt-j-6B \
--tasks hellaswag \
--device cuda:0 \
--batch_size 8
```

Additional arguments can be provided to the model constructor using the `--model_args` flag. Most notably, this supports the common practice of using the `revisions` feature on the Hub to store partially trained checkpoints, or to specify the datatype for running a model:

```bash
lm_eval --model hf \
--model_args pretrained=EleutherAI/pythia-160m,revision=step100000,dtype="float" \
--tasks lambada_openai,hellaswag \
--device cuda:0 \
--batch_size 8
```

Models that are loaded via both `transformers.AutoModelForCausalLM` (autoregressive, decoder-only GPT style models) and `transformers.AutoModelForSeq2SeqLM` (such as encoder-decoder models like T5) in Huggingface are supported.

Batch size selection can be automated by setting the ```--batch_size``` flag to ```auto```. This will perform automatic detection of the largest batch size that will fit on your device. On tasks where there is a large difference between the longest and shortest example, it can be helpful to periodically recompute the largest batch size, to gain a further speedup. To do this, append ```:N``` to above flag to automatically recompute the largest batch size ```N``` times. For example, to recompute the batch size 4 times, the command would be:

```bash
lm_eval --model hf \
--model_args pretrained=EleutherAI/pythia-160m,revision=step100000,dtype="float" \
--tasks lambada_openai,hellaswag \
--device cuda:0 \
--batch_size auto:4
```

> [!Note]
> Just like you can provide a local path to `transformers.AutoModel`, you can also provide a local path to `lm_eval` via `--model_args pretrained=/path/to/model`

#### Evaluating GGUF Models

`lm-eval` supports evaluating models in GGUF format using the Hugging Face (`hf`) backend. This allows you to use quantized models compatible with `transformers`, `AutoModel`, and llama.cpp conversions.

To evaluate a GGUF model, pass the path to the directory containing the model weights, the `gguf_file`, and optionally a separate `tokenizer` path using the `--model_args` flag.

**🚨 Important Note:**
If no separate tokenizer is provided, Hugging Face will attempt to reconstruct the tokenizer from the GGUF file — this can take **hours** or even hang indefinitely. Passing a separate tokenizer avoids this issue and can reduce tokenizer loading time from hours to seconds.

**✅ Recommended usage:**

```bash
lm_eval --model hf \
--model_args pretrained=/path/to/gguf_folder,gguf_file=model-name.gguf,tokenizer=/path/to/tokenizer \
--tasks hellaswag \
--device cuda:0 \
--batch_size 8
```

> [!Tip]
> Ensure the tokenizer path points to a valid Hugging Face tokenizer directory (e.g., containing tokenizer_config.json, vocab.json, etc.).

#### Multi-GPU Evaluation with Hugging Face `accelerate`

We support three main ways of using Hugging Face's [accelerate 🚀](https://github.com/huggingface/accelerate) library for multi-GPU evaluation.

To perform *data-parallel evaluation* (where each GPU loads a **separate full copy** of the model), we leverage the `accelerate` launcher as follows:

```bash
accelerate launch -m lm_eval --model hf \
--tasks lambada_openai,arc_easy \
--batch_size 16
```

(or via `accelerate launch --no-python lm_eval`).

For cases where your model can fit on a single GPU, this allows you to evaluate on K GPUs K times faster than on one.

**WARNING**: This setup does not work with FSDP model sharding, so in `accelerate config` FSDP must be disabled, or the NO_SHARD FSDP option must be used.

The second way of using `accelerate` for multi-GPU evaluation is when your model is *too large to fit on a single GPU.*

In this setting, run the library *outside the `accelerate` launcher*, but passing `parallelize=True` to `--model_args` as follows:

```bash
lm_eval --model hf \
--tasks lambada_openai,arc_easy \
--model_args parallelize=True \
--batch_size 16
```

This means that your model's weights will be split across all available GPUs.

For more advanced users or even larger models, we allow for the following arguments when `parallelize=True` as well:

- `device_map_option`: How to split model weights across available GPUs. defaults to "auto".
- `max_memory_per_gpu`: the max GPU memory to use per GPU in loading the model.
- `max_cpu_memory`: the max amount of CPU memory to use when offloading the model weights to RAM.
- `offload_folder`: a folder where model weights will be offloaded to disk if needed.

The third option is to use both at the same time. This will allow you to take advantage of both data parallelism and model sharding, and is especially useful for models that are too large to fit on a single GPU.

```bash
accelerate launch --multi_gpu --num_processes {nb_of_copies_of_your_model} \
-m lm_eval --model hf \
--tasks lambada_openai,arc_easy \
--model_args parallelize=True \
--batch_size 16
```

To learn more about model parallelism and how to use it with the `accelerate` library, see the [accelerate documentation](https://huggingface.co/docs/transformers/v4.15.0/en/parallelism)

**Warning: We do not natively support multi-node evaluation using the `hf` model type! Please reference [our GPT-NeoX library integration](https://github.com/EleutherAI/gpt-neox/blob/main/eval.py) for an example of code in which a custom multi-machine evaluation script is written.**

**Note: we do not currently support multi-node evaluations natively, and advise using either an externally hosted server to run inference requests against, or creating a custom integration with your distributed framework [as is done for the GPT-NeoX library](https://github.com/EleutherAI/gpt-neox/blob/main/eval_tasks/eval_adapter.py).**

#### Tensor Parallelism (native PyTorch)

For models that support PyTorch's native Tensor Parallelism (via DTensor), you can shard model weights across GPUs without `accelerate`'s device-map by passing `tp_plan=auto` in `--model_args`. Launch with `torchrun` or `accelerate launch`:

```bash
torchrun --nproc-per-node=4 -m lm_eval \
--model hf \
--model_args pretrained=google/gemma-4-31B-it,tp_plan=auto \
--tasks lambada_openai,arc_easy \
--batch_size 16
```

**Constraints:**

- `tp_plan` and `parallelize=True` are mutually exclusive — use one or the other.
- The number of key-value heads in the model must be divisible by `--nproc-per-node` (the TP degree).
- Requires PyTorch >= 2.4 and a `transformers` version that exposes a TP plan for the model (v4.47+).

### Steered Hugging Face `transformers` models

To evaluate a Hugging Face `transformers` model with steering vectors applied, specify the model type as `steered` and provide the path to either a PyTorch file containing pre-defined steering vectors, or a CSV file that specifies how to derive steering vectors from pretrained `sparsify` or `sae_lens` models (you will need to install the corresponding optional dependency for this method).

Specify pre-defined steering vectors:

```python
import torch

steer_config = {
"layers.3": {
"steering_vector": torch.randn(1, 768),
"bias": torch.randn(1, 768),
"steering_coefficient": 1,
"action": "add"
},
}
torch.save(steer_config, "steer_config.pt")
```

Specify derived steering vectors:

```python
import pandas as pd

pd.DataFrame({
"loader