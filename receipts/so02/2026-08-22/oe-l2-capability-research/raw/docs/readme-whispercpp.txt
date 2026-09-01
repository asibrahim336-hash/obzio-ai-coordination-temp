# whisper.cpp

![whisper.cpp](https://user-images.githubusercontent.com/1991296/235238348-05d0f6a4-da44-4900-a1de-d0707e75b763.jpeg)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/github/v/release/ggml-org/whisper.cpp?filter=v*)](https://github.com/ggml-org/whisper.cpp/releases)
[![Actions Status](https://github.com/ggml-org/whisper.cpp/workflows/CI/badge.svg)](https://github.com/ggml-org/whisper.cpp/actions)
[![Conan Center](https://shields.io/conan/v/whisper-cpp)](https://conan.io/center/whisper-cpp)
[![npm](https://img.shields.io/npm/v/whisper.cpp.svg)](https://www.npmjs.com/package/whisper.cpp/)

High-performance inference of [OpenAI's Whisper](https://github.com/openai/whisper) automatic speech recognition (ASR) model:

- Plain C/C++ implementation without dependencies
- Apple Silicon first-class citizen - optimized via ARM NEON, Accelerate framework, Metal and [Core ML](#core-ml-support)
- AVX intrinsics support for x86 architectures
- [VSX intrinsics support for POWER architectures](#power-vsx-intrinsics)
- Mixed F16 / F32 precision
- [Integer quantization support](#quantization)
- Zero memory allocations at runtime
- [Vulkan support](#vulkan-gpu-support)
- Support for CPU-only inference
- [Efficient GPU support for NVIDIA](#nvidia-gpu-support)
- [AMD ROCm GPU support](#amd-rocm-gpu-support)
- [OpenVINO Support](#openvino-support)
- [Ascend NPU Support](#ascend-npu-support)
- [Moore Threads GPU Support](#moore-threads-gpu-support)
- [C-style API](https://github.com/ggml-org/whisper.cpp/blob/master/include/whisper.h)
- [Voice Activity Detection (VAD)](#voice-activity-detection-vad)

Supported platforms:

- [x] Mac OS (Intel and Arm)
- [x] [iOS](examples/whisper.objc)
- [x] [Android](examples/whisper.android)
- [x] [Java](bindings/java/README.md)
- [x] Linux / [FreeBSD](https://github.com/ggml-org/whisper.cpp/issues/56#issuecomment-1350920264)
- [x] [WebAssembly](examples/whisper.wasm)
- [x] Windows ([MSVC](https://github.com/ggml-org/whisper.cpp/blob/master/.github/workflows/build.yml#L117-L144) and [MinGW](https://github.com/ggml-org/whisper.cpp/issues/168))
- [x] [Raspberry Pi](https://github.com/ggml-org/whisper.cpp/discussions/166)
- [x] [Docker](https://github.com/ggml-org/whisper.cpp/pkgs/container/whisper.cpp)

The entire high-level implementation of the model is contained in [whisper.h](include/whisper.h) and [whisper.cpp](src/whisper.cpp).
The rest of the code is part of the [`ggml`](https://github.com/ggml-org/ggml) machine learning library.

Having such a lightweight implementation of the model allows to easily integrate it in different platforms and applications.
As an example, here is a video of running the model on an iPhone 13 device - fully offline, on-device: [whisper.objc](examples/whisper.objc)

https://user-images.githubusercontent.com/1991296/197385372-962a6dea-bca1-4d50-bf96-1d8c27b98c81.mp4

You can also easily make your own offline voice assistant application: [command](examples/command)

https://user-images.githubusercontent.com/1991296/204038393-2f846eae-c255-4099-a76d-5735c25c49da.mp4

On Apple Silicon, the inference runs fully on the GPU via Metal:

https://github.com/ggml-org/whisper.cpp/assets/1991296/c82e8f86-60dc-49f2-b048-d2fdbd6b5225

## Quick start

First clone the repository:

```bash
git clone https://github.com/ggml-org/whisper.cpp.git
```

Navigate into the directory:

```
cd whisper.cpp
```

Then, download one of the Whisper [models](models/README.md) converted in [`ggml` format](#ggml-format). For example:

```bash
sh ./models/download-ggml-model.sh base.en
```

Now build the [whisper-cli](examples/cli) example and transcribe an audio file like this:

```bash
# build the project
cmake -B build
cmake --build build -j --config Release

# transcribe an audio file
./build/bin/whisper-cli -f samples/jfk.wav
```

---

For a quick demo, simply run `make base.en`.

The command downloads the `base.en` model converted to custom `ggml` format and runs the inference on all `.wav` samples in the folder `samples`.

For detailed usage instructions, run: `./build/bin/whisper-cli -h`

Note that the [whisper-cli](examples/cli) example currently runs only with 16-bit WAV files, so make sure to convert your input before running the tool.
For example, you can use `ffmpeg` like this:

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav
```

## More audio samples

If you want some extra audio samples to play with, simply run:

```
make -j samples
```

This will download a few more audio files from Wikipedia and convert them to 16-bit WAV format via `ffmpeg`.

You can download and run the other models as follows:

```
make -j tiny.en
make -j tiny
make -j base.en
make -j base
make -j small.en
make -j small
make -j medium.en
make -j medium
make -j large-v1
make -j large-v2
make -j large-v3
make -j large-v3-turbo
```

## Memory usage

| Model | Disk | Mem |
| ------ | ------- | ------- |
| tiny | 75 MiB | ~273 MB |
| base | 142 MiB | ~388 MB |
| small | 466 MiB | ~852 MB |
| medium | 1.5 GiB | ~2.1 GB |
| large | 2.9 GiB | ~3.9 GB |

## POWER VSX Intrinsics

`whisper.cpp` supports POWER architectures and includes code which
significantly speeds operation on Linux running on POWER9/10, making it
capable of faster-than-realtime transcription on underclocked Raptor
Talos II. Ensure you have a BLAS package installed, and replace the
standard cmake setup with:

```bash
# build with GGML_BLAS defined
cmake -B build -DGGML_BLAS=1
cmake --build build -j --config Release
./build/bin/whisper-cli [ .. etc .. ]
```

## Quantization

`whisper.cpp` supports integer quantization of the Whisper `ggml` models.
Quantized models require less memory and disk space and depending on the hardware can be processed more efficiently.

Here are the steps for creating and using a quantized model:

```bash
# quantize a model with Q5_0 method
cmake -B build
cmake --build build -j --config Release
./build/bin/quantize models/ggml-base.en.bin models/ggml-base.en-q5_0.bin q5_0

# run the examples as usual, specifying the quantized model file
./build/bin/whisper-cli -m models/ggml-base.en-q5_0.bin ./samples/gb0.wav
```

## Core ML support

On Apple Silicon devices, the Encoder inference can be executed on the Apple Neural Engine (ANE) via Core ML. This can result in significant
speed-up - more than x3 faster compared with CPU-only execution. Here are the instructions for generating a Core ML model and using it with `whisper.cpp`:

- Install Python dependencies needed for the creation of the Core ML model:

```bash
pip install ane_transformers
pip install openai-whisper
pip install coremltools
```

- To ensure `coremltools` operates correctly, please confirm that [Xcode](https://developer.apple.com/xcode/) is installed and execute `xcode-select --install` to install the command-line tools.
- Python 3.11 is recommended.
- MacOS Sonoma (version 14) or newer is recommended, as older versions of MacOS might experience issues with transcription hallucination.
- [OPTIONAL] It is recommended to utilize a Python version management system, such as [Miniconda](https://docs.conda.io/en/latest/miniconda.html) for this step:
- To create an environment, use: `conda create -n py311-whisper python=3.11 -y`
- To activate the environment, use: `conda activate py311-whisper`

- Generate a Core ML model. For example, to generate a `base.en` model, use:

```bash
./models/generate-coreml-model.sh base.en
```

This will generate the folder `models/ggml-base.en-encoder.mlmodelc`

- Build `whisper.cpp` with Core ML support:

```bash
# using CMake
cmake -B build -DWHISPER_COREML=1
cmake --build build -j --config Release
```

- Run the examples as usual. For example:

```text
$ ./build/bin/whisper-cli -m models/ggml-base.en.bin -f samples/jfk.wav

...

whisper_init_state: loading Core ML model from 'models/ggml-base.en-encoder.mlmodelc'
whisper_init_state: first run on a device may take a while ...
whisper_init_state: Core ML model loaded

system_info: n_threads = 4 / 10 | AVX = 0 | AVX2 = 0 | AVX512 = 0 | FMA = 0 | NEON = 1 | ARM_FMA = 1 | F16C = 0 | FP16_VA = 1 | WASM_SIMD = 0 | BLAS = 1 | SSE3 = 0 | VSX = 0 | COREML = 1 |

...
```

The first run on a device is slow, since the ANE service compiles the Core ML model to some device-specific format.
Next runs are faster.

For more information about the Core ML implementation please refer to PR [#566](https://github.com/ggml-org/whisper.cpp/pull/566).

## OpenVINO support

On platforms that support [OpenVINO](https://github.com/openvinotoolkit/openvino), the Encoder inference can be executed
on OpenVINO-supported devices including x86 CPUs and Intel GPUs (integrated & discrete).

This can result in significant speedup in encoder performance. Here are the instructions for generating the OpenVINO model and using it with `whisper.cpp`:

- First, setup python virtual env. and install python dependencies. Python 3.10 is recommended.

Windows:

```powershell
cd models
python -m venv openvino_conv_env
openvino_conv_env\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-openvino.txt
```

Linux and macOS:

```bash
cd models
python3 -m venv openvino_conv_env
source openvino_conv_env/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-openvino.txt
```

- Generate an OpenVINO encoder model. For example, to generate a `base.en` model, use:

```
python convert-whisper-to-openvino.py --model base.en
```

This will produce ggml-base.en-encoder-openvino.xml/.bin IR model files. It's recommended to relocate these to the same folder as `ggml` models, as that
is the default location that the OpenVINO extension will search at runtime.

- Build `whisper.cpp` with OpenVINO support:

Download OpenVINO package from [release page](https://github.com/openvinotoolkit/openvino/releases). The recommended version to use is [2026.3.0](https://github.com/openvinotoolkit/openvino/releases/tag/2026.3.0). Ready to use Binaries of the required libraries can be found in the [OpenVino Archives](https://storage.openvinotoolkit.org/repositories/openvino/packages/2026.3/)

After downloading & extracting package onto your development system, set up required environment by sourcing setupvars script. For example:

Linux:

```bash
source /path/to/openvino_toolkit_ubuntu/setupvars.sh
```

Windows (cmd):

```powershell
C:\Path\To\openvino_toolkit_windows\setupvars.bat
```

And then build the project using cmake:

```bash
cmake -B build -DWHISPER_OPENVINO=1
cmake --build build -j --config Release
```

- Run the examples as usual. For example:

```text
$ ./build/bin/whisper-cli -m models/ggml-base.en.bin -f samples/jfk.wav

...

whisper_ctx_init_openvino_encoder: loading OpenVINO model from 'models/ggml-base.en-encoder-openvino.xml'
whisper_ctx_init_openvino_encoder: first run on a device may take a while ...
whisper_openvino_init: path_model = models/ggml-base.en-encoder-openvino.xml, device = GPU, cache_dir = models/ggml-base.en-encoder-openvino-cache
whisper_ctx_init_openvino_encoder: OpenVINO model loaded

system_info: n_threads = 4 / 8 | AVX = 1 | AVX2 = 1 | AVX512 = 0 | FMA = 1 | NEON = 0 | ARM_FMA = 0 | F16C = 1 | FP16_VA = 0 | WASM_SIMD = 0 | BLAS = 0 | SSE3 = 1 | VSX = 0 | COREML = 0 | OPENVINO = 1 |

...
```

The first time run on an OpenVINO device is slow, since the OpenVINO framework will compile the IR (Intermediate Representation) model to a device-specific 'blob'. This device-specific blob will get
cached for the next run.

For more information about the OpenVINO implementation please refer to PR [#1037](https://github.com/ggml-org/whisper.cpp/pull/1037).

## NVIDIA GPU support

With NVIDIA cards the processing of the models is done efficiently on the GPU via cuBLAS and custom CUDA kernels.
First, make sure you have installed `cuda`: https://developer.nvidia.com/cuda-downloads

Now build `whisper.cpp` with CUDA support:

```
cmake -B build -DGGML_CUDA=1
cmake --build build -j --config Release
```

or for newer NVIDIA GPU's (RTX 5000 series):
```
cmake -B build -DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES="86"
cmake --build build -j --config Release
```

## Vulkan GPU support
Cross-vendor solution which allows you to accelerate workload on your GPU.
First, make sure your graphics card driver provides support for Vulkan API.

Now build `whisper.cpp` with Vulkan support:
```
cmake -B build -DGGML_VULKAN=1
cmake --build build -j --config Release
```

## AMD ROCm GPU support

With AMD GPUs the processing can be accelerated via HIP/ROCm.
First, make sure you have installed [ROCm](https://rocm.docs.amd.com/en/latest/).

Now build `whisper.cpp` with HIP support:

```
cmake -B build -DGGML_HIP=1 -DAMDGPU_TARGETS="gfx1201"
cmake --build build -j --config Release
```

Replace `gfx1201` with your GPU architecture. You can find it with:

```
rocminfo | grep "gfx"
```

Common architectures: `gfx1100` (RX 7900 XTX), `gfx1101` (RX 7800 XT), `gfx1201` (RX 9070 XT).
For multiple GPUs with different architectures: `-DAMDGPU_TARGETS="gfx1100;gfx1201"`.

## BLAS CPU support via OpenBLAS

Encoder processing can be accelerated on the CPU via OpenBLAS.
First, make sure you have installed `openblas`: https://www.openblas.net/

Now build `whisper.cpp` with OpenBLAS support:

```
cmake -B build -DGGML_BLAS=1
cmake --build build -j --config Release
```

## Ascend NPU support

Ascend NPU provides inference acceleration via [`CANN`](https://www.hiascend.com/en/software/cann) and AI cores.

First, check if your Ascend NPU device is supported:

**Verified devices**
| Ascend NPU | Status |
|:-----------------------------:|:-------:|
| Atlas 300T A2 | Support |
| Atlas 300I Duo | Support |

Then, make sure you have installed [`CANN toolkit`](https://www.hiascend.com/en/software/cann/community) . The latest version of CANN is recommended.

Now build `whisper.cpp` with CANN support:

```
cmake -B build -DGGML_CANN=1
cmake --build b