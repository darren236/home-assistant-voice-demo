const turns = {
  "night": {
    "request": "Night light.",
    "reply": "Starting night light.",
    "intent": "Home Assistant runs the Night Light routine",
    "route": "Play the saved confirmation",
    "effect": "Room lights at full brightness",
    "timing": {
      "captureEnd": 1.22,
      "intentStart": 1.84,
      "speechStart": 2.34,
      "answerStart": 2.34,
      "end": 5.3
    }
  },
  "clock": {
    "request": "What time is it?",
    "reply": "It is eight forty-two in the evening.",
    "intent": "Resolve the clock question",
    "route": "Play the pre-generated clip for this minute",
    "effect": "Clock fixture \u00b7 8:42 PM",
    "timing": {
      "captureEnd": 2.42,
      "intentStart": 3.04,
      "speechStart": 3.54,
      "answerStart": 3.54,
      "end": 6.26
    }
  },
  "sky": {
    "request": "Why is the sky blue?",
    "reply": "Sunlight scatters in the air. Blue light scatters more than red light.",
    "intent": "Look up a public source and form a short answer",
    "route": "Play a thinking cue and stream a fresh answer from the phone",
    "effect": "Public knowledge question",
    "timing": {
      "captureEnd": 2.26,
      "intentStart": 2.88,
      "speechStart": 3.56,
      "answerStart": 4.9,
      "end": 10.74
    }
  }
};
