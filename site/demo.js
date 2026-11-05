"use strict";

const el = (id) => document.getElementById(id);
const audio = el("turn-audio");
const phone = el("phone");
const play = el("play");
const sound = el("sound");
const fallback = el("fallback");
const scenarioButtons = [...document.querySelectorAll("[data-scenario]")];
const stages = [...document.querySelectorAll(".trace li")];

let selected = "night";
let running = false;
let generation = 0;
let step = -1;
let animation = 0;
let stallTimer = 0;

function scenario() {
  return turns[selected];
}

function describeRoute() {
  el("route").textContent = selected === "sky" && fallback.checked
    ? "Phone unavailable → stream MOSS-TTS-Nano from the home server"
    : scenario().route;
}

function setPhase(phase, label) {
  phone.dataset.phase = phase;
  el("phone-phase").textContent = label;
}

function setLights(dimmed) {
  phone.dataset.light = dimmed ? "night" : "normal";
  el("console-effect").textContent = dimmed
    ? "Night Light · 10% warm white"
    : scenario().effect;
}

function setStep(next) {
  if (step === next) return;
  step = next;
  stages.forEach((stage, index) => {
    stage.toggleAttribute("data-complete", index < step);
    if (index === step) stage.setAttribute("aria-current", "step");
    else stage.removeAttribute("aria-current");
  });
}

function stop(completed = false) {
  generation += 1;
  running = false;
  cancelAnimationFrame(animation);
  animation = 0;
  clearTimeout(stallTimer);
  stallTimer = 0;
  audio.pause();
  if (audio.readyState > 0) audio.currentTime = 0;
  setPhase("ready", "Ready");
  setStep(completed ? stages.length : -1);
  setLights(completed && selected === "night");
  el("play-icon").textContent = "▶";
  el("play-label").textContent = completed ? "Replay turn" : "Play turn";
  el("announcement").textContent = completed ? "Turn complete. The console is ready." : "";
}

function select(name) {
  selected = name;
  stop();
  audio.src = `audio/${name}.mp3`;
  el("play-error").textContent = "";
  el("fallback-option").hidden = name !== "sky";
  scenarioButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.scenario === name));
  });
  el("request").textContent = `“${scenario().request}”`;
  el("reply").textContent = `“${scenario().reply}”`;
  el("intent").textContent = scenario().intent;
  describeRoute();
}

function showAt(seconds) {
  const { captureEnd, intentStart, speechStart, answerStart } = scenario().timing;
  const next = [captureEnd, intentStart, speechStart].findIndex((time) => seconds < time);
  const index = next === -1 ? 3 : next;
  const cue = index === 3 && seconds < answerStart;
  const labels = ["Listening", "Transcribing", "Resolving", cue ? "Thinking cue" : "Speaking"];
  const phases = ["listening", "processing", "processing", "speaking"];
  if (step !== index || el("phone-phase").textContent !== labels[index]) {
    setStep(index);
    setPhase(phases[index], labels[index]);
    if (index === 3 && selected === "night") setLights(true);
  }
}

function playWithoutAudio(token, offset = audio.currentTime) {
  if (token !== generation || animation) return;
  audio.pause();
  clearTimeout(stallTimer);
  stallTimer = 0;
  el("play-error").textContent = "Audio playback is unavailable. Continuing the visual replay. Play again to retry the audio.";
  const started = performance.now() - offset * 1000;
  function advance(now) {
    if (token !== generation) return;
    const seconds = (now - started) / 1000;
    if (seconds >= scenario().timing.end) {
      stop(true);
      return;
    }
    showAt(seconds);
    animation = requestAnimationFrame(advance);
  }
  animation = requestAnimationFrame(advance);
}

function watchAudio() {
  if (!running || animation || stallTimer) return;
  const token = generation;
  const position = audio.currentTime;
  stallTimer = setTimeout(() => {
    stallTimer = 0;
    if (token !== generation) return;
    if (audio.currentTime <= position) {
      playWithoutAudio(token, position);
    } else {
      watchAudio();
    }
  }, 6000);
}

play.addEventListener("click", () => {
  if (running) {
    stop();
    return;
  }

  const token = ++generation;
  running = true;
  el("play-error").textContent = "";
  el("announcement").textContent = "";
  el("play-icon").textContent = "■";
  el("play-label").textContent = "Stop";
  setLights(false);
  showAt(0);
  audio.muted = !sound.checked;
  if (audio.error) audio.load();
  watchAudio();
  audio.play().catch(() => playWithoutAudio(token));
});

audio.addEventListener("timeupdate", () => {
  if (running && !animation && !audio.paused) showAt(audio.currentTime);
});
audio.addEventListener("ended", () => {
  if (running && !animation && audio.ended) stop(true);
});
audio.addEventListener("error", () => {
  if (running && audio.error) playWithoutAudio(generation);
});
audio.addEventListener("waiting", watchAudio);
audio.addEventListener("stalled", watchAudio);
audio.addEventListener("playing", () => {
  clearTimeout(stallTimer);
  stallTimer = 0;
  if (animation) audio.pause();
});

sound.addEventListener("change", () => { audio.muted = !sound.checked; });
fallback.addEventListener("change", () => {
  if (running) stop();
  describeRoute();
});
scenarioButtons.forEach((button) => {
  button.addEventListener("click", () => select(button.dataset.scenario));
});

select(selected);
