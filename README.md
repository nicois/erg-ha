# Erg Energy Scheduler

<img width="256" height="256" alt="image" src="https://erg.297108.xyz/icon.png" />

A Home Assistant integration that optimises the scheduling of controllable energy loads — pool pumps, EV chargers, water heaters, and similar — to minimise electricity costs and maximise solar self-consumption.

Erg takes your electricity tariffs, solar forecast, battery state, and a set of jobs with time constraints, then finds the cheapest times to run everything. It provides controls you can use in your automations to implement the schedule. Once a schedule has been generated, you can also directly <a href="https://erg.297108.xyz/api/v1/schedule/view">view</a> the current schedule:
<img width="1097" height="1181" alt="image" src="https://github.com/user-attachments/assets/20fb9eab-6eb3-41bc-b89a-d4dd0e0eee93" />

## Philosophy

Erg intentionally does not analyse your energy usage to infer your habits, but is instead driven by what you tell it. Based on tariff information, solar production, plus a combination of optional and forced "jobs", Erg
generates a recommended schedule for when these jobs should optimally be run.

This is what Erg takes into account:

- any "forced" jobs must be run at some time within their allotted window.
- any unforced jobs are assigned a financial benefit, and will be allocated if the additional cost (of importing energy, or not running other jobs) is warranted
- batteries can sustain damage when at very high or low charge. A financial configuration value ("battery preservation") can be assigned to this. If nonzero, Erg will try to keep battery levels in the 30-80% range. The greater the preservation value, the harder Erg avoids this.
- if "battery storage value" is nonzero, Erg will understand that all other things being equal, it's good to have a higher charge in the battery. The greater this value, the more likely you are to have a well-charged battery at the end of the scheduling period.

The scheduling algorithm is fairly advanced and is not suitable for running on a Home Assistant appliance. During installation of this integration, you will be prompted to authenticate (using Google) with the server. This is to allow rate-limiting, avoiding the server from being overloaded.

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations**.
3. Click the three-dot menu in the top right and select **Custom repositories**.
4. Enter `https://github.com/nicois/erg-ha` as the repository URL and select **Integration** as the category.
5. Click **Add**.
6. Search for "Erg Energy Scheduler" in HACS and install it.
7. Restart Home Assistant.

### Manual

Copy the `custom_components/erg` directory into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## Setup

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for "Erg Energy Scheduler".
3. Enter the connection details for your Erg server (host, port, and optionally an API token). You probably want to leave the defaults as-is.
4. Select Google as your identity provider. A new tab will open where you will authenticate with google, identifying yourself to the Erg server.

## Configuration

After setup, configure the integration via **Settings > Devices & Services > Erg Energy Scheduler > Configure**. Configuration is split into two sections.

### System parameters

| Option                        | Default               | Description                                                                                                                                                                              |
| ----------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grid import limit (kW)        | 10.0                  | Maximum power that can be drawn from the grid. The scheduler will not schedule jobs whose combined consumption exceeds this.                                                             |
| Grid export limit (kW)        | 5                     | Maximum power that can be exported to the grid (in addition to offsetting local consumption)                                                                                             |
| Inverter power (kW)           | 10                    | Maximum AC power the inverter can produce or consume.                                                                                                                                    |
| Battery capacity (kWh)        | 42                    | Total usable battery capacity. Set to 0 if you have no battery.                                                                                                                          |
| Battery storage value ($/kWh) | 0.10                  | Economic value of energy stored in the battery at the end of the scheduling horizon. Encourages the scheduler to keep the battery charged.                                               |
| Battery preservation ($/kWh)  | 0.03                  | Penalty for cycling the battery outside the 30-80% SoC band. Higher values discourage deep discharges and full charges.                                                                  |
| Battery SoC entity            | sensor.foxess_bat_soc | A Home Assistant entity that reports the battery's state of charge. Accepts both percentage (%) and kWh values.                                                                          |
| Solar forecast provider       | Auto                  | Set to "Auto-discover" to use solar forecast data from integrations like Solcast. The scheduler uses this to avoid running loads when solar generation could cover them for free.        |
| Update interval (minutes)     | 15                    | How often the schedule is recalculated.                                                                                                                                                  |
| Horizon (hours)               | 24                    | How far ahead to schedule. Longer horizons give better optimisation but are slower to compute.                                                                                           |
| Extend to end of day          | On                    | When enabled, the scheduling window extends to midnight of the final day rather than ending exactly at `now + horizon hours`. Useful for ensuring full-day jobs can always be scheduled. |
| Slot duration                 | 15m                   | The time resolution of the schedule. Smaller slots give more precise scheduling but increase computation. Format: `5m`, `15m`, `1h`, etc.                                                |
| Tariff source                 | Manual                | Where electricity prices come from. Choose **Manual** to use your configured tariff periods, or **AEMO Wholesale** to fetch live NEM PREDISPATCH spot prices from the Erg server.       |
| AEMO NEM region               | —                     | When tariff source is AEMO: the NEM region to use (NSW1, QLD1, VIC1, SA1, TAS1).                                                                                                        |

