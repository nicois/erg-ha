# Erg HA Integration: UX Improvement Recommendations

## 1. Split the Options Form into Categorised Steps

**Problem**: The system configuration step (`async_step_init` in `config_flow.py:426`) presents 15+ fields in a single form — grid limits, battery parameters, solar settings, tariff source, slot duration, and preservation bounds all in one wall of inputs. Users are overwhelmed and don't know which fields matter for their setup.

**Recommendation**: Break into 2-3 sub-steps: (1) Grid & Battery (import/export limits, capacity, SoC entity, inverter power, efficiency) (2) Scheduling (slot duration, horizon, tariff source, AEMO region) (3) Advanced (battery preservation, preservation bounds, solar confidence, storage value). Most users only need step 1 and can accept defaults for the rest. The HA options flow supports a menu pattern already used by the tariff management section.

**Files**: `config_flow.py` (options flow init step), `strings.json` (step labels)

---

## 2. Replace Free-Text Entity IDs with HA Entity Selectors

**Problem**: Job creation (`config_flow.py:651`) asks users to type an entity ID as a plain string (e.g. `switch.pool_pump`). Users must know the exact ID format, get no autocomplete, and typos silently break the integration. The same issue applies to `battery_soc_entity` in system config, which defaults to the vendor-specific `sensor.foxess_bat_soc`.

**Recommendation**: Use HA's `EntitySelector` for all entity ID fields. This provides autocomplete, domain filtering (e.g. only show `switch.*` entities for jobs), and validation. For the SoC entity, filter to sensors with `device_class: battery` or `unit_of_measurement: %`. Remove the vendor-specific default.

**Files**: `config_flow.py` (job user step, options init step), `strings.json`

---

## 3. Replace Go-Duration Text Fields with Preset Selectors

**Problem**: Duration fields (maximum duration, minimum duration, minimum burst, slot duration) accept Go-style strings like `"1h30m"` but provide no format guidance. Users try `"90m"`, `"1.5h"`, or `"90 minutes"` and get cryptic validation errors. The same issue affects time window fields (`HH:MM`) and one-shot start/finish fields (ISO 8601).

**Recommendation**: For durations, use a `SelectSelector` with common presets (`5m`, `15m`, `30m`, `1h`, `2h`, `3h`, `4h`, `6h`, `8h`) plus a free-text option. For time windows, use a `TimeSelector`. For one-shot start/finish, use a `DateTimeSelector`. These all exist in the HA selector framework and eliminate format guessing entirely.

**Files**: `config_flow.py` (job recurring/oneshot steps, options init), `text.py` (runtime entity controls), `strings.json`

---

## 4. Clarify Monetary Sensor Names and Units

**Problem**: The global sensors (`sensor.py:53-129`) use ambiguous names: "Total Cost" (cost of what?), "Net Value" (profit? savings?), "Total Benefit" (from what?). Users seeing these on their dashboard can't tell what they represent without reading source code. The currency symbol is also hardcoded/implicit.

**Recommendation**: Rename to be self-describing:
- "Total Cost" -> "Grid Import Cost"
- "Export Revenue" -> "Grid Export Revenue" (already ok)
- "Total Benefit" -> "Job Scheduling Benefit"
- "Net Value" -> "Net Schedule Value"

Add a description attribute to each sensor explaining the calculation (e.g. "Total cost of grid electricity imports across all scheduled slots"). Consider exposing the currency as a configurable option.

**Files**: `sensor.py` (sensor name constants), `strings.json` (entity descriptions)

---

## 5. Add Inline Descriptions for Battery Preservation Settings

**Problem**: `battery_preservation`, `preservation_lower_bound`, and `preservation_upper_bound` in the options flow are opaque technical parameters. Users don't know that "0.3" means "30% SoC" or that the preservation cost is a penalty coefficient in $/kWh. The defaults (0.3/0.8) are reasonable for NMC chemistry but wrong for LFP, and there's no guidance on which to choose.

**Recommendation**: Add field descriptions in `strings.json` that explain in plain language: "Penalty cost ($/kWh) for operating battery outside the preferred charge range. Higher values keep the battery closer to the target band. Set to 0 to disable." For the bounds: "Lower bound: minimum preferred charge level (0.3 = 30%). LFP batteries can use 0.1. Upper bound: maximum preferred charge level (0.8 = 80%). LFP batteries can use 0.95." Consider adding a "Battery Chemistry" selector (NMC/LFP) that auto-sets sensible defaults.

**Files**: `strings.json` (init step data_description), `config_flow.py`

---

## 6. Surface Solver Errors to the User

