"""Exercise the checked-in intent against a fresh, network-isolated Home Assistant."""
import asyncio
from pathlib import Path

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml


async def main():
    Path("/work").mkdir(exist_ok=True)
    hass = HomeAssistant("/work")
    loader.async_setup(hass)
    config = load_yaml("/example/configuration.yaml")
    # Start only the components under test; disable unrelated discovery/UI services.
    config.pop("default_config", None)
    assert await bootstrap.async_from_config_dict(config, hass)
    await hass.async_start()
    await hass.async_block_till_done()
    try:
        result = await hass.services.async_call("conversation", "process",
            {"text": "night light", "language": "en"}, blocking=True, return_response=True)
        await hass.async_block_till_done()
        light = hass.states.get("light.bedside_light")
        assert light and light.state == "on", (light, result)
        assert light.attributes.get("brightness") in (25, 26), light
        assert result["response"]["speech"]["plain"]["speech"] == "Starting night light.", result
        print("Night light intent: expected reply, virtual light on, brightness 10%.")
    finally:
        await hass.async_stop()


asyncio.run(main())
