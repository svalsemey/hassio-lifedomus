"""Lifedomus integration constants.

This module contains integration-wide constants such as domain name,
configuration keys, default values, and Lifedomus-specific CLSIDs for
devices, actions, properties, and states.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
    # "Météo / Capteur Sonde" in French
    "CLSID-DEVC-M-CS"
)
LD_CLSID_DEVICE_TYPE_SENSOR: Final[str] = (
    # "Sécurité / Détecteur" in French
    "CLSID-DEVC-S-DT"
)
LD_CLSID_DEVICE_TYPE_SENSOR_ALARM: Final[str] = (
    # "Sécurité / Protection" in French
    "CLSID-DEVC-S-PR"
)


# --- Models with device types families recognized by the gateway ---
# Note that CLSIDs definitions returned by the gateway are mostly derived from French
# (e.g. "ÉClairage" for lighting, "MOteur" for motor, "DéTecteur" for detector, etc.)
# Some of them are not known for now, as I never had the opportunity to check with a
# gateway that has them configured.
LD_CLSID_DEVICE_TYPES: Final[dict[str, str]] = {
    "CLSID-DEVC-A-AV04": "Unknown actuator (type AV04)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV05": "Unknown actuator (type AV05)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV07": "Unknown actuator (type AV07)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV08": "Unknown actuator (type AV08)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV09": "Unknown actuator (type AV09)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV10": "Unknown actuator (type AV10)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV11": "Unknown actuator (type AV11)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV12": "Unknown actuator (type AV12)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV13": "Unknown actuator (type AV13)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV14": "Unknown actuator (type AV14)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV15": "Unknown actuator (type AV15)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV16": "Unknown actuator (type AV16)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV20": "Unknown actuator (type AV20)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV21": "Unknown actuator (type AV21)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV22": "Unknown actuator (type AV22)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV23": "Unknown actuator (type AV23)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV24": "Unknown actuator (type AV24)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-AV25": "Unknown actuator (type AV25)",                    # Actuator ("Audio/Video"?)
    "CLSID-DEVC-A-CC03": "Calybox 1020 WT/2020 WT / RF 6600 FP",            # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC05": "Unknown climate control device (type 05)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC06": "Unknown climate control device (type 06)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC07": "Unknown climate control device (type 07)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC08": "Unknown climate control device (type 08)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC09": "Unknown climate control device (type 09)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC10": "Unknown climate control device (type 10)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC11": "Siemens thermostat",                              # Actuator ("Climate Control"): thermostat
    "CLSID-DEVC-A-CC12": "Unknown climate control device (type 12)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC13": "Unknown climate control device (type 13)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC14": "Unknown climate control device (type 14)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC15": "Unknown climate control device (type 15)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-CC16": "Unknown climate control device (type 16)",        # Actuator ("Climate Control")
    "CLSID-DEVC-A-EC01": "Tyxia 5610/5612/6610",                            # Actuator ("ÉClairage"): On/off light
    "CLSID-DEVC-A-EC02": "Tyxia 4801/4811/6610",                            # Actuator ("ÉClairage"): On/off light with timer
    "CLSID-DEVC-A-EC03": "Tyxia 4840/4850/5640/5650",                       # Actuator ("ÉClairage"): Dimmable light
    "CLSID-DEVC-A-EC04": "Unknown light device (type 04)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC05": "Unknown light device (type 05)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC06": "Unknown light device (type 06)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC07": "Unknown light device (type 07)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC08": "Unknown light device (type 08)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC09": "Unknown light device (type 09)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-EC10": "Unknown light device (type 10)",                  # Actuator ("ÉClairage"): Unknown light device
    "CLSID-DEVC-A-MO01": "Unknown motor (type 01)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO04": "Unknown motor (type 04)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO05": "Unknown motor (type 05)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO06": "Unknown motor (type 06)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO07": "Unknown motor (type 07)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO08": "Unknown motor (type 08)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO09": "Tymoov / Tyxia 5630/5730",                        # Actuator ("MOtor")
    "CLSID-DEVC-A-MO10": "Unknown motor (type 10)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO11": "Unknown motor (type 11)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO12": "Unknown motor (type 12)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO13": "Unknown motor (type 13)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO14": "Unknown motor (type 14)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO15": "Unknown motor (type 15)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO16": "Unknown motor (type 16)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO17": "Unknown motor (type 17)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO18": "Unknown motor (type 18)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-MO19": "Unknown motor (type 19)",                         # Actuator ("MOtor")
    "CLSID-DEVC-A-PC01": "Unknown command device",                          # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC06": "Unknown command device",                          # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC07": "Tyxia 4620",                                      # Actuator ("Push Circuit") (on/off)
    "CLSID-DEVC-A-PC08": "Unknown command device (type 08)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC09": "Unknown command device (type 09)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC10": "Unknown command device (type 10)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC11": "Unknown command device (type 11)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC12": "IRTRANS Remote receiver",                         # Actuator ("Push Circuit"): Infrared remote receiver
    "CLSID-DEVC-A-PC13": "Unknown command device (type 13)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC14": "Unknown command device (type 14)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC15": "Unknown command device (type 15)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-PC16": "Unknown command device (type 16)",                # Actuator ("Push Circuit")
    "CLSID-DEVC-A-TE01": "Unknown actuator (type TE01)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-TE02": "Unknown actuator (type TE02)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-TE03": "Unknown actuator (type TE03)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-TE04": "Unknown actuator (type TE04)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-UN01": "Unknown actuator (type UN01)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-UN02": "Unknown actuator (type UN02)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-UN03": "Unknown actuator (type UN03)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-UN04": "Unknown actuator (type UN04)",                    # Actuator: Unknown device type
    "CLSID-DEVC-A-VE03": "Unknown actuator (type VE03)",                    # Actuator ("VEntilation" ?)
    "CLSID-DEVC-A-VE04": "Unknown actuator (type VE04)",                    # Actuator ("VEntilation" ?)
    "CLSID-DEVC-A-VE05": "Unknown actuator (type VE05)",                    # Actuator ("VEntilation" ?)
    "CLSID-DEVC-A-VE06": "Unknown actuator (type VE06)",                    # Actuator ("VEntilation" ?)
    "CLSID-DEVC-A-VE07": "Unknown actuator (type VE07)",                    # Actuator ("VEntilation" ?)
    "CLSID-DEVC-E-IO-AI": "Unknown I/O device (analog input)",              # I/O ("Entrée") device
    "CLSID-DEVC-E-IO-ALM": "Unknown I/O device (alarm)",                    # I/O ("Entrée") device
    "CLSID-DEVC-E-IO-AO": "Unknown I/O device (analog output)",             # I/O ("Entrée") device
    "CLSID-DEVC-E-IO-CPT": "Unknown I/O device (counter pulse)",            # I/O ("Entrée") device
    "CLSID-DEVC-E-IO-DI": "Unknown I/O device (digital input)",             # I/O ("Entrée") device
    "CLSID-DEVC-E-IO-DO": "Unknown I/O device (digital output)",            # I/O ("Entrée") device
    "CLSID-DEVC-E-SC01": "Unknown sensor (type SC01)",                      # Input ("Entrée")
    "CLSID-DEVC-E-SC03": "Unknown sensor (type SC03)",                      # Input ("Entrée")
    "CLSID-DEVC-E-SC04": "Unknown sensor (type SC04)",                      # Input ("Entrée")
    "CLSID-DEVC-M-CC01": "Unknown meter (type CC01)",                       # Meter: Unknown device type
    "CLSID-DEVC-M-CC02": "Unknown meter (type CC02)",                       # Meter: Unknown device type
    "CLSID-DEVC-M-CC03": "Unknown meter (type CC03)",                       # Meter: Unknown device type
    "CLSID-DEVC-M-CP04": "Unknown energy meter (type CP04)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP05": "Unknown energy meter (type CP05)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP06": "Unknown energy meter (type CP06)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP07": "Unknown energy meter (type CP07)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP08": "Unknown energy meter (type CP08)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP09": "Unknown energy meter (type CP09)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP10": "Unknown energy meter (type CP10)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP11": "Unknown energy meter (type CP11)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP12": "Unknown energy meter (type CP12)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP13": "Calybox 2020 WT",                                 # Meter: Energy meter
    "CLSID-DEVC-M-CP14": "Unknown energy meter (type CP14)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CP15": "Unknown energy meter (type CP15)",                # Meter: Unknown energy meter
    "CLSID-DEVC-M-CS01": "Unknown sensor (type CS01)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS02": "Unknown sensor (type CS02)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS03": "Unknown sensor (type CS03)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS04": "Unknown sensor (type CS04)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS05": "Unknown sensor (type CS05)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS06": "Unknown sensor (type CS06)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS07": "Unknown sensor (type CS07)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS08": "Unknown sensor (type CS08)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS09": "Unknown sensor (type CS09)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS10": "Unknown sensor (type CS10)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS11": "Unknown sensor (type CS11)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS12": "Unknown sensor (type CS12)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS13": "Unknown sensor (type CS13)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS14": "Unknown sensor (type CS14)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS15": "Tysense thermo (type CS15)",                      # Meter: Temperature probe
    "CLSID-DEVC-M-CS16": "Unknown sensor (type CS16)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS17": "Unknown sensor (type CS17)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS18": "Unknown sensor (type CS18)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS19": "Unknown sensor (type CS19)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS20": "Unknown sensor (type CS20)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS21": "Unknown sensor (type CS21)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS22": "Tysense sun",                                     # Meter: Solar irradiance
    "CLSID-DEVC-M-CS23": "Unknown sensor (type CS23)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS24": "Unknown sensor (type CS24)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS25": "Unknown sensor (type CS25)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS26": "Unknown sensor (type CS26)",                      # Meter: Unknown sensor
    "CLSID-DEVC-M-CS27": "Unknown sensor (type CS27)",                      # Meter: Unknown sensor
    "CLSID-DEVC-S-DT01": "Tyxal+ DU",                                       # Security ("DéTecteur"): Universal detector
    "CLSID-DEVC-S-DT02": "Unknown detector (type DT02)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT03": "Unknown detector (type DT03)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT04": "Unknown detector (type DT04)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT05": "Tyxal+ DF",                                       # Security ("DéTecteur"): Flood detector
    "CLSID-DEVC-S-DT06": "Unknown detector (type DT06)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT07": "Unknown detector (type DT07)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT08": "Tyxal+ DFR",                                      # Security ("DéTecteur"): Smoke detector
    "CLSID-DEVC-S-DT09": "Tyxal+ DMB / DMBD / DMBE / DMBV / DMDR / DME",    # Security ("DéTecteur"): Motion detector
    "CLSID-DEVC-S-DT10": "Tyxal+ DO / DOI / DOS / MDO",                     # Security ("DéTecteur"): Opening detector
    "CLSID-DEVC-S-DT11": "Unknown detector (type DT11)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT12": "Unknown detector (type DT12)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT13": "Unknown detector (type DT13)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT14": "Unknown detector (type DT14)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT15": "Unknown detector (type DT15)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT16": "Unknown detector (type DT16)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT17": "Unknown detector (type DT17)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT18": "Unknown detector (type DT18)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT19": "Unknown detector (type DT19)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-DT20": "Unknown detector (type DT20)",                    # Security ("DéTecteur")
    "CLSID-DEVC-S-LC02": "Unknown security device (type LC02)",             # Security (LC?)
    "CLSID-DEVC-S-LC03": "Unknown security device (type LC03)",             # Security: Unknown device type
    "CLSID-DEVC-S-LC04": "Unknown security device (type LC04)",             # Security: Unknown device type
    "CLSID-DEVC-S-LC05": "Unknown security device (type LC05)",             # Security: Unknown device type
    "CLSID-DEVC-S-LC06": "Unknown security device (type LC06)",             # Security: Unknown device type
    "CLSID-DEVC-S-LC07": "Unknown security device (type LC07)",             # Security: Unknown device type
    "CLSID-DEVC-S-LC08": "Unknown security device (type LC08)",             # Security: Unknown device type
    "CLSID-DEVC-S-PR02": "Unknown protection device (type PR02)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR04": "Unknown protection device (type PR04)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR05": "Unknown protection device (type PR05)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR06": "Unknown protection device (type PR06)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR07": "Unknown protection device (type PR07)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR09": "Unknown protection device (type PR09)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR10": "Unknown protection device (type PR10)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR11": "Unknown protection device (type PR11)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR08": "Tyxal+ CS 8000",                                  # Security: Alarm central unit
    "CLSID-DEVC-S-PR09": "Unknown protection device (type PR09)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR10": "Unknown protection device (type PR10)",           # Security ("PRotection")
    "CLSID-DEVC-S-PR11": "Unknown protection device (type PR11)",           # Security ("PRotection")
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