### Tariff periods

Add one or more electricity tariff periods. Each period defines the import price (what you pay) and feed-in price (what you earn for export) during a recurring time window.

When using **AEMO Wholesale** as the tariff source, your manual tariff periods act as price offsets that are added on top of the wholesale spot price. For example, if you configure a manual period with an import price of $0.20/kWh (representing network charges and retailer margin) and the AEMO spot price is $0.06/kWh, the scheduler sees a total import cost of $0.26/kWh. This lets you separate the volatile wholesale component from the stable retail components. If AEMO data is temporarily unavailable, the scheduler falls back to the manual tariff periods alone.

| Field                 | Description                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Name                  | A label for this period (e.g. "Peak", "Off-peak", "Shoulder").                                                    |
| Frequency             | When this tariff applies: daily, weekdays, weekends, a specific day of the week, or custom days.                  |
| Time window start     | Start time in HH:MM format.                                                                                       |
| Time window end       | End time in HH:MM format. Overnight windows (e.g. 22:00 to 06:00) are supported.                                  |
| Import price ($/kWh)  | Cost to import power during this period. Negative prices imply you are paid to import.                            |
| Feed-in price ($/kWh) | Payment received for exporting power during this period. Negative prices imply you will lose money if you feed in |

#### Importing tariffs from YAML

Instead of adding each tariff period one at a time, you can bulk-import them from YAML. In the tariff management menu, select **Import tariffs from YAML** and paste your tariff definition. This replaces all existing tariff periods.

```yaml
periods:
  - start: "00:00"
    name: "Morning"
    end: "10:00"
    import_price: 0.2695
    feed_in_price: 0.003
  - start: "10:00"
    name: "Midmorning"
    end: "11:00"
    import_price: 0.2695
    feed_in_price: 0
  - start: "11:00"
    name: "Midday"
    end: "14:00"
    import_price: 0
    feed_in_price: 0
  - start: "14:00"
    name: "Mid afternoon"
    end: "16:00"
    import_price: 0.2695
    feed_in_price: 0.003
  - start: "16:00"
    name: "Late afternoon"
    end: "18:00"
    import_price: 0.2695
    feed_in_price: 0.03
  - start: "18:00"
    name: "Evening"
    end: "20:00"
    import_price: 0.385
    feed_in_price: 0.15
  - start: "20:00"
    name: "Late evening"
    end: "21:00"
    import_price: 0.385
    feed_in_price: 0.03
  - start: "21:00"
    name: "Night"
    end: "00:00"
    import_price: 0.2695
    feed_in_price: 0.003
```

Each period requires `start` and `end` in HH:MM format. `import_price` and `feed_in_price` default to 0 if omitted. You can optionally include a `name` field per period; otherwise names are generated automatically. All imported periods are set to daily frequency. The outer `periods:` key is optional — a bare list is also accepted.

## Managing jobs

Jobs represent controllable loads that the scheduler can turn on and off. They are managed through Home Assistant services, either manually or via automation/script actions.

### Creating a job

Call the `erg.create_job` service:

```yaml
service: erg.create_job
data:
  entity_id: switch.pool_pump
  job_type: recurring
  ac_power: 1.5
  maximum_duration: 2h
  time_window_start: "06:00"
  time_window_end: "18:00"
```

**Required fields:**

- `entity_id` — The Home Assistant entity to control (e.g. `switch.pool_pump`).
- `job_type` — `recurring` (repeats on a schedule) or `oneshot` (runs once in an explicit time window).

**Common optional fields:**

