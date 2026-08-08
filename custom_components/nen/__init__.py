from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import NenApiClient
from .const import CONF_EXCLUDED, CONF_PASSWORD, CONF_USERNAME, DOMAIN
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
    coordinator = NenDataCoordinator(
        hass, client, excluded=set(entry.options.get(CONF_EXCLUDED, []))
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _purge_unselected_devices(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so a changed selection takes effect immediately."""
    await hass.config_entries.async_reload(entry.entry_id)


def _current_device_identifiers(
    entry: ConfigEntry, coordinator: NenDataCoordinator
) -> set[tuple[str, str]]:
    data = coordinator.data or {}
    legacy_ids = data.get("legacy_subscription_ids", {})

    identifiers: set[tuple[str, str]] = set()
    for subscription_id, sub in data.get("subscriptions", {}).items():
        utility = sub.get("utility")
        if not utility:
            continue
        _, device_suffix = subscription_identity(
            entry.entry_id, utility, subscription_id, legacy_ids
        )
        identifiers.add((DOMAIN, f"{entry.entry_id}_{device_suffix}"))
    return identifiers


def _purge_unselected_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: NenDataCoordinator
) -> None:
    """Delete devices for contracts that are no longer set up.

    Home Assistant keeps devices in its registry once created. Leaving them
    behind after a contract is deselected would reproduce the stale, entirely
    unavailable devices this integration already had to work around.
    """
    current = _current_device_identifiers(entry, coordinator)
    registry = dr.async_get(hass)

    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if any(identifier in current for identifier in device.identifiers):
            continue
        registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting devices the account no longer reports.

    Closed contracts stop producing subscriptions, but Home Assistant keeps
    their devices in the registry with every entity unavailable. Without this
    hook the UI offers no way to delete them.
    """
    coordinator: NenDataCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    current = _current_device_identifiers(config_entry, coordinator)
    return not any(identifier in current for identifier in device_entry.identifiers)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
