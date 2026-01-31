"""Lifedomus API client.

This module provides an asynchronous HTTP client for the Lifedomus gateway.
It exposes minimal helpers to validate connectivity and retrieve basic info
(e.g., version and UUID) and specific helpers to list sites and users.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from aiohttp import ClientError, ClientSession, ClientTimeout
from defusedxml import ElementTree as ET

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    LD_CLSID_SYSTEM_VARIABLES,
    LD_DAY_OF_WEEK_MAPPING,
    LD_HTTP_HEADERS,
    LD_MONTH_MAPPING,
    LD_PORT,
    LD_STATE_VALUE,
    OPTION_UPDATE_INTERVAL_DEFAULT,
    PATTERN_DEVICE_KEY,
    PATTERN_SESSION_KEY,
    PATTERN_SITE_KEY,
    PATTERN_USER_KEY,
    SOAP_NAMESPACE,
)

HTTP_RESPONSE_OK: Final = 200


@dataclass(slots=True)
class SiteInfo:
    """Container for Lifedomus site information."""

    site_key: str
    label: str
    currency: str
    date_format: str
    time_format: str
    order_view: int
    default: bool


@dataclass(slots=True)
class UserInfo:
    """Container for Lifedomus user information."""

    user_key: str
    nickname: str
    order_view: int


class LifedomusApiError(Exception):
    """Base exception for Lifedomus API errors."""


class LifedomusAuthError(LifedomusApiError):
    """Authentication or authorization error."""


def parse_bool(txt: str | None) -> bool | None:
    """Convert a textual boolean to a Python boolean."""
    if txt is None:
        return None
    s = txt.strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def parse_number(txt: str | None, *, prefer_int: bool = False) -> float | int | None:
    """Convert a string with optional comma decimal separator to a number.

    Args:
        txt: The text to parse.
        prefer_int: When true, returns int for exact integer values.

    Returns:
        float, int (when prefer_int and value is an integer) or None if invalid.
    """
    if txt is None:
        return None
    s = txt.strip().replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    if prefer_int and val.is_integer():
        return int(val)
    return val


def build_action_descriptor(args: dict[str, Any]) -> str:
    """Build a generic XML descriptor for ExecuteOneAction.

    The descriptor is built as:
        <args>
          <arg><name>n1</name><value>v1</value></arg>
          <arg><name>n2</name><value>v2</value></arg>
          ...
        </args>

    Args:
        args: Mapping of parameter name -> value.

    Returns:
        The XML descriptor string. Values are converted as:
         - bool -> 'true'/'false'
         - other types -> str(value)
         - None values are skipped
    """
    parts: list[str] = []
    for name, value in args.items():
        if value is None:
            continue
        v = ("true" if value else "false") if isinstance(value, bool) else str(value)
        parts.append(
            f"<arg><name>{escape(str(name))}</name><value>{escape(v)}</value></arg>"
        )
    return f"<args>{''.join(parts)}</args>"


class LifedomusApi:
    """Asynchronous client for the Lifedomus API."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        *,
        verify_ssl: bool = False,
        request_timeout: float = OPTION_UPDATE_INTERVAL_DEFAULT,
    ) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._host = host.strip().rstrip("/")
        self._timeout = ClientTimeout(total=request_timeout)
        # Lifedomus installations often use self-signed certs; verification can be disabled.
        self._session: ClientSession = async_get_clientsession(
            hass, verify_ssl=verify_ssl
        )
        # Authentication context used for automatic session refresh.
        self._site_key: str | None = None
        self._user_key: str | None = None
        self._password: str | None = None
        self._session_key: str | None = None

    def _ensure_valid_device_key(self, value: str) -> str:
        """Validate and return a device/target key in the expected format."""
        if not value or not PATTERN_DEVICE_KEY.fullmatch(value):
            raise LifedomusApiError(
                "Invalid device_key/target_key format; expected pattern '^DEVC_[0-9]{35}$'"
            )
        return value

    def txt(self, tag: str, parent: Element) -> str:
        """Return the stripped text content of the given tag from the parent element."""
        el = parent.find(tag)
        return el.text.strip() if el is not None and el.text is not None else ""

    @staticmethod
    def txt_path(parent: Element, path: str) -> str | None:
        """Return stripped text at a relative XPath-like path, or None.

        Args:
            parent: Parent XML element from which the path is evaluated.
            path: Relative path (Element.find syntax) to the desired node.

        Returns:
            The stripped text when present, otherwise None.
        """
        el = parent.find(path)
        return el.text.strip() if el is not None and el.text is not None else None

    async def async_get_uuid(self) -> str:
        """Return UUID."""
        namespace = "Account"
        action = "GetUUID"
        elements = await self.async_request(namespace=namespace, action=action)
        if not elements or elements[0].text is None:
            raise LifedomusApiError(
                f"No UUID found in response from {namespace}/{action} on {self._host}"
            )
        return elements[0].text.strip()

    async def async_get_version(self) -> str:
        """Return version information."""
        namespace = "CoreServices"
        action = "GetVersion"
        elements = await self.async_request(namespace=namespace, action=action)
        if not elements or elements[0].text is None:
            raise LifedomusApiError(
                f"No version information found in response from {namespace}/{action} on {self._host}"
            )
        return elements[0].text.strip()

    async def async_get_site_list(self) -> list[SiteInfo]:
        """Return the ordered site list.

        Site key format is validated here when parsing the response.
        """
        returns = await self.async_request(namespace="Site", action="GetNameList")

        sites: list[SiteInfo] = []
        for ret in returns:
            order_raw = self.txt(tag="order_view", parent=ret)
            try:
                order_view = int(order_raw) if order_raw else 0
            except ValueError:
                order_view = 0

            site_key = self.txt(tag="site_key", parent=ret)
            if not site_key or not PATTERN_SITE_KEY.fullmatch(site_key):
                raise LifedomusApiError(
                    "Invalid site_key format; expected pattern '^SITE_[0-9]{35}$'"
                )
            label = self.txt(tag="label", parent=ret)

            sites.append(
                SiteInfo(
                    site_key=site_key,
                    label=label,
                    currency=self.txt(tag="currency", parent=ret),
                    date_format=self.txt(tag="dateFormat", parent=ret),
                    time_format=self.txt(tag="timeFormat", parent=ret),
                    order_view=order_view,
                    default=bool(self.txt(tag="deft", parent=ret) == "true"),
                )
            )

        sites.sort(key=lambda s: s.order_view)
        return sites

    async def async_get_user_list(self, site_key: str) -> list[UserInfo]:
        """Return the user list for a given site.

        User key format is validated here when parsing the response.
        The provided site_key is trusted at this point.
        """
        returns = await self.async_request(
            namespace="User", action="GetNameList", params={"site_key": site_key}
        )

        users: list[UserInfo] = []

        for ret in returns:
            nickname = self.txt(tag="nickname", parent=ret)
            user_key = self.txt(tag="user_key", parent=ret)
            order_raw = self.txt(tag="order_view", parent=ret)
            try:
                order_view = int(order_raw) if order_raw else 0
            except ValueError:
                order_view = 0

            # Validate user_key only during parsing of User/GetNameList.
            if not user_key or not PATTERN_USER_KEY.fullmatch(user_key):
                raise LifedomusApiError(
                    "Invalid user_key format; expected pattern '^USER_[0-9]{35}$'"
                )

            if nickname:
                users.append(
                    UserInfo(
                        user_key=user_key,
                        nickname=nickname or user_key,
                        order_view=order_view,
                    )
                )

        users.sort(key=lambda u: u.order_view)
        return users

    def set_auth_context(
        self, *, site_key: str, user_key: str, password: str | None
    ) -> None:
        """Set the authentication context used for User/Login and session refresh.

        Args:
            site_key: The site key to authenticate against.
            user_key: The user key used for the login.
            password: The password for the user.
        """
        self._site_key = site_key
        self._user_key = user_key
        self._password = password

    def _set_session_key(self, session_key: str) -> None:
        """Validate and store the current session key.

        Args:
            session_key: The raw session key returned by the gateway.

        Raises:
            LifedomusApiError: If the provided key does not match the expected format.
        """
        cleaned_key = session_key.strip()
        if not PATTERN_SESSION_KEY.fullmatch(cleaned_key):
            raise LifedomusApiError(
                "Invalid session_key format; expected '^[a-z0-9]{40}$'"
            )
        self._session_key = cleaned_key

    async def async_request(
        self,
        namespace: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> list[Element]:
        """Perform the HTTP request and return the response text."""

        def build_payload_and_method() -> tuple[str, str]:
            """Return (method, payload) for the SOAP request."""
            # Account/GetUUID and CoreServices/GetVersion are GET; everything else is POST.
            if (namespace == "Account" and action == "GetUUID") or (
                namespace == "CoreServices" and action == "GetVersion"
            ):
                return "GET", ""

            # All other calls are POST: build payload with params and optional session key injection.
            post_params = dict(params) if params else {}

            # Inject session_key for authenticated POST calls, except for Login and GetNameList.
            if (
                action not in {"Login", "GetNameList"}
                and "session_key" not in post_params
                and self._session_key is not None
            ):
                post_params["session_key"] = self._session_key

            # Validate device/target keys ONLY if not a system variable
            target_type = post_params.get("target_type", "")
            if target_type != "SYSTEM_VARIABLE":
                for key_name in ("device_key", "target_key"):
                    if key_name in post_params:
                        post_params[key_name] = self._ensure_valid_device_key(
                            str(post_params[key_name])
                        )

            # Determine the correct domain for the namespace
            if namespace in ("CoreServices", "State"):
                domain_hint = "domobox"
            else:
                domain_hint = "domoboxbusiness"

            params_xml = "".join(
                f"<{escape(str(k))}>{escape(str(v))}</{escape(str(k))}>"
                for k, v in post_params.items()
            )
            payload_xml = (
                f'<soap:Envelope xmlns:soap="{SOAP_NAMESPACE}">'
                "<soap:Body>"
                f'<ns2:{escape(action)} xmlns:ns2="http://{escape(namespace)}.ws.{escape(domain_hint)}.com/">'
                f"{params_xml}"
                f"</ns2:{escape(action)}>"
                "</soap:Body>"
                "</soap:Envelope>"
            )
            return "POST", payload_xml

        attempted_refresh = False
        while True:
            method, payload = build_payload_and_method()
            try:
                resp = await self._session.request(
                    method,
                    f"https://{self._host}:{LD_PORT}/DomoBox/{namespace}/{action}",
                    headers=LD_HTTP_HEADERS,
                    data=payload or {},
                    timeout=self._timeout,
                )
            except ClientError as err:
                raise LifedomusApiError(
                    f"HTTP error while calling {namespace}/{action} on {self._host}: {err}"
                ) from err

            # If authentication was refused, attempt a session refresh via User/Login and retry once.
            if (
                resp.status in {401, 403, 500}
                and action != "Login"
                and not attempted_refresh
            ):
                await self.async_refresh_session()
                attempted_refresh = True
                # Loop will rebuild payload with the new session key and retry once.
                continue

            # Raise domain-specific exception if not successful.
            if resp.status != HTTP_RESPONSE_OK:
                raise LifedomusAuthError(
                    f"Auth failed calling {namespace}/{action} on {self._host} (status {resp.status})"
                )

            # Parse SOAP XML response.
            try:
                root = ET.fromstring(await resp.text())
                body_el = root.find(f"{{{SOAP_NAMESPACE}}}Body")
                if body_el is None:
                    raise LifedomusApiError(
                        f"SOAP Body not found in XML from {namespace}/{action} on {self._host}"
                    )
                return body_el.findall(".//return")
            except ET.ParseError as err:
                raise LifedomusApiError(
                    f"Invalid XML from {namespace}/{action} on {self._host}: {err}"
                ) from err

    async def async_refresh_session(self) -> None:
        """Refresh the session by performing a User/Login call.

        This method validates the authentication context and performs a login request
        to obtain a new session key. The SOAP request is delegated to async_request()
        to keep request handling consistent across the client.

        Raises:
            LifedomusAuthError: If authentication context is missing or if the login fails.
            LifedomusApiError: If the response does not contain a valid session key.
        """
        params: list[str] = []
        if not self._site_key or self._site_key == "None":
            params.append("site_key")
        if not self._user_key or self._user_key == "None":
            params.append("user_key")
        if not self._password or self._password == "None":
            params.append("password")

        if params:
            if len(params) == 1:
                missing_str = params[0]
            else:
                missing_str = ", ".join(params[:-1]) + f" and {params[-1]}"
            raise LifedomusAuthError(f"Cannot refresh session: missing {missing_str}")

        returns = await self.async_request(
            namespace="User",
            action="Login",
            params={
                "site_key": self._site_key,
                "user_key": self._user_key,
                "password": self._password,
            },
        )

        if not returns or returns[0].text is None:
            raise LifedomusApiError(
                f"No session_key returned by User/Login on {self._host}"
            )

        self._set_session_key(returns[0].text)

    async def async_execute_one_action(
        self,
        *,
        target_key: str,
        prop_clsid: str,
        action_clsid: str,
        prop_numr: int = 0,
        descriptor: str | None = None,
    ) -> list[Element]:
        """Execute a CoreServices/ExecuteOneAction call with common defaults.

        This helper centralizes the standard payload used across platforms.
        """
        params: dict[str, Any] = {
            "site_key": self._site_key,
            "user_key": self._user_key,
            "target_key": self._ensure_valid_device_key(target_key),
            "prop_clsid": prop_clsid,
            "prop_numr": int(prop_numr),
            "action_clsid": action_clsid,
        }
        if descriptor:
            params["descriptor"] = descriptor

        return await self.async_request(
            namespace="CoreServices", action="ExecuteOneAction", params=params
        )

    async def async_get_monitor_private_key(self) -> str:
        """Return the SSH private key content for 'ld-remote' monitoring.

        The key is fetched using a GET request on /SecureConnect?format=classic.
        The returned content is expected to be a PEM-encoded private key.
        """
        url = f"https://{self._host}:{LD_PORT}/SecureConnect?format=classic"
        try:
            resp = await self._session.request(
                "GET", url, headers=LD_HTTP_HEADERS, timeout=self._timeout
            )
        except ClientError as err:
            raise LifedomusApiError(
                f"HTTP error while fetching SecureConnect key on {self._host}: {err}"
            ) from err

        if resp.status != HTTP_RESPONSE_OK:
            raise LifedomusApiError(
                f"Failed to fetch SecureConnect key on {self._host} (status {resp.status})"
            )

        key_text = await resp.text()
        # Basic sanity check for PEM content
        if "BEGIN" not in key_text or "PRIVATE KEY" not in key_text:
            raise LifedomusApiError(
                "Invalid SecureConnect key content returned by gateway"
            )
        return key_text

    async def async_get_total_data_value(
        self, *, site_key: str, device_key: str, value_type: str = "elec"
    ) -> dict[str, Any]:
        """Fetch total data value from Mobile/GetTotalDataValue.

        Args:
            site_key: Site key for the request.
            device_key: Device key (energy meter).
            value_type: Energy type, defaults to 'elec'.

        Returns:
            A dict containing parsed fields:
            - value: float (total consumption in Wh or similar unit),
            - value_reset: float,
            - date: dict with dayInMonth, month, year,
            - date_reset: dict with dayInMonth, month, year.
        """
        returns = await self.async_request(
            namespace="Mobile",
            action="GetTotalDataValue",
            params={
                "site_key": site_key,
                "device_key": self._ensure_valid_device_key(device_key),
                "type": value_type,
            },
        )

        if not returns:
            raise LifedomusApiError(
                f"No data returned by GetTotalDataValue for device {device_key}"
            )

        ret = returns[0]

        def parse_float_sci(txt: str | None) -> float | None:
            """Parse a float in standard or scientific notation."""
            if txt is None:
                return None
            s = txt.strip()
            try:
                return float(s)
            except ValueError:
                return None

        def parse_date_element(parent: Element | None) -> str | None:
            """Parse a date element into ISO format (YYYY-MM-DD)."""
            if parent is None:
                return None

            day_txt = self.txt_path(parent, "dayInMonth")
            month_txt = self.txt_path(parent, "month")
            year_txt = self.txt_path(parent, "year")

            if not day_txt or not month_txt or not year_txt:
                return None

            try:
                day = int(day_txt.strip())
                month = LD_MONTH_MAPPING.get(month_txt.strip().upper())
                year = int(year_txt.strip())

                if month is None:
                    return None

                parsed_date = date(year, month, day)
                return parsed_date.isoformat()
            except (ValueError, KeyError):
                return None

        return {
            "value": parse_float_sci(self.txt_path(ret, "value")),
            "value_reset": parse_float_sci(self.txt_path(ret, "value_reset")),
            "date": parse_date_element(ret.find("date")),
            "date_reset": parse_date_element(ret.find("date_reset")),
        }

    async def async_get_system_variable(
        self, *, site_key: str, variable_key: str
    ) -> bool | date | datetime | int | float | str | None:
        """Fetch a system variable value from State/GetNewValue.

        Args:
            site_key: Site key for the request.
            variable_key: System variable key (e.g., CLSID-SYSTEM-WEB, CLSID-SYSTEM-TIME).

        Returns:
            The parsed value as int, float, bool, str (ISO 8601 for string TIME, HH:MM for DURATION), datetime (for datetime TIME) or None if unavailable.
        """
        returns = await self.async_request(
            namespace="State",
            action="GetNewValue",
            params={
                "site_key": site_key,
                "target_key": variable_key,
                "target_type": "SYSTEM_VARIABLE",
                "state_clsid": LD_STATE_VALUE,
                "prop_numr": 0,
            },
        )

        if not returns:
            return None

        ret = returns[0]
        value_type = self.txt_path(ret, "type")
        config = LD_CLSID_SYSTEM_VARIABLES.get(variable_key)

        if not config:
            return None

        if value_type == "BOOLEAN" and config.value_type is bool:
            value_txt = self.txt_path(ret, "value")
            return parse_bool(value_txt) if value_txt else None

        if value_type in ("DAY_OF_MONTH", "NUMERIC") and config.value_type in (
            int,
            float,
        ):
            value_txt = self.txt_path(ret, "value")
            return (
                parse_number(value_txt, prefer_int=(config.value_type is int))
                if value_txt
                else None
            )

        if value_type == "TIME":
            value_el = ret.find("value")
            if value_el is None:
                return None

            hour_txt = self.txt_path(value_el, "hour")
            minute_txt = self.txt_path(value_el, "minute")
            offset_txt = self.txt_path(value_el, "GMTOffsetInMinute")

            if hour_txt is None or minute_txt is None:
                return None

            try:
                hour = int(hour_txt)
                minute = int(minute_txt)

                # Handle DURATION: return HH:MM string format
                if config.sensor_class == SensorDeviceClass.DURATION:
                    return f"{hour:02d}:{minute:02d}"

                # Handle full datetime for timestamp variables
                if config.value_type is datetime:
                    if offset_txt is None:
                        return None
                    gmt_offset_min = int(offset_txt)
                    tz_offset = timezone(timedelta(minutes=gmt_offset_min))
                    return datetime.now(tz=tz_offset).replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )

                # Handle string TIME format: HH:MM±HH:MM
                if config.value_type is str:
                    if offset_txt is None:
                        return None
                    gmt_offset_min = int(offset_txt)

                    # Build timezone offset string
                    offset_hours = abs(gmt_offset_min) // 60
                    offset_minutes = abs(gmt_offset_min) % 60
                    offset_sign = "+" if gmt_offset_min >= 0 else "-"

                    return f"{hour:02d}:{minute:02d}{offset_sign}{offset_hours:02d}:{offset_minutes:02d}"

            except (ValueError, OverflowError):
                return None

        if value_type == "DATE":
            value_el = ret.find("value")
            if value_el is None:
                return None

            day_txt = self.txt_path(value_el, "dayInMonth")
            month_txt = self.txt_path(value_el, "month")
            year_txt = self.txt_path(value_el, "year")

            if not day_txt or not month_txt or not year_txt:
                return None

            try:
                day = int(day_txt.strip())
                month = LD_MONTH_MAPPING.get(month_txt.strip().upper())
                year = int(year_txt.strip())

                if month is None:
                    return None

                if config.value_type is date:
                    return date(year, month, day)

            except (ValueError, KeyError):
                return None

        if value_type == "DAY_OF_WEEK":
            value_txt = self.txt_path(ret, "value")
            if not value_txt:
                return None

            try:
                day_num = int(value_txt.strip())
                if config.value_type is str:
                    return LD_DAY_OF_WEEK_MAPPING.get(day_num)
            except ValueError:
                return None

        return None
