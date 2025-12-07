"""Lifedomus integration constants.

This module contains integration-wide constants such as domain name,
configuration keys, default values, and Lifedomus-specific CLSIDs for
devices, actions, properties, and states.
"""

from __future__ import annotations

import re
from typing import Final

MANUFACTURER: Final = "Delta Dore"
DOMAIN: Final = "lifedomus"
MODEL: Final = "Lifedomus"

# Multicast discovery constants (IPv4)
DISCOVERY_MCAST_ADDR: Final = "229.51.0.13"
DISCOVERY_MCAST_PORT: Final = 51013
DISCOVERY_TIMEOUT_S: Final = 5.0
DISCOVERY_PACKET_PREFIX: Final = b"\x04\x01\x07\x01\x03"
DISCOVERY_PACKET_SUFFIX: Final = b"\x01"

# UI sentinel for the "enter host manually" option in the discovery step.
MANUAL_SELECT_VALUE: Final = "__ENTER_HOST_MANUALLY__"
MANUAL_SELECT_LABEL: Final = "Enter host manually"

# Keys stored in the config entry.
CONF_HOST: Final = "host"
CONF_NAME: Final = "name"
CONF_SITE_KEY: Final = "site_key"
CONF_SITE_LABEL: Final = "label"
CONF_USER_KEY: Final = "user_key"
CONF_PASSWORD: Final = "password"
CONF_UUID: Final = "uuid"
CONF_VERSION: Final = "version"
CONF_ALARM_CODE: Final = "alarm_code"

# Global option keys.
OPTION_UPDATE_INTERVAL: Final = "update_interval"
OPTION_UPDATE_INTERVAL_DEFAULT: Final = 60  # seconds

LD_HTTP_HEADERS: Final = {
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip",
    "Content-Type": "text/xml; charset=utf-8",
}
LD_PORT: Final[int] = 8443
LD_MONITOR_SSH_PORT: Final[int] = 51023
LD_MONITOR_SSH_USER: Final[str] = "ld-remote"
LD_MONITOR_TUNNEL_PORT: Final[int] = 8090

# SOAP namespaces used when building/parsing envelopes. The envelope namespace is
# defined by the SOAP/1.1 envelope schema and is used on Body parsing.
SOAP_NAMESPACE: Final = "http://schemas.xmlsoap.org/soap/envelope/"

PATTERN_DEVICE_KEY: Final[re.Pattern[str]] = re.compile(r"^DEVC_[0-9]{35}$")
PATTERN_SESSION_KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{40}$")
PATTERN_SITE_KEY: Final[re.Pattern[str]] = re.compile(r"^SITE_[0-9]{35}$")
PATTERN_USER_KEY: Final[re.Pattern[str]] = re.compile(r"^USER_[0-9]{35}$")

# --- Actions CLSIDs ---
LD_ACTION_ALARM_FULL_ARMING: Final[str] = "CLSID-ACTION-ALARM-FULL-ARMING"
LD_ACTION_ALARM_STOP: Final[str] = "CLSID-ACTION-ALARM-STOP"
LD_ACTION_ALARM_ZONE_ENABLE: Final[str] = "CLSID-ACTION-ALARM-ZONE-ENABLE"
LD_ACTION_ALARM_ZONE_DISABLE: Final[str] = "CLSID-ACTION-ALARM-ZONE-DISABLE"
LD_ACTION_ALARM_EVENTS_ACKNOWLEDGE: Final[str] = "CLSID-ACTION-ALARM-ACKNOWLEDGE-EVENTS"
LD_ACTION_DOWN: Final[str] = "CLSID-ACTION-DOWN"
LD_ACTION_OFF: Final[str] = "CLSID-ACTION-OFF"
LD_ACTION_ON: Final[str] = "CLSID-ACTION-ON"
LD_ACTION_PUSH: Final[str] = "CLSID-ACTION-PUSH"
LD_ACTION_STOP: Final[str] = "CLSID-ACTION-STOP"
LD_ACTION_UP: Final[str] = "CLSID-ACTION-UP"
LD_ACTION_VALUE: Final[str] = "CLSID-ACTION-VALUE"
LD_ACTION_SETPOINT_6POS_ANTIFROST: Final[str] = "CLSID-ACTION-SETPOINT-6POS-ANTI-FROST"
LD_ACTION_SETPOINT_6POS_COMFORT: Final[str] = "CLSID-ACTION-SETPOINT-6POS-COMFORT"
LD_ACTION_SETPOINT_6POS_ECO: Final[str] = "CLSID-ACTION-SETPOINT-6POS-REDUCED"
LD_ACTION_SETPOINT_6POS_STOP: Final[str] = "CLSID-ACTION-SETPOINT-6POS-STOP"


