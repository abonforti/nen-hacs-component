from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
from .models import subscription_identity


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
        key="ee_consumption_cap_usage",
        name="Annual Cap Usage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        suggested_display_precision=1,
        utility="EE",
        value_fn=lambda sub: (sub.get("consumptions") or {}).get(
            "cap_usage_percentage"
        ),
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
    NenSensorDescription(
        key="ee_last_bill_date",
        name="Last Bill Date",
        device_class=SensorDeviceClass.DATE,
        utility="EE",
        value_fn=lambda sub: sub.get("last_bill", {}).get("emission_date"),
    ),
    NenSensorDescription(
        key="ee_last_bill_charge_date",
        name="Last Bill Charge Date",
        device_class=SensorDeviceClass.DATE,
        utility="EE",
        value_fn=lambda sub: sub.get("last_bill", {}).get("charge_date"),
    ),
    NenSensorDescription(
        key="ee_last_bill_status",
        name="Last Bill Status",
        utility="EE",
        value_fn=lambda sub: sub.get("last_bill", {}).get("status"),
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
    NenSensorDescription(
        key="ga_last_bill_date",
        name="Last Bill Date",
        device_class=SensorDeviceClass.DATE,
        utility="GA",
        value_fn=lambda sub: sub.get("last_bill", {}).get("emission_date"),
    ),
    NenSensorDescription(
        key="ga_last_bill_charge_date",
        name="Last Bill Charge Date",
        device_class=SensorDeviceClass.DATE,
        utility="GA",
        value_fn=lambda sub: sub.get("last_bill", {}).get("charge_date"),
    ),
    NenSensorDescription(
        key="ga_last_bill_status",
        name="Last Bill Status",
        utility="GA",
        value_fn=lambda sub: sub.get("last_bill", {}).get("status"),
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
    for subscription_id, sub in subscriptions.items():
        descriptions = {
            "EE": ELECTRICITY_SENSORS,
            "GA": GAS_SENSORS,
        }.get(sub.get("utility"), ())
        for desc in descriptions:
            entities.append(NenSensor(coordinator, entry, desc, subscription_id))

    async_add_entities(entities)


class NenSensor(CoordinatorEntity[NenDataCoordinator], SensorEntity):
    entity_description: NenSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NenDataCoordinator,
        entry: ConfigEntry,
        description: NenSensorDescription,
        subscription_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._subscription_id = subscription_id

        legacy_ids = coordinator.data.get("legacy_subscription_ids", {})
        unique_prefix, device_suffix = subscription_identity(
            entry.entry_id,
            description.utility,
            subscription_id,
            legacy_ids,
        )
        self._attr_unique_id = f"{unique_prefix}_{description.key}"

        utility_label = "Electricity" if description.utility == "EE" else "Gas"
        sub = coordinator.data["subscriptions"][subscription_id]
        location = sub.get("home_name") or sub.get("home_address") or sub.get("pod")
        device_name = f"NeN {utility_label}"
        if (
            len(
                [
                    item
                    for item in coordinator.data["subscriptions"].values()
                    if item.get("utility") == description.utility
                ]
            )
            > 1
            and location
        ):
            device_name = f"{device_name} - {location}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{device_suffix}")},
            name=device_name,
            configuration_url="https://nen.it",
        )

    @property
    def _subscription(self) -> dict:
        return self.coordinator.data["subscriptions"].get(self._subscription_id, {})

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._subscription)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sub = self._subscription
        attrs: dict[str, Any] = {}

        attrs["home"] = sub.get("home_name")
        attrs["address"] = sub.get("home_address")
        attrs["pod"] = sub.get("pod")
        attrs["contract_status"] = sub.get("status")

        if self.entity_description.key.endswith("_ytd"):
            consumptions = sub.get("consumptions") or {}
            attrs["latest_date"] = consumptions.get("latest_date")

        if self.entity_description.key.endswith("_cap_usage"):
            consumptions = sub.get("consumptions") or {}
            attrs["delta_percentage"] = consumptions.get("delta_percentage")

        if "monthly_rate" in self.entity_description.key:
            contract = sub.get("contract", {})
            attrs["contract_end_date"] = contract.get("end_date")
            attrs["contract_start_date"] = contract.get("start_date")
            attrs["contract_name"] = contract.get("name")

        if "last_bill" in self.entity_description.key:
            last_bill = sub.get("last_bill") or {}
            attrs["amount"] = last_bill.get("amount")
            attrs["number"] = last_bill.get("number")
            attrs["residual"] = last_bill.get("residual")

        return {k: v for k, v in attrs.items() if v is not None}