| Field              | Default | Description                                                                                                  |
| ------------------ | ------- | ------------------------------------------------------------------------------------------------------------ |
| `ac_power`         | 0.0     | Power consumption in kW. Negative values represent generation.                                               |
| `min_ac_power`     | 0.0     | Minimum AC power (kW) when the load is active. Only used with `target_energy`. Defaults to `ac_power`.       |
| `dc_power`         | 0.0     | DC power that goes directly to/from the battery (e.g. DC-coupled solar).                                     |
| `benefit`          | 0.0     | Economic value of running this job for its full duration. The scheduler weighs this against the energy cost. |
| `force`            | false   | When true, the job must be scheduled regardless of cost.                                                     |
| `enabled`          | true    | When false, the job is excluded from scheduling.                                                             |
| `maximum_duration` | 1h      | Maximum run time per scheduling window.                                                                      |
| `minimum_duration` | 0s      | If the job runs at all, it must run for at least this long.                                                  |
| `minimum_burst`    | 0s      | Minimum contiguous run time. Prevents the scheduler from splitting a job into very short fragments.          |
| `target_energy`    | 0.0     | Total energy to deliver (kWh). When > 0, enables variable-power mode (see below). When 0, fixed-power.      |
| `min_energy`       | 0.0     | Minimum energy (kWh) for two-tier charging. The high-value portion that must be delivered (see below).       |
| `low_benefit`      | 0.0     | Benefit ($/run) for energy above `min_energy`. Used with two-tier charging (see below).                      |

**Recurring job fields:**

| Field               | Default | Description                                                           |
| ------------------- | ------- | --------------------------------------------------------------------- |
| `frequency`         | daily   | One of: `daily`, `weekdays`, `weekends`, `weekly`, `custom`.          |
| `time_window_start` | 09:00   | Earliest time the job may run (HH:MM).                                |
| `time_window_end`   | 17:00   | Latest time the job may run (HH:MM). Overnight windows are supported. |
| `day_of_week`       | —       | Day number (0=Monday through 6=Sunday) when `frequency` is `weekly`.  |
| `days_of_week`      | —       | List of day numbers when `frequency` is `custom`.                     |

**One-shot job fields:**

| Field    | Description                              |
| -------- | ---------------------------------------- |
| `start`  | Earliest start time (ISO 8601 datetime). |
| `finish` | Latest finish time (ISO 8601 datetime).  |

### Updating a job

```yaml
service: erg.update_job
data:
  job_entity_id: switch.pool_pump
  ac_power: 2.0
  time_window_end: "20:00"
```

Only the fields you provide are updated; everything else is unchanged.

### Deleting a job

```yaml
service: erg.delete_job
data:
  job_entity_id: switch.pool_pump
```

This removes the job and all its associated entities.

### Variable-power loads

When `target_energy` is set to a value greater than zero, the job enters variable-power mode. Instead of drawing a fixed amount of power whenever it runs, the solver chooses the power level per time slot within the range `[min_ac_power, ac_power]`. This is useful for loads like EV chargers that can charge at variable rates.

For example, an EV charger that can draw between 1.4 kW and 7.2 kW to deliver 30 kWh:

```yaml
service: erg.create_job
data:
  entity_id: switch.ev_charger
  job_type: oneshot
  ac_power: 7.2
  min_ac_power: 1.4
  target_energy: 30
  benefit: 10
  start: "2026-03-05T18:00:00+11:00"
  finish: "2026-03-06T07:00:00+11:00"
```

The solver will charge faster during cheap tariff periods and slower (or not at all) during expensive ones, while ensuring the 30 kWh target is met.

### Two-tier EV charging

