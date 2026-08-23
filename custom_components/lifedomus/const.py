"""Lifedomus integration constants.

This module contains integration-wide constants such as domain name,
configuration keys, default values, and Lifedomus-specific CLSIDs for
devices, actions, properties, and states.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
import re
from typing import Final

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

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
LD_DEFAULT_ITEMS_LIMIT: Final[int] = 50

# SOAP namespaces used when building/parsing envelopes. The envelope namespace is
# defined by the SOAP/1.1 envelope schema and is used on Body parsing.
SOAP_NAMESPACE: Final = "http://schemas.xmlsoap.org/soap/envelope/"

PATTERN_DEVICE_KEY: Final[re.Pattern[str]] = re.compile(r"^DEVC_[0-9]{35}$")
PATTERN_SESSION_KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{40}$")
PATTERN_SITE_KEY: Final[re.Pattern[str]] = re.compile(r"^SITE_[0-9]{35}$")
PATTERN_USER_KEY: Final[re.Pattern[str]] = re.compile(r"^USER_[0-9]{35}$")

# Day of week mapping for Lifedomus XML responses (1=Sunday, 7=Saturday)
LD_DAY_OF_WEEK_MAPPING: Final[dict[int, str]] = {
    1: "sunday",
    2: "monday",
    3: "tuesday",
    4: "wednesday",
    5: "thursday",
    6: "friday",
    7: "saturday",
}

# Month name mapping for date parsing from Lifedomus XML responses
LD_MONTH_MAPPING: Final[dict[str, int]] = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

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


# --- Device categories and models recognized by the gateway ---
# Note that CLSID definitions returned by the gateway are sometimes derived from French
# (e.g. "ÉClairage" for lighting, "Entrée" for input, "Traitement de l’Eau" for water
# treatment).


class LdDeviceCategory(StrEnum):
    """Device category CLSIDs addressed by Mobile/GetDevicesFromCatg.

    Each device type CLSID is prefixed by its category CLSID (e.g. type
    'CLSID-DEVC-A-EC01' belongs to category 'CLSID-DEVC-A-EC').
    """

    # Actuator / Audio/Video
    ACTUATOR_AUDIOVIDEO = "CLSID-DEVC-A-AV"
    # Actuator / Climate control
    ACTUATOR_CLIMATECONTROL = "CLSID-DEVC-A-CC"
    # Actuator / "Éclairage" in French
    ACTUATOR_LIGHT = "CLSID-DEVC-A-EC"
    # Actuator / Motor
    ACTUATOR_MOTOR = "CLSID-DEVC-A-MO"
    # Actuator / Push contact
    ACTUATOR_REMOTE_CONTROL = "CLSID-DEVC-A-PC"
    # Actuator / "Traitement de l’eau" in French
    ACTUATOR_WATER_TREATMENT = "CLSID-DEVC-A-TE"
    # Actuator / Universal
    ACTUATOR_GENERIC = "CLSID-DEVC-A-UN"
    # Actuator / Ventilation
    ACTUATOR_VENTILATION = "CLSID-DEVC-A-VE"
    # Automation ("Entrée" in French) / Input/Output
    AUTOMATION_IO = "CLSID-DEVC-E-IO"
    # Automation ("Entrée" in French) / Scenes
    AUTOMATION_SCENES = "CLSID-DEVC-E-SC"
    # Measure / Calendar and clock
    MEASURE_CALENDAR_AND_CLOCK = "CLSID-DEVC-M-CC"
    # Measure / Consumption
    MEASURE_CONSUMPTION = "CLSID-DEVC-M-CP"
    # Measure / "Capteur Sonde" in French
    MEASURE_SENSOR = "CLSID-DEVC-M-CS"
    # Surveillance / Detector
    SURVEILLANCE_DETECTOR = "CLSID-DEVC-S-DT"
    # Surveillance / Logic comparison
    SURVEILLANCE_LOGICCOMPARISON = "CLSID-DEVC-S-LC"
    # Surveillance / Protection
    SURVEILLANCE_PROTECTION = "CLSID-DEVC-S-PR"


# Device type CLSIDs and their human-readable model names, nested per category.
# This is the single source of truth for device models.
LD_CLSID_DEVICE_CATEGORIES: Final[dict[LdDeviceCategory, dict[str, str]]] = {
    LdDeviceCategory.ACTUATOR_AUDIOVIDEO: {
        "CLSID-DEVC-A-AV04": "NuVo multi-room tuner",
        "CLSID-DEVC-A-AV05": "NuVo multi-room audio amplifier",
        "CLSID-DEVC-A-AV07": "NuVo Music Port",
        "CLSID-DEVC-A-AV08": "DVD Player",
        "CLSID-DEVC-A-AV09": "Television",
        "CLSID-DEVC-A-AV10": "Satellite",
        "CLSID-DEVC-A-AV11": "Receiver",
        "CLSID-DEVC-A-AV12": "Tuner",
        "CLSID-DEVC-A-AV13": "Video projector",
        "CLSID-DEVC-A-AV14": "Dune HD TV-101",
        "CLSID-DEVC-A-AV15": "Sonos media player",
        "CLSID-DEVC-A-AV16": "Popcorn media player",
        "CLSID-DEVC-A-AV20": "Generic audio/video device",
        "CLSID-DEVC-A-AV21": "Kodi media player",
        "CLSID-DEVC-A-AV22": "Smart television",
        "CLSID-DEVC-A-AV23": "Legrand multi-room audio",
        "CLSID-DEVC-A-AV24": "Plex media player",
        "CLSID-DEVC-A-AV25": "Multi-room audio device",
    },
    LdDeviceCategory.ACTUATOR_CLIMATECONTROL: {
        "CLSID-DEVC-A-CC03": "Room thermostat",
        "CLSID-DEVC-A-CC05": "Temperature control unit",
        "CLSID-DEVC-A-CC06": "Heating device",
        "CLSID-DEVC-A-CC07": "Heated towel rail",
        "CLSID-DEVC-A-CC08": "Furnace",
        "CLSID-DEVC-A-CC09": "HVAC PID Controller",
        "CLSID-DEVC-A-CC10": "Generic climate control device",
        "CLSID-DEVC-A-CC11": "Siemens room thermostat",
        "CLSID-DEVC-A-CC12": "Air conditioning unit",
        "CLSID-DEVC-A-CC13": "Unknown climate control device (type 13)",
        "CLSID-DEVC-A-CC14": "Hot water tank",
        "CLSID-DEVC-A-CC15": "Floor heating",
        "CLSID-DEVC-A-CC16": "Virtual thermostat",
    },
    LdDeviceCategory.ACTUATOR_LIGHT: {
        "CLSID-DEVC-A-EC01": "Light",
        "CLSID-DEVC-A-EC02": "Electrical socket",
        "CLSID-DEVC-A-EC03": "Dimmer (230V)",
        "CLSID-DEVC-A-EC04": "Dimmer (1-10V)",
        "CLSID-DEVC-A-EC05": "RGB LED",
        "CLSID-DEVC-A-EC06": "Switch",
        "CLSID-DEVC-A-EC07": "Generic light device",
        "CLSID-DEVC-A-EC08": "Philips Hue light",
        "CLSID-DEVC-A-EC09": "Generic switch",
        "CLSID-DEVC-A-EC10": "Generic toggle button",
    },
    LdDeviceCategory.ACTUATOR_MOTOR: {
        "CLSID-DEVC-A-MO01": "Cinema Screen",
        "CLSID-DEVC-A-MO04": "Electric gate",
        "CLSID-DEVC-A-MO05": "Automatic door",
        "CLSID-DEVC-A-MO06": "Garage door",
        "CLSID-DEVC-A-MO07": "Awning",
        "CLSID-DEVC-A-MO08": "Pool cover",
        "CLSID-DEVC-A-MO09": "Roller shutter / blind",
        "CLSID-DEVC-A-MO10": "Roller blind",
        "CLSID-DEVC-A-MO11": "Solenoid",
        "CLSID-DEVC-A-MO12": "Skylight",
        "CLSID-DEVC-A-MO13": "Horizontal roller blind",
        "CLSID-DEVC-A-MO14": "Vertical roller blind",
        "CLSID-DEVC-A-MO15": '"Against ride" motor',
        "CLSID-DEVC-A-MO16": "Swing shutter",
        "CLSID-DEVC-A-MO17": "Generic motor device",
        "CLSID-DEVC-A-MO18": "Lock",
        "CLSID-DEVC-A-MO19": "Smart Intego lock",
    },
    LdDeviceCategory.ACTUATOR_REMOTE_CONTROL: {
        "CLSID-DEVC-A-PC01": "Infrared relay",
        "CLSID-DEVC-A-PC06": "Hestia Varuna",
        "CLSID-DEVC-A-PC07": "Remote control",
        "CLSID-DEVC-A-PC08": "Remote ON button",
        "CLSID-DEVC-A-PC09": "Remote OFF button",
        "CLSID-DEVC-A-PC10": "Remote toggle button",
        "CLSID-DEVC-A-PC11": "Generic push button",
        "CLSID-DEVC-A-PC12": "IRTrans remote",
        "CLSID-DEVC-A-PC13": "Unknown command device (type PC13)",
        "CLSID-DEVC-A-PC14": "Unknown command device (type PC14)",
        "CLSID-DEVC-A-PC15": "Unknown command device (type PC15)",
        "CLSID-DEVC-A-PC16": "Unknown command device (type PC16)",
    },
    LdDeviceCategory.ACTUATOR_WATER_TREATMENT: {
        "CLSID-DEVC-A-TE01": "Pool filtration pump",
        "CLSID-DEVC-A-TE02": "Pool electrolyzer",
        "CLSID-DEVC-A-TE03": "Pool pH regulator",
        "CLSID-DEVC-A-TE04": "Generic water treatment device",
    },
    LdDeviceCategory.ACTUATOR_GENERIC: {
        "CLSID-DEVC-A-UN01": "Generic universal actuator",
        "CLSID-DEVC-A-UN02": "Generic listening device",
        "CLSID-DEVC-A-UN03": "Unknown generic device (type UN03)",
        "CLSID-DEVC-A-UN04": "HomeKit bridge",
    },
    LdDeviceCategory.ACTUATOR_VENTILATION: {
        "CLSID-DEVC-A-VE03": "Helios mechanical extract ventilation",
        "CLSID-DEVC-A-VE04": "Mechanical extract ventilation",
        "CLSID-DEVC-A-VE05": "Dehumidifier",
        "CLSID-DEVC-A-VE06": "Humidity controller",
        "CLSID-DEVC-A-VE07": "Generic ventilation device",
    },
    LdDeviceCategory.AUTOMATION_IO: {
        "CLSID-DEVC-E-IO-AI": "Analog input",
        "CLSID-DEVC-E-IO-ALM": "Alarm input",
        "CLSID-DEVC-E-IO-AO": "Analog output",
        "CLSID-DEVC-E-IO-CPT": "Counter pulse",
        "CLSID-DEVC-E-IO-DI": "Digital input",
        "CLSID-DEVC-E-IO-DO": "Digital output",
    },
    LdDeviceCategory.AUTOMATION_SCENES: {
        "CLSID-DEVC-E-SC01": "Scene input",
        "CLSID-DEVC-E-SC03": "Unknown scene input",
        "CLSID-DEVC-E-SC04": "Mobile scene input",
    },
    LdDeviceCategory.MEASURE_CALENDAR_AND_CLOCK: {
        "CLSID-DEVC-M-CC01": "Date",
        "CLSID-DEVC-M-CC02": "Time",
        "CLSID-DEVC-M-CC03": "Clock station",
    },
    LdDeviceCategory.MEASURE_CONSUMPTION: {
        "CLSID-DEVC-M-CP03": "Gas meter",
        "CLSID-DEVC-M-CP04": "Water meter",
        "CLSID-DEVC-M-CP05": "Fuel meter",
        "CLSID-DEVC-M-CP06": "Liquid meter",
        "CLSID-DEVC-M-CP07": "Electricity meter",
        "CLSID-DEVC-M-CP08": "Electrical power meter",
        "CLSID-DEVC-M-CP09": "Amperage meter",
        "CLSID-DEVC-M-CP10": "Voltage meter",
        "CLSID-DEVC-M-CP11": "Electrical frequency meter",
        "CLSID-DEVC-M-CP12": "Generic energy meter",
        "CLSID-DEVC-M-CP13": "Heating manager",
        "CLSID-DEVC-M-CP14": "TyWatt 5200",
        "CLSID-DEVC-M-CP15": "Teleinfo Receiver",
    },
    LdDeviceCategory.MEASURE_SENSOR: {
        "CLSID-DEVC-M-CS01": "Anemometer",
        "CLSID-DEVC-M-CS02": "Air density sensor",
        "CLSID-DEVC-M-CS03": "Enthalpy sensor",
        "CLSID-DEVC-M-CS04": "Air humidity sensor",
        "CLSID-DEVC-M-CS05": "Soil humidity sensor",
        "CLSID-DEVC-M-CS06": "Brightness sensor",
        "CLSID-DEVC-M-CS07": "Unknown sensor (type CS07)",
        "CLSID-DEVC-M-CS08": "Noise level sensor",
        "CLSID-DEVC-M-CS09": "CO₂ sensor",
        "CLSID-DEVC-M-CS10": "Chlorine level sensor",
        "CLSID-DEVC-M-CS11": "pH sensor",
        "CLSID-DEVC-M-CS12": "Filling level sensor",
        "CLSID-DEVC-M-CS13": "Rainfall sensor",
        "CLSID-DEVC-M-CS14": "Atmospheric pressure sensor",
        "CLSID-DEVC-M-CS15": "Temperature sensor",
        "CLSID-DEVC-M-CS16": "Sun azimuth",
        "CLSID-DEVC-M-CS17": "Sun elevation",
        "CLSID-DEVC-M-CS18": "Pulse counter",
        "CLSID-DEVC-M-CS19": "Netatmo central device",
        "CLSID-DEVC-M-CS20": "Netatmo module device",
        "CLSID-DEVC-M-CS21": "Generic sensor",
        "CLSID-DEVC-M-CS22": "Irradiance sensor",
        "CLSID-DEVC-M-CS23": "VOC sensor",
        "CLSID-DEVC-M-CS24": "Ozone sensor",
        "CLSID-DEVC-M-CS25": "Particles sensor",
        "CLSID-DEVC-M-CS26": "Radon sensor",
        "CLSID-DEVC-M-CS27": "Unknown meter/sensor (type CS27)",
    },
    LdDeviceCategory.SURVEILLANCE_DETECTOR: {
        "CLSID-DEVC-S-DT01": "Universal detector",
        "CLSID-DEVC-S-DT02": "Closing detector",
        "CLSID-DEVC-S-DT03": "Bottom door detector",
        "CLSID-DEVC-S-DT04": "Gas leak detector",
        "CLSID-DEVC-S-DT05": "Water leak detector",
        "CLSID-DEVC-S-DT06": "Fuel leak detector",
        "CLSID-DEVC-S-DT07": "Liquid leak detector",
        "CLSID-DEVC-S-DT08": "Smoke / fire detector",
        "CLSID-DEVC-S-DT09": "Motion detector",
        "CLSID-DEVC-S-DT10": "Opening detector",
        "CLSID-DEVC-S-DT11": "Presence detector",
        "CLSID-DEVC-S-DT12": "Fall detector",
        "CLSID-DEVC-S-DT13": "Emergency call detector",
        "CLSID-DEVC-S-DT14": "Rain detector",
        "CLSID-DEVC-S-DT15": "Snow detector",
        "CLSID-DEVC-S-DT16": "Generic detector",
        "CLSID-DEVC-S-DT17": "Carbon monoxide detector",
        "CLSID-DEVC-S-DT18": "Rain/snow detector",
        "CLSID-DEVC-S-DT19": "Window handle",
        "CLSID-DEVC-S-DT20": "Generic flag (type DT20)",
    },
    LdDeviceCategory.SURVEILLANCE_LOGICCOMPARISON: {
        "CLSID-DEVC-S-LC02": "Binary input",
        "CLSID-DEVC-S-LC03": "Binary input (NOT)",
        "CLSID-DEVC-S-LC04": "Binary inputs (AND)",
        "CLSID-DEVC-S-LC05": "Binary inputs (NAND)",
        "CLSID-DEVC-S-LC06": "Binary inputs (OR)",
        "CLSID-DEVC-S-LC07": "Binary inputs (NOR)",
        "CLSID-DEVC-S-LC08": "Binary inputs (XOR)",
    },
    LdDeviceCategory.SURVEILLANCE_PROTECTION: {
        "CLSID-DEVC-S-PR02": "KNX (EIS) status messages",
        "CLSID-DEVC-S-PR04": "Burglar alarm",
        "CLSID-DEVC-S-PR05": "Generic security device",
        "CLSID-DEVC-S-PR06": "Keypad",
        "CLSID-DEVC-S-PR07": "KNX alarm",
        "CLSID-DEVC-S-PR08": "Tyxal+ Alarm",
        "CLSID-DEVC-S-PR09": "Unknown protection device (type PR09)",
        "CLSID-DEVC-S-PR10": "Unknown protection device (type PR10)",
        "CLSID-DEVC-S-PR11": "Unknown protection device (type PR11)",
    },
}

# Labels for various alarm faults. Some are probably missing (not found in tested devices).
LD_LABEL_FAULT_BATTERY: Final[str] = "{CLSID-LBL-XXD-FAULTS-BATTERY-CELL}"
LD_LABEL_FAULT_INHIBITION: Final[str] = "{CLSID-LBL-XXD-FAULTS-INHIBITION}"
LD_LABEL_FAULT_INTRUSION: Final[str] = "{CLSID-LBL-XXD-FAULTS-INTRUSION}"
LD_LABEL_FAULT_IP: Final[str] = "{CLSID-LBL-XXD-FAULTS-IP}"
LD_LABEL_FAULT_MONITORING: Final[str] = "{CLSID-LBL-XXD-FAULTS-MONITORING}"
LD_LABEL_FAULT_POWER: Final[str] = "{CLSID-LBL-XXD-FAULTS-POWER}"
LD_LABEL_FAULT_SELFPROTECTION: Final[str] = "{CLSID-LBL-XXD-FAULTS-SELF-PROTECTION}"
LD_LABEL_FAULT_TECHNICAL: Final[str] = "{CLSID-LBL-XXD-FAULTS-TECHNICAL}"

LD_LABEL_HISTORY_FIRE_FAULT: Final[str] = "{CLSID-LBL-XXD-HIST-FIRE-FAULT}"
LD_LABEL_HISTORY_INTRUSION_ALERT: Final[str] = "{CLSID-LBL-XXD-HIST-INTRUSION-ALERT}"
LD_LABEL_HISTORY_TECHNICAL_FAULT: Final[str] = "{CLSID-LBL-XXD-HIST-TECHNICAL-FAULT}"

TYXAL_LABEL_DEVICE_BASEMENT: Final[str] = "{CLSID-LBL-TYXAL-DEVCLABEL-BASEMENT}"
TYXAL_LABEL_DEVICE_FLOOR: Final[str] = "{CLSID-LBL-TYXAL-DEVCLABEL-FLOOR}"
TYXAL_LABEL_DEVICE_GARAGE: Final[str] = "{CLSID-LBL-TYXAL-DEVCLABEL-GARAGE}"
TYXAL_LABEL_DEVICE_KITCHEN: Final[str] = "{CLSID-LBL-TYXAL-DEVCLABEL-KITCHEN}"
TYXAL_LABEL_DEVICE_VERANDA: Final[str] = "{CLSID-LBL-TYXAL-DEVCLABEL-VERANDA}"

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
LD_STATE_FLOOR_HEATING: Final[str] = (
    # Floor heating running state (true=heating/false=idle)
    "CLSID-STATE-DEVC-FLOOR-HEATING"
)
LD_STATE_LIGHT: Final[str] = (
    # Used both for lights and dimmers (true=on/off=false)
    "CLSID-STATE-LIGHT"
)
LD_STATE_POSITION_PERCENTAGE: Final[str] = (
    # Used both for dimmers and covers (numeric value 0-100)
    "CLSID-STATE-POSITION-PERCENTAGE"
)
LD_STATE_REGULATION_ON: Final[str] = (
    # Virtual thermostat regulation enabled (true/false)
    "CLSID-STATE-REGULATION-ON"
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
LD_STATE_TEMPERATURE: Final[str] = (
    # Ambiant current temperature; variant of CLSID-STATE-AMBIANT-TEMPERATURE
    # reported by some gateway versions and by virtual thermostats
    "CLSID-STATE-TEMPERATURE"
)
LD_STATE_TEMPERATURE_AMBIANT: Final[str] = (
    # Ambiant current temperature provided by sensor (numeric value with step of 0.5 °C)
    "CLSID-STATE-AMBIANT-TEMPERATURE"
)
LD_STATE_TEMPERATURE_COMFORT: Final[str] = (
    # Thermostat target temperature; variant of CLSID-STATE-SETPOINT-TEMPERATURE
    # reported by some gateway versions and by virtual thermostats
    "CLSID-STATE-COMFORT-TEMPERATURE"
)
LD_STATE_TEMPERATURE_SETPOINT: Final[str] = (
    # Thermostat target temperature (numeric value with step of 0.5 °C)
    "CLSID-STATE-SETPOINT-TEMPERATURE"
)
LD_STATE_THERMOSTAT: Final[str] = (
    # Thermostat working state (true=on/off=false)
    "CLSID-STATE-THERMOSTAT"
)
LD_STATE_THERMOSTAT_THERM_MODE: Final[str] = (
    # Virtual thermostat thermal mode (raw text value)
    "CLSID-STATE-THERMOSTAT-THERM-MODE"
)
LD_STATE_TRIGGERED: Final[str] = (
    # Triggered sensor - Note: spelling as returned by Lifedomus XML
    "CLSID-STATE-TRIGGERRED"
)
LD_STATE_VALUE: Final[str] = (
    # Generic numeric value state
    "CLSID-STATE-VALUE"
)


@dataclass(frozen=True, slots=True)
class SystemVariableConfig:
    """Configuration for a Lifedomus system variable."""

    clsid: str
    value_type: type[bool | date | datetime | int | float | str]
    translation_key: str
    icon: str
    unit: str | None = None
    sensor_class: (
        SensorDeviceClass | SensorStateClass | BinarySensorDeviceClass | None
    ) = None
    enabled: bool = True


# --- System variables CLSIDs ---
LD_SYSTEM_VAR_DATE: Final[str] = "CLSID-SYSTEM-DATE"
LD_SYSTEM_VAR_DAY_OF_MONTH: Final[str] = "CLSID-SYSTEM-DAY-OF-MONTH"
LD_SYSTEM_VAR_DAY_OF_WEEK: Final[str] = "CLSID-SYSTEM-DAY-OF-WEEK"
LD_SYSTEM_VAR_MONTH: Final[str] = "CLSID-SYSTEM-MONTH"
LD_SYSTEM_VAR_SOLAR_ELEVATION: Final[str] = "CLSID-SYSTEM-SOLAR-ELEVATION"
LD_SYSTEM_VAR_SOLAR_AZIMUTH: Final[str] = "CLSID-SYSTEM-SOLAR-AZIMUTH"
LD_SYSTEM_VAR_TIME: Final[str] = "CLSID-SYSTEM-TIME"
LD_SYSTEM_VAR_TIME_SOLARNOON: Final[str] = "CLSID-SYSTEM-TIME-SOLARNOON"
LD_SYSTEM_VAR_TIME_SUNLIGHT: Final[str] = "CLSID-SYSTEM-TIME-SUNLIGHT"
LD_SYSTEM_VAR_TIME_SUNRISE: Final[str] = "CLSID-SYSTEM-TIME-SUNRISE"
LD_SYSTEM_VAR_TIME_SUNSET: Final[str] = "CLSID-SYSTEM-TIME-SUNSET"
LD_SYSTEM_VAR_UPTIME: Final[str] = "CLSID-SYSTEM-NB-OF-MIN-SINCE-START-UP"
LD_SYSTEM_VAR_WEB_STATUS: Final[str] = "CLSID-SYSTEM-WEB"
LD_SYSTEM_VAR_YEAR: Final[str] = "CLSID-SYSTEM-YEAR"

# System variables configuration mapping
LD_CLSID_SYSTEM_VARIABLES: Final[dict[str, SystemVariableConfig]] = {
    LD_SYSTEM_VAR_DATE: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_DATE,
        value_type=date,
        translation_key="system_var_date",
        icon="mdi:calendar-today",
        unit=None,
        sensor_class=SensorDeviceClass.DATE,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
    LD_SYSTEM_VAR_DAY_OF_MONTH: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_DAY_OF_MONTH,
        value_type=int,
        translation_key="system_var_day_of_month",
        icon="mdi:calendar-today",
        sensor_class=None,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
    LD_SYSTEM_VAR_DAY_OF_WEEK: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_DAY_OF_WEEK,
        value_type=str,
        translation_key="system_var_day_of_week",
        icon="mdi:calendar-today",
        sensor_class=None,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
    LD_SYSTEM_VAR_MONTH: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_MONTH,
        value_type=int,
        translation_key="system_var_month",
        icon="mdi:calendar-month",
        sensor_class=None,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
    LD_SYSTEM_VAR_SOLAR_ELEVATION: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_SOLAR_ELEVATION,
        value_type=float,
        translation_key="system_var_solar_elevation",
        icon="mdi:sun-angle",
        unit="°",
        sensor_class=SensorStateClass.MEASUREMENT,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_SOLAR_AZIMUTH: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_SOLAR_AZIMUTH,
        value_type=float,
        translation_key="system_var_solar_azimuth",
        icon="mdi:sun-compass",
        unit="°",
        sensor_class=SensorStateClass.MEASUREMENT,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_TIME: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_TIME,
        value_type=str,
        translation_key="system_var_time",
        icon="mdi:clock-outline",
        sensor_class=None,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
    LD_SYSTEM_VAR_TIME_SOLARNOON: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_TIME_SOLARNOON,
        value_type=datetime,
        translation_key="system_var_time_solarnoon",
        icon="mdi:sun-clock",
        sensor_class=None,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_TIME_SUNLIGHT: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_TIME_SUNLIGHT,
        value_type=str,  # HH:MM string format
        translation_key="system_var_time_sunlight",
        icon="mdi:sun-clock",
        sensor_class=SensorDeviceClass.DURATION,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_TIME_SUNRISE: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_TIME_SUNRISE,
        value_type=datetime,
        translation_key="system_var_time_sunrise",
        icon="mdi:weather-sunset-up",
        sensor_class=None,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_TIME_SUNSET: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_TIME_SUNSET,
        value_type=datetime,
        translation_key="system_var_time_sunset",
        icon="mdi:weather-sunset-down",
        sensor_class=None,
        enabled=False,  # Disabled by default as Home Assistant sun integration is already providing this
    ),
    LD_SYSTEM_VAR_UPTIME: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_UPTIME,
        value_type=int,
        translation_key="system_var_uptime",
        icon="mdi:timer-outline",
        unit="min",
        sensor_class=SensorStateClass.TOTAL_INCREASING,
        enabled=True,
    ),
    LD_SYSTEM_VAR_WEB_STATUS: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_WEB_STATUS,
        value_type=bool,
        translation_key="system_var_web_status",
        icon="mdi:web",
        sensor_class=BinarySensorDeviceClass.CONNECTIVITY,
        enabled=True,
    ),
    LD_SYSTEM_VAR_YEAR: SystemVariableConfig(
        clsid=LD_SYSTEM_VAR_YEAR,
        value_type=int,
        translation_key="system_var_year",
        icon="mdi:calendar",
        sensor_class=None,
        enabled=False,  # Disabled by default as it's not very useful as a sensor
    ),
}

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