# --- Devices types CLSIDs ---
LD_CLSID_DEVICE_TYPE_ACTUATOR_BUTTON: Final[str] = (
    # "Actionneur / Push contact"
    "CLSID-DEVC-A-PC"
)
LD_CLSID_DEVICE_TYPE_ACTUATOR_CLIMATECONTROL: Final[str] = (
    # "Actionneur / Contrôle Climatique" in French
    "CLSID-DEVC-A-CC"
)
LD_CLSID_DEVICE_TYPE_ACTUATOR_LIGHT: Final[str] = (
    # "Actionneur / Éclairage" in French
    "CLSID-DEVC-A-EC"
)
LD_CLSID_DEVICE_TYPE_ACTUATOR_MOTOR: Final[str] = (
    # "Actionneur / Moteur" in French
    "CLSID-DEVC-A-MO"
)
LD_CLSID_DEVICE_TYPE_SENSOR_ENERGY: Final[str] = (
    # "Mesure / Comptage Puissance" in French
    "CLSID-DEVC-M-CP"
)
LD_CLSID_DEVICE_TYPE_SENSOR_ENVIRONMENT: Final[str] = (
    # "Météo / Capteur Système" in French
    "CLSID-DEVC-M-CS"
)
LD_CLSID_DEVICE_TYPE_SENSOR: Final[str] = (
    # "Surveillance / Détecteur" in French
    "CLSID-DEVC-S-DT"
)
LD_CLSID_DEVICE_TYPE_SENSOR_ALARM: Final[str] = (
    # "Surveillance / Protection" in French
    "CLSID-DEVC-S-PR"
)


# --- Known models with device types families ---
LD_CLSID_DEVICE_TYPES: Final[dict[str, str]] = {
    "CLSID-DEVC-A-CC03": "Calybox 1020 WT/2020 WT / RF 6600 FP",  # Thermostat
    "CLSID-DEVC-A-EC01": "Tyxia 5610/5612/6610",  # On/off light
    "CLSID-DEVC-A-EC02": "Tyxia 4801/4811/6610",  # On/off light with timer
    "CLSID-DEVC-A-EC03": "Tyxia 4840/4850/5640/5650",  # Dimmable light
    "CLSID-DEVC-A-MO09": "Tymoov / Tyxia 5630/5730",  # Motor
    "CLSID-DEVC-A-PC07": "Tyxia 4620",  # Push button
    "CLSID-DEVC-M-CP13": "Calybox 2020 WT",  # Energy meter
    "CLSID-DEVC-M-CS15": "Tysense thermo",  # Temperature probe
    "CLSID-DEVC-M-CS22": "Tysense sun",  # Solar irradiance
    "CLSID-DEVC-S-DT01": "Tyxal+ DU",  # Universal detector
    "CLSID-DEVC-S-DT05": "Tyxal+ DF",  # Flood detector
    "CLSID-DEVC-S-DT08": "Tyxal+ DFR",  # Smoke detector
    "CLSID-DEVC-S-DT09": "Tyxal+ DMB / DMBD / DMBE / DMBV / DMDR / DME",  # Motion detector
    "CLSID-DEVC-S-DT10": "Tyxal+ DO / DOI / DOS / MDO",  # Opening detector
    "CLSID-DEVC-S-PR08": "Tyxal+ CS 8000",  # Alarm central unit
}