For EV charging, you often want to guarantee a minimum charge (e.g. enough for tomorrow's commute) while opportunistically charging more if electricity is cheap. The `min_energy` and `low_benefit` fields enable this.

When `min_energy > 0` and `target_energy > min_energy`, the job is internally split into two tiers:

1. **Must-have tier**: delivers `min_energy` kWh at the full `benefit` rate. This portion is treated as high priority and will be scheduled even during moderately expensive periods.
2. **Surplus tier**: delivers the remaining `target_energy - min_energy` kWh at the `low_benefit` rate. This portion is only scheduled when electricity is cheap enough to justify the lower benefit.

Example: guarantee 40 kWh for the daily commute, but charge up to 60 kWh if prices are favourable:

```yaml
service: erg.create_job
data:
  entity_id: switch.ev_charger
  job_type: oneshot
  ac_power: 7.2
  min_ac_power: 1.4
  target_energy: 60
  min_energy: 40
  benefit: 10
  low_benefit: 2
  start: "2026-03-05T18:00:00+11:00"
  finish: "2026-03-06T07:00:00+11:00"
```

The scheduler values the first 40 kWh at $10 and the remaining 20 kWh at $2. If overnight prices are high, you still get the 40 kWh you need; if prices drop, the full 60 kWh is delivered.

## Entities

Once jobs are created, the integration exposes a range of entities for monitoring and control.

### Global sensors

| Entity                   | Description                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------------------------------- |
| Erg Net Value            | Net financial outcome of the current schedule (benefit + export revenue - cost).                                |
| Erg Total Cost           | Total cost of grid imports in the schedule.                                                                     |
| Erg Total Benefit        | Total benefit from scheduled jobs.                                                                              |
| Erg Export Revenue       | Revenue from grid exports.                                                                                      |
| Erg Battery SoC Forecast | Projected battery state of charge at the end of the horizon. Includes a time-series forecast in its attributes. |
| Erg Next Job             | Entity ID of the next job scheduled to start.                                                                   |
| Erg Schedule Age         | Minutes since the last successful schedule update.                                                              |

### Per-job entities

For each job, the following entities are created:

| Entity            | Platform      | Description                                                   |
| ----------------- | ------------- | ------------------------------------------------------------- |
| Scheduled         | Binary sensor | On when the job is scheduled to run in the current time slot. |
| Next Start        | Sensor        | Timestamp of the next scheduled start.                        |
| Run Time          | Sensor        | Total scheduled run time in hours.                            |
| Energy Cost       | Sensor        | Estimated energy cost for this job.                           |
| Enabled           | Switch        | Toggle whether this job is included in scheduling.            |
| Force             | Switch        | Toggle whether this job must be scheduled regardless of cost. |
| AC Power          | Number        | Adjust AC power consumption (kW).                             |
| Min AC Power      | Number        | Adjust minimum AC power for variable-power loads (kW).        |
| DC Power          | Number        | Adjust DC power (kW).                                         |
| Benefit           | Number        | Adjust economic benefit value.                                |
| Target Energy     | Number        | Target energy delivery (kWh). Set > 0 for variable-power.    |
| Min Energy        | Number        | Minimum energy for two-tier charging (kWh).                   |
| Low Benefit       | Number        | Benefit for energy above minimum (two-tier charging).         |
| Max Duration      | Text          | Maximum run duration (e.g. `2h`, `30m`).                      |
| Min Duration      | Text          | Minimum total run duration.                                   |
| Min Burst         | Text          | Minimum contiguous run duration.                              |
| Time Window Start | Text          | Earliest start time, HH:MM (recurring jobs only).             |
| Time Window End   | Text          | Latest end time, HH:MM (recurring jobs only).                 |
| Frequency         | Select        | Recurrence pattern (recurring jobs only).                     |

### Calendar

The **Erg Schedule** calendar entity shows all scheduled runs as events. Contiguous time slots are merged into single events. Each event includes the run time, energy cost, and benefit in its description.

## Automations

Job properties can be modified from automations using [device actions](https://www.home-assistant.io/docs/automation/action/). Available actions per job device:

- Set force on/off
- Set enabled on/off
- Set benefit, AC power, DC power
- Set target energy (variable-power mode)
- Set EV charging parameters (target energy, min energy, benefit, low benefit)
- Set maximum/minimum duration and minimum burst
- Set time window start and end

## Execution

The integration actively controls devices. At each slot interval it compares the schedule against the current state of each job's entity and calls `homeassistant.turn_on` or `homeassistant.turn_off` as needed. Entities that are unavailable or unknown are skipped.

When a job is currently running and a new schedule is computed, the active run is preserved to avoid unnecessary on/off cycling.

## Troubleshooting

- **Schedule not updating** — Check that the Erg server is reachable. The integration will show an error in the Home Assistant logs if it cannot connect.
- **Jobs not running** — Verify the job is enabled (check the Enabled switch) and that its time window overlaps with the current time.
- **Jobs discarded from schedule** — If a job's time window does not intersect with the scheduling horizon, or its minimum duration or minimum burst cannot fit within the available window, the scheduler will discard it and log a warning.
- **Forced job not scheduled** — If a forced job's maximum duration exceeds the available time in its window, the scheduler clamps the duration to fit. Check the Erg server logs for details.
- **Schedule solve timeout** — Large problems (many boxes, long horizons, small slots) may take longer to solve. The integration submits schedule requests asynchronously and polls for results, with a 2-minute timeout. If solves consistently time out, try increasing the slot duration or reducing the horizon.
