from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NenDataCoordinator


@dataclass(frozen=True)
class NenSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any] = lambda _: None
    utility: str = "EE"  # "EE" or "GA"


ELECTRICITY_SENSORS: tuple[NenSensorDescription, ...] = (
    NenSensorDescription(
        key="ee_consumption_ytd",
        name="Consumption YTD",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        utility="EE",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get("ytd"),
    ),
    NenSensorDescription(
        key="ee_consumption_cap",
        name="Annual Cap",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        utility="EE",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get("cap"),
    ),
    NenSensorDescription(
        key="ee_consumption_latest",
        name="Last Day Consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        utility="EE",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get("latest_value"),
    ),
    NenSensorDescription(
        key="ee_monthly_rate",
        name="Monthly Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        utility="EE",
        value_fn=lambda sub: sub.get("contract", {}).get("monthly_rate"),
    ),
    NenSensorDescription(
        key="ee_unit_price",
        name="Unit Price",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=4,
        utility="EE",
        value_fn=lambda sub: sub.get("detail", {}).get("unit_price"),
    ),
)

GAS_SENSORS: tuple[NenSensorDescription, ...] = (
    NenSensorDescription(
        key="ga_consumption_ytd",
        name="Consumption YTD",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        utility="GA",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get("ytd"),
    ),
    NenSensorDescription(
        key="ga_consumption_latest",
        name="Last Month Consumption",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        utility="GA",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get("latest_value"),
    ),
    NenSensorDescription(
        key="ga_monthly_rate",
        name="Monthly Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        utility="GA",
        value_fn=lambda sub: sub.get("contract", {}).get("monthly_rate"),
    ),
    NenSensorDescription(
        key="ga_unit_price",
        name="Unit Price",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR/m³",
        suggested_display_precision=4,
        utility="GA",
        value_fn=lambda sub: sub.get("detail", {}).get("unit_price"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NenDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    subscriptions = coordinator.data.get("subscriptions", {})

    entities: list[NenSensor] = []
    for desc in (*ELECTRICITY_SENSORS, *GAS_SENSORS):
        sub = subscriptions.get(desc.utility)
        if sub is None:
            continue
        entities.append(NenSensor(coordinator, entry, desc))

    async_add_entities(entities)


class NenSensor(CoordinatorEntity[NenDataCoordinator], SensorEntity):
    entity_description: NenSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NenDataCoordinator,
        entry: ConfigEntry,
        description: NenSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

        utility_label = "Electricity" if description.utility == "EE" else "Gas"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{description.utility}")},
            name=f"NeN {utility_label}",
            configuration_url="https://nen.it",
        )

    @property
    def _subscription(self) -> dict:
        return self.coordinator.data["subscriptions"].get(
            self.entity_description.utility, {}
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._subscription)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sub = self._subscription
        attrs: dict[str, Any] = {}

        if self.entity_description.key.endswith("_ytd"):
            consumptions = sub.get("consumptions") or {}
            attrs["latest_date"] = consumptions.get("latest_date")
            attrs["pod"] = sub.get("pod")

        if "monthly_rate" in self.entity_description.key:
            contract = sub.get("contract", {})
            attrs["contract_end_date"] = contract.get("end_date")
            attrs["contract_start_date"] = contract.get("start_date")
            attrs["contract_name"] = contract.get("name")

        return {k: v for k, v in attrs.items() if v is not None}
