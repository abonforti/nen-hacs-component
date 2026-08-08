from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import NenApiClient
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import NenDataCoordinator
from .models import subscription_identity

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = NenApiClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        session,
    )
    coordinator = NenDataCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting devices the account no longer reports.

    Closed contracts stop producing subscriptions, but Home Assistant keeps
    their devices in the registry with every entity unavailable. Without this
    hook the UI offers no way to delete them.
    """
    coordinator: NenDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    data = coordinator.data or {}
    legacy_ids = data.get("legacy_subscription_ids", {})

    current: set[tuple[str, str]] = set()
    for subscription_id, sub in data.get("subscriptions", {}).items():
        utility = sub.get("utility")
        if not utility:
            continue
        _, device_suffix = subscription_identity(
            config_entry.entry_id, utility, subscription_id, legacy_ids
        )
        current.add((DOMAIN, f"{config_entry.entry_id}_{device_suffix}"))

    return not any(identifier in current for identifier in device_entry.identifiers)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
