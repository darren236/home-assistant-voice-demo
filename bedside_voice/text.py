"""Expand standalone Home Assistant clock replies for the small TTS model."""

import re


_SMALL = ("zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty")


def normalize_for_speech(text: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([AP]M)\.?", text.strip(), re.I)
    if not match:
        return text
    hour, minute = int(match[1]), int(match[2])
    period = match[3].upper()
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return text
    if hour == 12 and minute == 0:
        return "It is midnight." if period == "AM" else "It is noon."
    day_part = "morning" if period == "AM" else "afternoon" if hour == 12 or hour < 6 else "evening"
    if 0 < minute < 10:
        # Small character voices can turn "oh three" into "all three" or
        # "o'clock three". Spell out the relationship without a leading zero.
        unit = "minute" if minute == 1 else "minutes"
        return f"It is {_SMALL[minute]} {unit} past {_SMALL[hour]} in the {day_part}."
    if minute == 0:
        minutes = "o'clock"
    elif minute < 20:
        minutes = _SMALL[minute]
    else:
        minutes = _TENS[minute // 10]
        if minute % 10:
            minutes += " " + _SMALL[minute % 10]
    return f"It is {_SMALL[hour]} {minutes} in the {day_part}."
