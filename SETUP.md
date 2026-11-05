# Build a bedside voice system

Begin on the server. Once a sentence can make the round trip from text to MOSS audio to a Whisper transcript, add Home Assistant. Move synthesis onto Android after the server path works; that gives the phone a working fallback.

## Before starting

The Compose file targets an **x86-64 Linux host**, using host networking so Wyoming services and an optional phone forward stay on loopback. Start with 8 GB RAM and around 4 GB free disk for images, models and conversion work; these are planning allowances. Docker Engine and Compose v2 are required. The initial download needs internet; recognition and synthesis then run locally.

Ports **10600** (MOSS) and **10601** (Whisper) must be free. They deliberately differ from common Wyoming defaults. Home Assistant should run on this same host with host networking, as in the optional profile. Docker Desktop and remote Home Assistant instances need a different network arrangement and have not been validated here.

Clone the repository, or download its ZIP and run the commands from the extracted root. Models use public downloads without an API key.

## First, make the models speak and listen

```sh
docker compose build moss
docker compose run --rm moss prepare
docker compose up -d --wait moss whisper
```

`prepare` fetches the pinned OpenMOSS runtime, checks its SHA-256, and downloads both ONNX model bundles at fixed revisions. Assets live in the named `speech-data` volume. The runtime only opens the graphs needed for streaming CPU synthesis; PyTorch and a GPU are unnecessary.

```sh
docker compose exec moss python -m bedside_voice say \
  "The bedside light is on." --output /data/sample.wav
docker compose exec moss python -m bedside_voice transcribe --input /data/sample.wav
docker compose cp moss:/data/sample.wav ./sample.wav
```

Expect `complete: true`, a WAV at `sample.wav`, and a transcript equivalent to “The bedside light is on.” Punctuation may differ. The WAV is 24 kHz mono PCM16, including a 0.6-second protective tail. These commands save audio; they do not play it on a phone.

If startup fails, run `docker compose logs --tail=80 moss whisper`. A missing manifest means `prepare` did not finish. A connection refusal usually means model startup or download is still in progress; `--wait` uses readiness checks for both services. Port conflicts require changing the Compose command and matching client/Home Assistant port.

## Connect Home Assistant

For an existing Linux Home Assistant Container with host networking, add two **Wyoming Protocol** integrations under **Settings → Devices & services → Add integration**:

| Service | Host | Port |
| --- | --- | --- |
| Whisper | `127.0.0.1` | `10601` |
| MOSS | `127.0.0.1` | `10600` |

