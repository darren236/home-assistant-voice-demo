# Bedside Voice

A Home Assistant voice console built on a spare Galaxy A52s. **Whisper Small INT8** transcribes speech on the home server. **MOSS-TTS-Nano 100M** streams replies from the phone CPU, with a full-precision server fallback.

## From a spoken request to a reply

<picture>
  <source media="(max-width: 760px)" srcset="site/diagrams/workflow-mobile.svg">
  <img src="site/diagrams/workflow.svg" alt="Three stages show capture on a Galaxy A52s, recognition and intent resolution on the server, and speech playback on the handset.">
</picture>

VACA captures microphone audio after a tap on the Galaxy A52s. The server runs Faster Whisper with the Whisper Small INT8 model, then passes the transcript to Home Assistant Assist to resolve a room command or an answer. Public knowledge questions can add a Wikipedia lookup and local Qwen3 4B Instruct generation.

The reply goes through the speech bridge, which can reuse saved audio or request fresh MOSS-TTS-Nano synthesis. Home Assistant streams the result back to VACA on the same handset for playback. The phone handles capture and playback, while the server coordinates recognition, intent resolution, and reply delivery.

## Models and where they run

| Job | Model | Use in this project |
| --- | --- | --- |
| Speech recognition | [Whisper Small INT8](https://huggingface.co/rhasspy/faster-whisper-small-int8) | English speech on the server CPU via [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) and [Wyoming](https://www.home-assistant.io/integrations/wyoming/). |
| Speech synthesis | [MOSS-TTS-Nano 100M ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) | Primary bedside voice. The Android build quantizes dense layers to INT8. The server runs the FP32 graph for fallback. |
| Audio codec | [MOSS Audio Tokenizer Nano 20M ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX) | Decodes generated audio tokens into PCM. The Android decoder stays FP32 and streams incremental chunks. |
| Optional public Q&A | [Qwen3 4B Instruct](https://ollama.com/library/qwen3:4b-instruct) | Local Ollama can compose a short answer from retrieved Wikipedia passages. Direct extraction handles simpler questions. Home Assistant Assist resolves room commands. |
| Wake-word trial | [Custom openWakeWord classifier](https://github.com/dscripka/openWakeWord) | TFLite on Android. Hands-free wake is paused after false triggers. Tap-to-talk is the active entry point. |
| Separate phone Assist pipeline | [Piper `en_US-lessac-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium) | Server-side speech synthesis for standard phone Assist. The bedside console uses the MOSS pipeline. |

## Try the replay

[Download the ZIP](https://github.com/darren236/home-assistant-voice-demo/archive/refs/heads/main.zip), extract it, and open `site/index.html` in Chrome. The replay uses scripted device states and audio rendered with built-in MOSS-TTS-Nano voice presets.

![The bedside clock and turn trace during a spoken reply](media/preview.png)

- [Night Light](site/audio/night.mp3) uses a saved spoken confirmation and dims the simulated room.
- [Ask the time](site/audio/clock.mp3) illustrates the pre-generated clock bank.
- [Ask a question](site/audio/sky.mp3) plays a thinking cue before a fresh answer. The phone-offline toggle illustrates server fallback with the same recording.

## Inside the streaming synthesis path

<picture>
  <source media="(max-width: 760px)" srcset="site/diagrams/synthesis-mobile.svg">
  <img src="site/diagrams/synthesis.svg" alt="The server checks saved audio before sending text tokens to Android. MOSS-TTS-Nano generates audio tokens and its codec decodes PCM, which returns through the server for handset playback.">
</picture>

With Phone selected, the server normalizes the reply and checks its saved PCM bank. A cache hit skips synthesis. For a fresh reply, the server sends up to 75 SentencePiece tokens to the warm Android model. MOSS-TTS-Nano 100M uses INT8 dense layers to generate audio tokens from the text and reference audio codes. The MOSS Audio Tokenizer Nano 20M decoder stays FP32 and turns those tokens into PCM, decoding the first frame alone and then two frames at a time.

The server resamples the streamed PCM, applies pitch-preserving tempo and short-pause processing, and buffers it for Home Assistant playback. If the phone route fails before delivering answer PCM, the server can use its FP32 MOSS model even if a thinking cue has already played. A failure after answer PCM starts ends the reply without replaying it.

The saved bank holds **1,440 clock clips** and **82 common and volume confirmations**. These replies bypass live synthesis on the phone route. A fresh answer can play a short thinking cue while generation runs.

## What was measured

| Test | Result | Timing boundary |
| --- | --- | --- |
| Warm INT8 synthesis on the Galaxy A52s, 24 replies | **288 ms** median to first PCM. **0.942×** median real-time factor, range **0.838–1.004×**. | After input tokens arrive. Component benchmark without capture, network transit, or speaker playback. |
| Voice pipeline, 120 turns with outgoing audio | **1.22 s** median and **7.30 s** at the 90th percentile. | End of capture to first outgoing audio, which can be the thinking cue. Mixed normal use and test replays. |
| Wake-word detector, 20-clip offline replay | Original accepted 10/10 intended calls and 5/10 negatives. Trial accepted 8/10 intended calls and 0/10 negatives. | Small offline comparison. An unattended room false-wake rate has yet to be measured. |

The optimized phone run used three threads with CPU spinning and two-frame codec batches after the first frame. The earlier FP32 run on the same phone took 1.70–1.89× audio duration across three replies. Precision, thread count, and codec scheduling differed between runs. A real-time factor below 1 means generation takes less time than the resulting audio. First PCM can contain silence.

Two handset microphone replays illustrate the timing boundaries. Capture end to first outgoing audio took **1,295 ms** for a fresh reply with a cue and **1,064 ms** for a pre-generated clock reply. Bridge request to first answer PCM took **1,147 ms** and **7 ms**, respectively. Both received playback acknowledgements. Each route has one observation, and the two clocks start at different points.

## Source and assets

`site/` is the complete static demo. Its HTML, CSS, JavaScript, and MP3s run from the extracted folder or any static host. `site/turns.js` contains the captions and playback timestamps. `site/diagrams/` contains the editable SVG figures, with desktop and stacked mobile layouts. The project measurements above come from recorded deployment and component tests, separate from the browser replay.

Built by **darren236**. [Home Assistant Assist](https://www.home-assistant.io/voice_control/voice_remote_local_assistant/) · [VACA](https://github.com/msp1974/ViewAssist_Companion_App) · [OpenMOSS](https://github.com/OpenMOSS/MOSS-TTS-Nano)
