"""Root conftest — stubs homeassistant so erg tests can run standalone."""

import sys
from unittest.mock import MagicMock

_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.integration_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.data_entry_flow",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.calendar",
    "homeassistant.components.event",
    "voluptuous",
]

for mod_name in _HA_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

vol_mock = sys.modules["voluptuous"]
vol_mock.Schema = MagicMock(return_value=MagicMock())
vol_mock.Required = MagicMock(side_effect=lambda k, **kw: k)
vol_mock.Optional = MagicMock(side_effect=lambda k, **kw: k)
vol_mock.Coerce = MagicMock(side_effect=lambda t: t)
vol_mock.In = MagicMock(side_effect=lambda x: x)

# Sensor stubs
sensor_mod = sys.modules["homeassistant.components.sensor"]
sensor_mod.SensorEntity = type("SensorEntity", (), {})
sensor_mod.SensorDeviceClass = MagicMock()
sensor_mod.SensorStateClass = MagicMock()
sensor_mod.SensorEntityDescription = type(
    "SensorEntityDescription",
    (),
    {"__init__": lambda self, **kw: self.__dict__.update(kw)},
)

# Binary sensor stubs
binary_sensor_mod = sys.modules["homeassistant.components.binary_sensor"]
binary_sensor_mod.BinarySensorEntity = type("BinarySensorEntity", (), {})

# Calendar stubs
calendar_mod = sys.modules["homeassistant.components.calendar"]
calendar_mod.CalendarEntity = type("CalendarEntity", (), {})
calendar_mod.CalendarEvent = type(
    "CalendarEvent",
    (),
    {"__init__": lambda self, **kw: self.__dict__.update(kw)},
)

# Entity helpers stubs
entity_mod = sys.modules["homeassistant.helpers.entity"]
entity_mod.Entity = type("Entity", (), {})

entity_platform_mod = sys.modules["homeassistant.helpers.entity_platform"]
entity_platform_mod.AddEntitiesCallback = MagicMock()

event_mod = sys.modules["homeassistant.helpers.event"]
event_mod.async_track_time_interval = MagicMock()

# Update coordinator stubs
def _coordinator_entity_init(self, coordinator, **kw):
    self.coordinator = coordinator

coordinator_mod = sys.modules["homeassistant.helpers.update_coordinator"]
coordinator_mod.CoordinatorEntity = type(
    "CoordinatorEntity",
    (),
    {"__init__": _coordinator_entity_init},
)
coordinator_mod.DataUpdateCoordinator = type(
    "DataUpdateCoordinator",
    (),
    {},
)
