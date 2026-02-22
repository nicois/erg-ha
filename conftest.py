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
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.selector",
    "homeassistant.data_entry_flow",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.calendar",
    "homeassistant.components.event",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.switch",
    "homeassistant.components.text",
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

# Number stubs
number_mod = sys.modules["homeassistant.components.number"]
number_mod.NumberEntity = type("NumberEntity", (), {})
number_mod.NumberMode = MagicMock()

# Select stubs
select_mod = sys.modules["homeassistant.components.select"]
select_mod.SelectEntity = type("SelectEntity", (), {})

# Switch stubs
switch_mod = sys.modules["homeassistant.components.switch"]
switch_mod.SwitchEntity = type("SwitchEntity", (), {})

# Text stubs
text_mod = sys.modules["homeassistant.components.text"]
text_mod.TextEntity = type("TextEntity", (), {})

# Selector stubs
selector_mod = sys.modules["homeassistant.helpers.selector"]
selector_mod.TextSelectorConfig = type(
    "TextSelectorConfig",
    (),
    {"__init__": lambda self, **kw: self.__dict__.update(kw)},
)
selector_mod.TextSelector = type(
    "TextSelector",
    (),
    {"__init__": lambda self, config=None: None},
)

# Restore state stubs
restore_state_mod = sys.modules["homeassistant.helpers.restore_state"]
restore_state_mod.RestoreEntity = type("RestoreEntity", (), {})

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


# Config entries stubs — provide real base classes so flow tests work
def _options_flow_init(self, *_args, **_kwargs):
    pass

def _async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
    return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

def _async_create_entry(self, *, title="", data=None):
    return {"type": "create_entry", "title": title, "data": data or {}}

_OptionsFlow = type("OptionsFlow", (), {
    "__init__": _options_flow_init,
    "async_show_form": _async_show_form,
    "async_create_entry": _async_create_entry,
})

config_entries_mod = sys.modules["homeassistant.config_entries"]
config_entries_mod.OptionsFlow = _OptionsFlow
config_entries_mod.ConfigEntryState = MagicMock()


# ConfigSubentry stub — lightweight stand-in for the frozen dataclass
import uuid as _uuid

def _config_subentry_init(self, *, data, subentry_type, title, unique_id=None):
    self.data = data
    self.subentry_type = subentry_type
    self.title = title
    self.unique_id = unique_id
    self.subentry_id = _uuid.uuid4().hex

_ConfigSubentry = type("ConfigSubentry", (), {
    "__init__": _config_subentry_init,
})

config_entries_mod.ConfigSubentry = _ConfigSubentry
