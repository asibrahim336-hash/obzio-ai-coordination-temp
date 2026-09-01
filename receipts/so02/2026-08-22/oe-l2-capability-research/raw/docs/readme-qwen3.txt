# Qwen3

💜 Qwen Chat    |   🤗 Hugging Face    |   🤖 ModelScope    |    📑 Paper    |    📑 Blog    ｜   📖 Documentation

🖥️ Demo    |   💬 WeChat (微信)    |   🫨 Discord

Visit our Hugging Face or ModelScope organization (click links above), search checkpoints with names starting with `Qwen3-` or visit the [Qwen3 collection](https://huggingface.co/collections/Qwen/qwen3-67dd247413f0e2e4f653967f), and you will find all you need! Enjoy!

To learn more about Qwen3, feel free to read our documentation \[[EN](https://qwen.readthedocs.io/en/latest/)|[ZH](https://qwen.readthedocs.io/zh-cn/latest/)\]. Our documentation consists of the following sections:

- Quickstart: the basic usages and demonstrations;
- Inference: the guidance for the inference with Transformers, including batch inference, streaming, etc.;
- Run Locally: the instructions for running LLM locally on CPU and GPU, with frameworks like llama.cpp, Ollama, and LM Studio;
- Deployment: the demonstration of how to deploy Qwen for large-scale inference with frameworks like SGLang, vLLM, TGI, etc.;
- Quantization: the practice of quantizing LLMs with GPTQ, AWQ, as well as the guidance for how to make high-quality quantized GGUF files;
- Training: the instructions for post-training, including SFT and RLHF (TODO) with frameworks like Axolotl, LLaMA-Factory, etc.
- Framework: the usage of Qwen with frameworks for application, e.g., RAG, Agent, etc.

## Introduction

### Qwen3-2507

Over the past three months, we continued to explore the potential of the Qwen3 families and we are excited to introduce the updated **Qwen3-2507** in two variants, Qwen3-Instruct-2507 and Qwen3-Thinking-2507, and three sizes, 235B-A22B, 30B-A3B, and 4B.

**Qwen3-Instruct-2507** is the updated version of the previous Qwen3 non-thinking mode, featuring the following key enhancements:

- **Significant improvements** in general capabilities, including **instruction following, logical reasoning, text comprehension, mathematics, science, coding and tool usage**.
- **Substantial gains** in long-tail knowledge coverage across **multiple languages**.
- **Markedly better alignment** with user preferences in **subjective and open-ended tasks**, enabling more helpful responses and higher-quality text generation.
- **Enhanced capabilities** in **256K-token long-context understanding**, extendable up to **1 million tokens**.

**Qwen3-Thinking-2507** is the continuation of Qwen3 thinking model, with improved quality and depth of reasoning, featuring the following key enhancements:
- **Significantly improved performance** on reasoning tasks, including logical reasoning, mathematics, science, coding, and academic benchmarks that typically require human expertise — achieving **state-of-the-art results among open-weight thinking models**.
- **Markedly better general capabilities**, such as instruction following, tool usage, text generation, and alignment with human preferences.
- **Enhanced 256K long-context understanding** capabilities, extendable up to **1 million tokens**.

Previous Qwen3 Release
Qwen3 (aka Qwen3-2504)

We are excited to announce the release of Qwen3, the latest addition to the Qwen family of large language models.
These models represent our most advanced and intelligent systems to date, improving from our experience in building QwQ and Qwen2.5.
We are making the weights of Qwen3 available to the public, including both dense and Mixture-of-Expert (MoE) models.

The highlights from Qwen3 include:

Dense and Mixture-of-Experts (MoE) models of various sizes , available in 0.6B, 1.7B, 4B, 8B, 14B, 32B and 30B-A3B, 235B-A22B.

Seamless switching between thinking mode (for complex logical reasoning, math, and coding) and non-thinking mode (for efficient, general-purpose chat), ensuring optimal performance across various scenarios.

Significantly enhancement in reasoning capabilities , surpassing previous QwQ (in thinking mode) and Qwen2.5 instruct models (in non-thinking mode) on mathematics, code generation, and commonsense logical reasoning.

Superior human preference alignment , excelling in creative writing, role-playing, multi-turn dialogues, and instruction following, to deliver a more natural, engaging, and immersive conversational experience.

Expertise in agent capabilities , enabling precise integration with external tools in both thinking and unthinking modes and achieving leading performance among open-source models in complex agent-based tasks.

Support of 100+ languages and dialects with strong capabilities for multilingual instruction following and translation .

## News
- 2025.08.08: You can now use Qwen3-2507 to handle ultra-long inputs of **1 million tokens**! See the update modelcards ([235B-A22B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507), [235B-A22B-Thinking-2507](https://huggingface.co/Qwen/Qwen3-235B-A22B-Thinking-2507), [A30B-A3B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507), [A30B-A3B-Thinking-2507](https://huggingface.co/Qwen/Qwen3-30B-A3B-Thinking-2507)) for how to enable this feature.
- 2025.08.06: The final open release of Qwen3-2507, [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) and [Qwen3-4B-Thinking-2507](https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507), is out!
- 2025.07.31: Qwen3-30B-A3B-Thinking-2507 is released. Check out the [modelcard](https://huggingface.co/Qwen/Qwen3-30B-A3B-Thinking-2507) for more details!
- 2025.07.30: Qwen3-30B-A3B-Instruct-2507 is released. Check out the [modelcard](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507) for more details!
- 2025.07.25: We released the updated version of Qwen3-235B-A22B thinking mode, named Qwen3-235B-A22B-Thinking-2507. Check out the [modelcard](https://huggingface.co/Qwen/Qwen3-235B-A22B-Thinking-2507) for more details!
- 2025.07.21: We released the updated version of Qwen3-235B-A22B non-thinking mode, named Qwen3-235B-A22B-Instruct-2507, featuring significant enhancements over the previous version and supporting 256K-token long-context understanding. Check our [modelcard](https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507) for more details!
- 2025.04.29: We released the Qwen3 series. Check our [blog](https://qwenlm.github.io/blog/qwen3) for more details!
- 2024.09.19: We released the Qwen2.5 series. This time there are 3 extra model sizes: 3B, 14B, and 32B for more possibilities. Check our [blog](https://qwenlm.github.io/blog/qwen2.5) for more!
- 2024.06.06: We released the Qwen2 series. Check our [blog](https://qwenlm.github.io/blog/qwen2/)!
- 2024.03.28: We released the first MoE model of Qwen: Qwen1.5-MoE-A2.7B! Temporarily, only HF transformers and vLLM support the model. We will soon add the support of llama.cpp, mlx-lm, etc. Check our [blog](https://qwenlm.github.io/blog/qwen-moe/) for more information!
- 2024.02.05: We released the Qwen1.5 series.

## Performance

Detailed evaluation results are reported in this [📑 blog (Qwen3-2504)](https://qwenlm.github.io/blog/qwen3/) and this [📑 blog (Qwen3-2507) \[coming soon\]]().

For requirements on GPU memory and the respective throughput, see results [here](https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html).

## Run Qwen3

### 🤗 Transformers

Transformers is a library of pretrained natural language processing for inference and training.
The latest version of `transformers` is recommended and `transformers>=4.51.0` is required.

#### Qwen3-Instruct-2507

The following contains a code snippet illustrating how to use Qwen3-30B-A3B-Instruct-2507 to generate content based on given inputs.
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "Qwen/Qwen3-30B-A3B-Instruct-2507"

# load the tokenizer and the model
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
model_name,
torch_dtype="auto",
device_map="auto"
)

# prepare the model input
prompt = "Give me a short introduction to large language model."
messages = [
{"role": "user", "content": prompt}
]
text = tokenizer.apply_chat_template(
messages,
tokenize=False,
add_generation_prompt=True,
)
model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

# conduct text completion
generated_ids = model.generate(
**model_inputs,
max_new_tokens=16384
)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()

content = tokenizer.decode(output_ids, skip_special_tokens=True)

print("content:", content)
```

> [!Note]
> Qwen3-Instruct-2507 supports only non-thinking mode and does not generate `` `` blocks in its output. Meanwhile, specifying `enable_thinking=False` is no longer required.

#### Qwen3-Thinking-2507

The following contains a code snippet illustrating how to use Qwen3-30B-A3B-Thinking-2507 to generate content based on given inputs.
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "Qwen/Qwen3-30B-A3B-Thinking-2507"

# load the tokenizer and the model
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
model_name,
torch_dtype="auto",
device_map="auto"
)

# prepare the model input
prompt = "Give me a short introduction to large language model."
messages = [
{"role": "user", "content": prompt}
]
text = tokenizer.apply_chat_template(
messages,
tokenize=False,
add_generation_prompt=True,
)
model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

# conduct text completion
generated_ids = model.generate(
**model_inputs,
max_new_tokens=32768
)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()

# parsing thinking content
try:
# rindex finding 151668 ( )
index = len(output_ids) - output_ids[::-1].index(151668)
except ValueError:
index = 0

thinking_content = tokenizer.decode(output_ids[:index], skip_special_tokens=True).strip("\n")
content = tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip("\n")

print("thinking content:", thinking_content) # no opening tag
print("content:", content)

```

> [!Note]
> Qwen3-Thinking-2507 supports only thinking mode.
> Additionally, to enforce model thinking, the default chat template automatically includes ` `. Therefore, it is normal for the model's output to contain only ` ` without an explicit opening ` ` tag.
>
> Qwen3-Thinking-2507 also features an increased thinking length. We strongly recommend its use in highly complex reasoning tasks with adequate maximum generation length.

Switching Thinking/Non-thinking Modes for Previous Qwen3 Models

By default, Qwen3 models will think before response.
This could be controlled by

enable_thinking=False : Passing enable_thinking=False to `tokenizer.apply_chat_template` will strictly prevent the model from generating thinking content.

/think and /no_think instructions: Use those words in the system or user message to signify whether Qwen3 should think. In multi-turn conversations, the latest instruction is followed.

### ModelScope

We strongly advise users especially those in mainland China to use ModelScope.
ModelScope adopts a Python API similar to Transformers.
The CLI tool `modelscope download` can help you solve issues concerning downloading checkpoints.
For vLLM and SGLang, the environment variable `VLLM_USE_MODELSCOPE=true` and `SGLANG_USE_MODELSCOPE=true` can be used respectively.

### llama.cpp

[`llama.cpp`](https://github.com/ggml-org/llama.cpp) enables LLM inference with minimal setup and state-of-the-art performance on a wide range of hardware.
`llama.cpp>=b5401` is recommended for the full support of Qwen3.

To use the CLI, run the following in a terminal:
```shell
./llama-cli -hf Qwen/Qwen3-8B-GGUF:Q8_0 --jinja --color -ngl 99 -fa -sm row --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0 -c 40960 -n 32768 --no-context-shift
# CTRL+C to exit
```

To use the API server, run the following in a terminal:
```shell
./llama-server -hf Qwen/Qwen3-8B-GGUF:Q8_0 --jinja --reasoning-format deepseek -ngl 99 -fa -sm row --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0 -c 40960 -n 32768 --no-context-shift --port 8080
```
A simple web front end will be at `http://localhost:8080` and an OpenAI-compatible API will be at `http://localhost:8080/v1`.

For additional guides, please refer to [our documentation](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html).

> [!Note]
> llama.cpp adopts "rotating context management" and infinite generation is made possible by evicting earlier tokens.
> It could configured by parameters and the commands above effectively disable it.
> For more details, please refer to [our documentation](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html#llama-cli).

### Ollama

After [installing Ollama](https://ollama.com/), you can initiate the Ollama service with the following command (Ollama v0.9.0 or higher is recommended):
```shell
ollama serve
# You need to keep this service running whenever you are using ollama
```

To pull a model checkpoint and run the model, use the `ollama run` command. You can specify a model size by adding a suffix to `qwen3`, such as `:8b` or `:30b-a3b`:
```shell
ollama run qwen3:8b
# Setting parameters, type "/set parameter num_ctx 40960" and "/set parameter num_predict 32768"
# To exit, type "/bye" and press ENTER
# For Qwen3-2504 models,
# - To enable thinking, which is the default, type "/set think"
# - To disable thinking, type "/set nothink"
```

You can also access the Ollama service via its OpenAI-compatible API.
Please note that you need to (1) keep `ollama serve` running while using the API, and (2) execute `ollama run qwen3:8b` before utilizing this API to ensure that the model checkpoint is prepared.
The API is at `http://localhost:11434/v1/` by default.

For additional details, please visit [ollama.ai](https://ollama.com/).

> [!Note]
> Ollama's naming may not be consistent with the Qwen's original naming.
> For example, `qwen3:30b-a3b` in Ollama points to `qwen3:30b-a3b-thinking-2507-q4_K_M` as of August 202