# Labels for various alarm faults. Some are probably missing (not found in tested devices).
LD_LABEL_FAULT_BATTERY: Final[str] = "{CLSID-LBL-XXD-FAULTS-BATTERY-CELL}"
LD_LABEL_FAULT_INHIBITION: Final[str] = "{CLSID-LBL-XXD-FAULTS-INHIBITION}"
LD_LABEL_FAULT_INTRUSION: Final[str] = "{CLSID-LBL-XXD-FAULTS-INTRUSION}"
LD_LABEL_FAULT_IP: Final[str] = "{CLSID-LBL-XXD-FAULTS-IP}"
LD_LABEL_FAULT_MONITORING: Final[str] = "{CLSID-LBL-XXD-FAULTS-MONITORING}"
LD_LABEL_FAULT_POWER: Final[str] = "{CLSID-LBL-XXD-FAULTS-POWER}"
LD_LABEL_FAULT_SELFPROTECTION: Final[str] = "{CLSID-LBL-XXD-FAULTS-SELF-PROTECTION}"


# Property constants for alarm features.
LD_PROP_ALARM_OPERATINGMODE: Final[str] = "CLSID-DEVC-PROP-ALARM-OPERATING-MODE"
LD_PROP_ALARM_ZONE_SW: Final[str] = "CLSID-DEVC-PROP-ALARM-ZONE-SW"
LD_PROP_ALARM_EVENTS_ACKNOWLEDGE: Final[str] = (
    "CLSID-DEVC-PROP-ALARM-ACKNOWLEDGE-EVENTS"
)
# Property constants for dimmers
LD_PROP_DIMMER_VA_POS: Final[str] = "CLSID-DEVC-PROP-DIMMER-VA-POS"
LD_PROP_DIMMER_SW: Final[str] = "CLSID-DEVC-PROP-DIMMER-SW"
# Property constants for motors (covers/blinds)
LD_PROP_MOTOR_UD: Final[str] = "CLSID-DEVC-PROP-MOTOR-UD"
LD_PROP_MOTOR_SW_STOP: Final[str] = "CLSID-DEVC-PROP-MOTOR-SW-STOP"
LD_PROP_MOTOR_VA_POS: Final[str] = "CLSID-DEVC-PROP-MOTOR-VA-POS"
# Property constants for thermostats
LD_PROP_THERMOSTAT_SETPOINT: Final[str] = (
    "CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-GENERALCONST"
)
LD_PROP_THERMOSTAT_SETPOINT_6POS: Final[str] = (
    # Thermostat setpoint 6 positions property
    "CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-SETPOINT-6POS"
)
LD_PROP_THERMOSTAT_STOP: Final[str] = (
    # Thermostat stop property
    "CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-STOP"
)
# Property constants for on/off devices (lights, sockets, etc.)
LD_PROP_TOR_SW: Final[str] = (
    # On/off device property ("Tout Ou Rien" in French)
    "CLSID-DEVC-PROP-TOR-SW"
)

