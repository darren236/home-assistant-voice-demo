# Bedside Voice

A spare Android phone became a bedside clock and voice console for Home Assistant. The system turns a spoken request into a room action or a short answer, then sends audio back to the phone.

![The Bedside Voice console and its step-by-step voice trace](media/preview.png)

## Try the demo

[Download the demo ZIP](https://github.com/darren236/home-assistant-voice-demo/archive/refs/heads/main.zip), extract it, and open `site/index.html` in a browser. The page runs from the extracted folder. The replay uses synthetic audio, scripted timing, and simulated devices.

| Example | What to look for |
| --- | --- |
| [Night Light](site/audio/night.mp3) | A room routine dims the simulated lights and plays a fixed confirmation. |
| [Ask the time](site/audio/clock.mp3) | The clock reply comes from a library with a pre-generated clip for each minute. |
| [Ask a question](site/audio/sky.mp3) | A thinking cue plays before the answer. The fallback toggle shows the route when phone synthesis is unavailable. |

## How the live system works

1. **Capture.** A Galaxy A52s running VACA captures the request and plays the reply.
2. **Recognize.** Faster Whisper transcribes the request on the home server.
3. **Resolve.** Home Assistant matches a room action or another intent. Public knowledge lookups can use an online source.
4. **Speak.** The bridge can play saved audio or stream MOSS-TTS-Nano output. The phone runs a quantized ONNX model. If it fails before answer audio starts, the home server can take over. A mid-answer failure ends the reply to avoid repeating partial speech.

A 24-hour snapshot of **120 turns that reached outgoing audio** included regular use and test replays. Capture end to first outgoing audio was **1.22 s median** and **7.30 s at the 90th percentile**. The measurement ends at server delivery. On some turns the first audio was the cue.

The console uses tap-to-talk while hands-free wake is paused. In a 20-clip offline replay, the trial detector accepted 8 of 10 intended calls and 0 of 10 negatives. The original accepted 10 of 10 intended calls and 5 of 10 negatives. Room false-wake performance remains unmeasured.

## Source and assets

The `site/` directory is the complete static site. Serve that directory as the document root for hosting. The stylized console is an original illustration. The sample audio was generated with built-in MOSS-TTS-Nano voice presets. `site/turns.js` stores captions and playback timestamps for the three scripted exchanges.

Built by **darren236**. [Home Assistant Assist](https://www.home-assistant.io/voice_control/voice_remote_local_assistant/) · [VACA](https://github.com/msp1974/ViewAssist_Companion_App) · [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano)
