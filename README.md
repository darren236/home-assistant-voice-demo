# Bedside Voice

A spare Android phone becomes a local Home Assistant voice console. Say “night light,” ask the time, or ask a question; the phone captures your request and plays the reply. **Whisper Small INT8** handles recognition on the server. **MOSS-TTS-Nano 100M** can generate speech on the phone CPU, with a server fallback.

The phone already had a screen, microphone and speaker. The interesting question was whether it could also synthesize a fresh reply quickly enough to be useful. That led to a split system: Home Assistant handles the home, while the phone does more of the speech work.

**[Try the replay](#see-a-turn)** · **[Build your own](#run-the-speech-stack)** · **[Read the measurements](results/README.md)**

The server example is verified through real synthesis, recognition and a virtual light command. The Android service builds, but a fresh handset installation and playback have not yet been verified.

![The bedside clock and turn trace during a spoken reply](media/preview.png)

## See a turn

[Download the ZIP](https://github.com/darren236/home-assistant-voice-demo/archive/refs/heads/main.zip), extract it, and open `site/index.html` in Chrome. Choose **Night light**, **Ask the time**, or **Ask a question**. Follow the transcript and model route while the audio plays.

This is a scripted replay with public MOSS voice presets. The phone-offline switch illustrates fallback using the same recording. The runnable code below performs real inference.

## How a request travels

![The phone captures, synthesizes and plays speech; the server transcribes, resolves intents and routes replies.](media/workflow-mobile.png)

“Night light” becomes text through Whisper. Home Assistant matches it to an intent, changes the light, and produces a short confirmation. The speech bridge decides how to deliver that confirmation; the handset plays the resulting audio. A room command can take this entire path without an LLM.

| Component | Model | Why it is here |
| --- | --- | --- |
| Recognition · server CPU | [Whisper Small INT8](https://huggingface.co/rhasspy/faster-whisper-small-int8), via Faster Whisper | Keeps English recognition local. |
| Speech · phone or server CPU | [MOSS-TTS-Nano 100M ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) | Small enough to explore speech generation on a reused phone. Phone dense layers use INT8; the server keeps FP32. |
| Audio decoding · alongside synthesis | [MOSS Audio Tokenizer Nano 20M ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX) | Turns generated audio tokens into PCM incrementally. The codec stays FP32. |

The deployed console uses [VACA](https://github.com/msp1974/ViewAssist_Companion_App) for capture and playback. Its optional knowledge route adds Wikipedia and local [Qwen3 4B Instruct](https://ollama.com/library/qwen3:4b-instruct). The reference build starts with Home Assistant's native intents and tap-to-talk.

## Why replies take different routes

![Saved PCM bypasses synthesis. Fresh replies use phone INT8 or server FP32 synthesis, then stream to the handset.](media/synthesis-mobile.png)

A clock answer repeats every day; a fresh explanation does not. Saving completed speech removes generation from repeated replies. On a cache miss, the phone generates audio tokens and decodes the first frame immediately, then two frames at a time. Short chunks let playback begin while the rest of the sentence is still being generated.

A phone reply has a 75-token budget. Longer replies use the server. If the phone fails before sending answer PCM, the server takes over. Once answer PCM has started, a failure ends that reply: restarting it would repeat words the listener already heard. Those boundaries are implemented in [`server.py`](bedside_voice/server.py) and covered by routing tests.

The figures describe the deployed system, including its pre-generated bank and audio processing. The reference build below reproduces the speech split, incremental decoder, completed-reply cache and fallback. Its [scope and differences](SETUP.md#what-this-build-reproduces) are explicit.

## Run the speech stack

On an **x86-64 Linux host with Docker Compose v2**, allow roughly 4 GB free disk and start with 8 GB RAM. Internet is needed to fetch public models; inference then runs locally. No GPU, API key or private reference recording is required.

```sh
git clone https://github.com/darren236/home-assistant-voice-demo.git
cd home-assistant-voice-demo
docker compose build moss
docker compose run --rm moss prepare
docker compose up -d --wait moss whisper
```

Generate a real reply, then ask Whisper to transcribe it:

```sh
docker compose exec moss python -m bedside_voice say \
  "The bedside light is on." --output /data/sample.wav
docker compose exec moss python -m bedside_voice transcribe --input /data/sample.wav
docker compose cp moss:/data/sample.wav ./sample.wav
```

You should get a complete WAV and a transcript of that sentence. This checks the two speech models without requiring a microphone or changing a device. Then [connect Home Assistant and try the virtual bedside light](SETUP.md#connect-home-assistant), or [build the Android synthesis service](SETUP.md#move-synthesis-to-android). The repository includes the app source, INT8 conversion and device provisioning tool.

## What the phone achieved

On a Galaxy A52s, 24 warm INT8 replies produced first PCM in **279–360 ms** (median **288 ms**) and a native real-time factor of **0.838–1.004×**. A value below 1 means generation was faster than the audio's native playback duration. First PCM can contain silence; this does not measure when the speaker becomes audible.

In 120 deployed turns with outgoing audio, capture end to first outgoing audio had a **1.22 s median** and **7.30 s 90th percentile**, sometimes ending at a thinking cue. The spread matters for everyday use. [The results](results/README.md) explain the timing boundaries, settings and small wake-word trial that led back to tap-to-talk.

The model and codec come from OpenMOSS. This project's work is the Android service, incremental decoding, quantization, speech routing and playback integration. The project is licensed under [Apache-2.0](LICENSE); [NOTICE](NOTICE) records upstream and media attribution. Model weights are downloaded separately under their model licences. Built by **darren236**.