# --- State CLSIDs ---
LD_STATE_ALARM_ALERT_DELAYED: Final[str] = (
    # Delayed alarm alert (true/false)
    "CLSID-STATE-ALARM-ALERTE-RETARDEE"
)
LD_STATE_ALARM_ALERT_SILENT: Final[str] = (
    # Silent alarm alert (true/false)
    "CLSID-STATE-ALARM-ALERTE-SILENCIEUSE"
)
LD_STATE_ALARM_INTRUSION: Final[str] = (
    # Alarm intrusion detected (true/false)
    "CLSID-STATE-ALARM-INTRUSION"
)
LD_STATE_ALARM_OPERATINGMODE: Final[str] = (
    # Alarm operating mode (LD_VALUE_ALARM_MODE_*)
    "CLSID-STATE-OPERATING-MODE"
)
LD_STATE_ALARM_WARN_BATTERY: Final[str] = (
    # One or more products with low battery (true/false)
    "CLSID-STATE-ALARM-WARN-BATTERY"
)
LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED: Final[str] = (
    # One or more unacknowledged alarm events (true/false)
    "CLSID-STATE-ALARM-WARN-UNACKNOWLEDGED-EVENTS"
)
LD_STATE_ALARM_WARN_INHIBITED: Final[str] = (
    # One or more products are inhibited (true/false)
    "CLSID-STATE-ALARM-WARN-INHIBITED-PRODUCTS"
)
LD_STATE_ALARM_WARN_MONITORING: Final[str] = (
    # Alarm remote monitoring unavailable (true/false)
    "CLSID-STATE-ALARM-WARN-MONITORING"
)
LD_STATE_ALARM_WARN_OPENENTRANCES: Final[str] = (
    # One or more protected entrances are open (true/false)
    "CLSID-STATE-ALARM-WARN-OPEN-ENTRANCES"
)
LD_STATE_ALARM_WARN_POWER: Final[str] = (
    # Mains power failure detected for main powered devices like transmitters (true/false)
    "CLSID-STATE-ALARM-WARN-POWER"
)
LD_STATE_ALARM_WARN_REMOVAL: Final[str] = (
    # A product is not responding on the X3D mesh but was not out of battery on last poll (true/false)
    "CLSID-STATE-ALARM-WARN-DOUBT-REMOVAL"
)
LD_STATE_ALARM_WARN_SIM: Final[str] = (
    # GSM alarm product with SIM card issue (true/false)
    "CLSID-STATE-ALARM-WARN-SIM"
)
LD_STATE_ALARM_WARN_TAMPERING: Final[str] = (
    # Product opened/tampered (true/false)
    "CLSID-STATE-ALARM-WARN-SELF-PROTECTION"
)
LD_STATE_ALARM_WARN_TECHNICALFAULT: Final[str] = (
    # Technical fault detected (true/false)
    "CLSID-STATE-ALARM-WARN-TECHNICAL-FAULTS"
)
LD_STATE_ALARM_WARN_REMOTE_COMMUNICATION: Final[str] = (
    # Alarm remote communication unavailable (true/false)
    "CLSID-STATE-ALARM-WARN-TELECOMMUNICATION"
)
LD_STATE_ALARM_WARN_REMOTE_MONITORING: Final[str] = (
    # Remote monitoring unavailable (true/false)
    "CLSID-STATE-ALARM-WARN-TELEMONITORING"
)
LD_STATE_ALARM_WARN_VIDEO_LINK: Final[str] = (
    # Video link unavailable (true/false)
    "CLSID-STATE-ALARM-WARN-VIDEO-LINK"
)
LD_STATE_ALARM_ZONESTATUS: Final[str] = (
    # Alarm zone status (true=on/off=false)
    "CLSID-STATE-ALARM-ZONESTATUS"
)
LD_STATE_FAULT_HEAT_TRANSFER: Final[str] = (
    # Thermostat: heat transfer fault detected (true/false)
    "CLSID-STATE-FAULT-HEAT-TRANSFER"
)
LD_STATE_AUTH_HEAT: Final[str] = (
    # Thermostat: authorized to heat (true=enabled/false=disabled)
    "CLSID-STATE-AUTH-HEAT"
)
LD_STATE_FAULT_TSOC: Final[str] = (
    # Thermostat: TSOC fault detected (true/false)
    "CLSID-STATE-FAULT-TSOC"
)
LD_STATE_FAULT_TSR: Final[str] = (
    # Thermostat: TSR fault detected (true/false)
    "CLSID-STATE-FAULT-TSR"
)
LD_STATE_FAULT_TSSC: Final[str] = (
    # Thermostat: TSSC fault detected (true/false)
    "CLSID-STATE-FAULT-TSSC"
)
LD_STATE_FLAG_ANTI_FROST: Final[str] = (
    # Thermostat: anti-frost mode (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-ANTI-FROST"
)
LD_STATE_FLAG_ENTRANCE: Final[str] = (
    # Thermostat: matching entrance opened, forcing anti-frost mode (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-ENTRANCE"
)
LD_STATE_FLAG_HEAT_TRANSFER: Final[str] = (
    # Thermostat: heat transfer (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-HEAT-TRANSFER"
)
LD_STATE_FLAG_LOAD_SHEDDING: Final[str] = (
    # Thermostat: load shedding mode (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-LOAD-SHEDDING"
)
LD_STATE_FLAG_PRESENCE: Final[str] = (
    # Thermostat: presence active (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-PRESENCE"
)
LD_STATE_FLAG_TEMPORARY: Final[str] = (
    # Thermostat: temporary mode (true=enabled/false=disabled)
    "CLSID-STATE-FLAG-TEMPORARY"
)
LD_STATE_LIGHT: Final[str] = (
    # Used both for lights and dimmers (true=on/off=false)
    "CLSID-STATE-LIGHT"
)
LD_STATE_POSITION_PERCENTAGE: Final[str] = (
    # Used both for dimmers and covers (numeric value 0-100)
    "CLSID-STATE-POSITION-PERCENTAGE"
)
LD_STATE_SETPOINT_6POS: Final[str] = (
    # Thermostat mode (LD_VALUE_THERMOSTAT_6POS_*)
    # Delta Dore devices seems to handle only 4 of the 6 positions
    "CLSID-STATE-SETPOINT-6POS"
)
LD_STATE_SOCKET: Final[str] = (
    # Same as on/off light but is identified as a socket (true=on/off=false)
    "CLSID-STATE-SOCKET"
)
LD_STATE_TEMPERATURE_AMBIANT: Final[str] = (
    # Ambiant current temperature provided by sensor (numeric value with step of 0.5 °C)
    "CLSID-STATE-AMBIANT-TEMPERATURE"
)
LD_STATE_TEMPERATURE_SETPOINT: Final[str] = (
    # Thermostat target temperature (numeric value with step of 0.5 °C)
    "CLSID-STATE-SETPOINT-TEMPERATURE"
)
LD_STATE_THERMOSTAT: Final[str] = (
    # Ambient current temperature provided by thermostat (numeric value with step of 0.1 °C)
    "CLSID-STATE-THERMOSTAT"
)
LD_STATE_TRIGGERED: Final[str] = (
    # Triggered sensor - Note: spelling as returned by Lifedomus XML
    "CLSID-STATE-TRIGGERRED"
)
LD_STATE_VALUE: Final[str] = (
    # Generic numeric value state
    "CLSID-STATE-VALUE"
)

# --- Known values for properties/states ---
# Values for alarm operating modes.
LD_VALUE_ALARM_MODE_ARMED_FULL: Final[str] = "FULL_ARMING"
LD_VALUE_ALARM_MODE_ARMED_PARTIAL: Final[str] = "PARTIAL_ARMING"
LD_VALUE_ALARM_MODE_MAINTENANCE: Final[str] = "MAINTENANCE"
LD_VALUE_ALARM_MODE_STOP: Final[str] = "STOP"

# Values in degrees Celsius for thermostat setpoints.
LD_VALUE_THERMOSTAT_MIN: Final[float] = 5.0
LD_VALUE_THERMOSTAT_MAX: Final[float] = 30.0
LD_VALUE_THERMOSTAT_STEP: Final[float] = 0.5
# Values for thermostat 6 positions (only 4 are used in practice).
LD_VALUE_THERMOSTAT_6POS_ANTIFROST: Final[str] = "ANTI_FROST"
LD_VALUE_THERMOSTAT_6POS_COMFORT: Final[str] = "COMFORT"
LD_VALUE_THERMOSTAT_6POS_ECO: Final[str] = "REDUCED"
LD_VALUE_THERMOSTAT_6POS_STOP: Final[str] = "STOP"