Under **Settings → Voice assistants**, create an English assistant. Choose Home Assistant as the conversation agent, Whisper for speech-to-text, and MOSS for text-to-speech with **Bedside Server** as the voice. Wyoming supplies model services; Home Assistant supplies intent handling. See the [official Wyoming integration](https://www.home-assistant.io/integrations/wyoming/) and [local voice setup](https://www.home-assistant.io/voice_control/voice_remote_local_assistant/).

### Try a virtual light first

A new installation can use the optional Home Assistant profile:

```sh
docker compose --profile homeassistant up -d homeassistant
```

This starts Home Assistant on port **8123** with a separate named config volume and the checked-in example configuration. Use it on a host without another Home Assistant instance on that port. Open `http://YOUR_SERVER:8123`, complete onboarding, then add the Wyoming integrations and assistant above. Access the UI from a device you normally use; browser microphone capture needs HTTPS, so use the Android Home Assistant app's Assist button for the spoken turn.

The example defines a virtual **Bedside Light** and a “night light” intent. Expose Bedside Light to Assist under **Settings → Voice assistants → Expose**, then type **night light** into Assist. Expect “Starting night light.” and a virtual light at roughly 10% brightness. Try the same sentence through the Android app's tap-to-talk. Standard commands such as “turn off bedside light” use Home Assistant's native intents.

The configuration is in [`examples/home-assistant/configuration.yaml`](examples/home-assistant/configuration.yaml). It uses [template lights](https://www.home-assistant.io/integrations/template/#light) and [intent scripts](https://www.home-assistant.io/integrations/intent_script/). For an existing installation, merge the individual example sections into your own configuration and restart after validating it. Keep your existing configuration intact.

The bedside deployment uses VACA as the display and capture/playback client. Its installation is separate: follow [VACA's upstream setup](https://github.com/msp1974/ViewAssist_Companion_App) and select the same Assist pipeline. The reference speech service below does not capture a microphone or draw a dashboard.

## Move synthesis to Android

This path is experimental. The app compiles locally and in CI; provisioning and playback from a fresh installation have not yet been verified on a handset.

Use an **ARM64 Android 10+ phone** with authorized USB debugging. The original deployment used a Galaxy A52s. The public app has a separate package, `com.darren236.bedsidevoice`, and only a headless synthesis service. It binds to loopback, requires a bearer token, and requires Android's privileged DUMP permission for ADB service startup. It has no microphone or account permission. Leave the server fallback running.

### 1. Convert a separate model bundle

```sh
docker compose run --rm moss quantize
mkdir -p .local
docker compose cp moss:/data/models-int8 .local/models-int8
```

This applies per-channel dynamic QInt8 to constant-weight MatMul/Gemm layers in the three TTS graphs. It checks that the input contract is unchanged and integer operations exist. The streaming codec stays FP32. The FP32 server bundle is preserved; an existing `models-int8` directory is refused to avoid silently replacing an earlier conversion.

### 2. Build the app

On the host, install Java 17, Python 3.10+, and the Android SDK with platform 35, Build Tools 34.0.0 and Platform Tools (which supplies `adb`). Allow several additional GB for the SDK, Gradle downloads and build output.

Set `ANDROID_HOME` to your SDK and `JAVA_HOME` to Java 17. The checked-in wrapper pins Gradle 8.9 and verifies the distribution checksum; AGP, Kotlin and ONNX Runtime Android versions are pinned in the build files.

From the repo root:

```sh
export PATH="$ANDROID_HOME/platform-tools:$PATH"
adb version
python3 --version
mkdir -p .local/android-tmp
export TMPDIR="$PWD/.local/android-tmp"
export ANDROID_TMP="$TMPDIR"
cd android
./gradlew --no-daemon "-Djava.io.tmpdir=$TMPDIR" :app:assembleDebug
cd ..
```

The debug APK is `android/app/build/outputs/apk/debug/app-debug.apk`. It includes the project's licence and notices under `assets/licenses/`. It is intended for ADB development, not app-store distribution. The app's source fingerprint and native runtime identity are included in its audio-cache identity. This reference removes the deployment's Galaxy-specific CPU affinity mask.

### 3. Select and provision your phone

Use `adb devices` to identify your own authorized device. Supply its serial explicitly:

```sh
python3 tools/provision_phone.py --serial YOUR_ADB_SERIAL \
  --apk android/app/build/outputs/apk/debug/app-debug.apk --data .local
```

This command installs this project's APK, transfers the public INT8 bundle and Ava prompt codes into its storage, generates a private token, starts the service, and forwards host loopback port **12883** to phone loopback port **12882**. It waits for the warmed model and saves its fingerprint in ignored `.local/phone.json`. The token is not printed.

Import that local connection file and restart the speech bridge:

```sh
docker compose cp .local/phone.json moss:/data/phone.json
docker compose restart moss
docker compose exec moss python -m bedside_voice say \
  "The bedside light is on." --route phone --output /data/phone-sample.wav
```

Inspect `docker compose logs --tail=30 moss`. The first successful phone reply logs `route=phone`; repeating the text logs `route=cache`. Unplugging before an uncached request should select `route=server`. A disconnect after answer PCM starts reports a synthesis error, with no repeated answer and no cached partial file. The CLI only promotes a WAV from `.partial` after `audio-stop`.

Reload the MOSS Wyoming integration in Home Assistant to discover **Bedside Phone**, then select it as the pipeline voice. Each request can explicitly choose Phone or Server. Without an explicit voice, the default is Server; set `BEDSIDE_ROUTE=phone` when starting Compose to change that default. Keep the Ava preset for the phone build: its reference codes are fixed during provisioning.

ADB forwards do not survive every disconnect or host reboot. Reconnect with `adb -s YOUR_ADB_SERIAL forward tcp:12883 tcp:12882` and start the service with `adb -s YOUR_ADB_SERIAL shell am start-foreground-service -n com.darren236.bedsidevoice/.PhoneSpeechService`. A permanent bedside installation needs a maintained USB connection or a separately configured authenticated SSH tunnel. The reference does not provision that tunnel or auto-start on phone boot.

## What this build reproduces

| Included in this repository | Deployment extension shown in the figures |
| --- | --- |
| Whisper recognition and native Home Assistant intents | Wikipedia retrieval and optional Qwen3 answers |
| Warm FP32 server MOSS, INT8 Android TTS, FP32 incremental codec | Deployment-specific voice reference |
| Normalized clock text, 75-token phone limit, server fallback | Pitch-preserving 1.10× tempo and guarded pause processing |
| Completed phone-reply cache with model fingerprint | Pre-generated 1,440 clock clips and 82 other confirmations |
| Virtual dimmable light and “night light” intent | Household integrations and VACA playback/wake hooks |
| Explicit ADB setup and loopback authentication | Maintained SSH forwarding and service lifecycle |

The reference streams at native pace and uses the public Ava preset. It is a starting point for reproducing the architecture. The [deployment measurements](results/README.md) use different voice, audio processing and CPU-affinity settings and should not be treated as expected results from a fresh clone. Phone model choice and reference voice must agree; re-provision and remove old cached clips after changing either.

## Checks and stopping

```sh
docker compose run --rm --no-deps --entrypoint python \
  -v "$PWD/tests:/app/tests:ro" moss -m unittest discover -s tests -v
docker compose down
```

The seven unit tests check pre-PCM fallback, partial-answer failure, completed-reply caching, the token limit, resampling and the phone protocol without a model download. CI also builds Android and exercises the “night light” intent in a network-isolated Home Assistant instance. The main stack was checked with a fresh public model download, real synthesis, recognition and INT8 conversion. The virtual light reached 10% with the expected reply. The newly packaged Android app's installation and phone playback remain to be checked on a separate device. APK compilation does not establish handset latency or end-to-end voice success.

`down` stops this Compose project and preserves model/config volumes. To stop the optional phone service, run `adb -s YOUR_ADB_SERIAL shell am force-stop com.darren236.bedsidevoice`. Removing `phone.json` from the speech volume and restarting MOSS returns to the server-only configuration.