**Problem**: The coordinator (`coordinator.py`) logs solver errors and API failures but doesn't surface them to the HA UI. When a schedule fails to solve (infeasible constraints, server unreachable, timeout), users see a stale schedule with no indication anything is wrong. The "Schedule Age" sensor shows staleness in raw minutes (e.g. "360") which doesn't clearly signal a problem.

**Recommendation**: Add a "Last Solve Status" sensor with states like "ok", "infeasible", "timeout", "connection_error". Store the error message in an attribute. Format "Schedule Age" as human-readable ("6h 0m ago") and set its `device_class` to `duration` so HA can render it natively. Consider making the Schedule Age sensor change icon/colour when older than a configurable threshold.

**Files**: `coordinator.py` (error tracking), `sensor.py` (schedule age formatting, new status sensor)

---

## 7. Explain the Two-Tier Energy Model in Job Configuration

**Problem**: The job form presents `target_energy`, `min_energy`, and `low_benefit` without explanation. These implement a two-tier EV charging model (high-value minimum charge + low-value top-up) that's powerful but incomprehensible to users who just want to charge their car. The `_split_ev_boxes` logic in the coordinator creates `__overflow` entities that appear in logs and confuse debugging.

**Recommendation**: Add a `data_description` entry in `strings.json` for each field:
- `target_energy`: "Total energy to deliver (kWh). Set to 0 for fixed-power devices like pumps. Set >0 for variable-power loads like EV chargers."
- `min_energy`: "Minimum energy that must be delivered (kWh). The solver treats this portion as high-priority. Leave 0 if all energy is equally important."
- `low_benefit`: "Benefit for energy above the minimum ($/run). Only used when min_energy > 0. Set lower than benefit to make the top-up portion optional."

Also consider hiding these fields behind an "Advanced" toggle for non-EV jobs.

**Files**: `strings.json` (data_description for job user step), `config_flow.py`

---

## 8. Improve Calendar Event Descriptions

**Problem**: The schedule calendar (`calendar.py:105-131`) shows job assignments as events with terse descriptions like "Run time: 5.50h, Cost: $2.34, Benefit: $5.00". Contiguous slots are silently merged into single events. Users can't tell whether an event represents one continuous run or the total across the day, and the description format is hard to scan.

**Recommendation**: Structure the event description as a readable summary: "Runs continuously from 09:00 to 14:30 (5h 30m). Grid cost: $2.34. Scheduling benefit: $5.00." For variable-power jobs, add "Energy delivered: 12.5 kWh, avg power: 2.3 kW". If the assignment has gaps (non-contiguous slots), show "Runs in 2 blocks: 09:00-11:00, 14:00-15:30". This makes the calendar a useful operational dashboard rather than just a list of opaque blocks.

**Files**: `calendar.py` (event creation logic)

---

## 9. Rename "Force" and "Scheduled" to User-Friendly Terms

**Problem**: The binary sensor "Erg {entity_id} Scheduled" (`binary_sensor.py:128`) is ambiguous — does "scheduled" mean "has a schedule for today" or "running right now"? The "Force" switch (`switch.py:77`) is equally unclear — force what? Users familiar with HA expect binary sensors to reflect current state and switches to have obvious effect descriptions.

**Recommendation**: Rename "Scheduled" binary sensor to "Active Now" or "Currently Running" — it reflects whether the current time slot has the job scheduled. Rename the "Force" switch to "Must Run" with a description: "When enabled, this job runs for its full duration regardless of energy cost. Disable to let the optimizer decide." These names communicate intent without requiring knowledge of the scheduling algorithm.

**Files**: `binary_sensor.py` (entity naming), `switch.py` (entity naming), `strings.json`

---

## 10. Add a Solve Status Notification and Integration Health Service

**Problem**: There is no mechanism for users to know the integration is working correctly. Schedules solve in the background on a timer. If the server is down, credentials expire, or the problem is infeasible, the integration silently keeps the last good schedule until it expires. The reauth flow handles token expiry but only fires after a failed request. Users building automations around the schedule have no way to check if the data is fresh.

**Recommendation**: (a) Fire a persistent notification when a solve fails, with the error message and a suggestion (e.g. "Schedule solve failed: forced jobs exceed grid import limit. Check your job configurations."). Clear the notification on next successful solve. (b) Add an `erg.check_health` service that returns the connection status, last solve time, last error, and number of active jobs — useful for automation conditions and dashboard status cards. (c) Add a "Solve Now" button entity (or service) so users can manually trigger a re-solve after changing parameters instead of waiting for the next cycle.

**Files**: `coordinator.py` (notification logic, health service), `services.yaml` (new service definitions), `button.py` (new file for solve trigger)
