"""Lifedomus config flow.

This module implements the Home Assistant config flow for the Lifedomus
integration. It discovers gateways (or lets the user enter a host manually),
then lets the user select a site from the chosen gateway, select a user
(by nickname), asks for the password, authenticates against the gateway to
retrieve a lifedomus_key, and finally creates the config entry with the site
label as the entry title.

This module also exposes an options flow that allows users to configure:
 - the global update interval in seconds (default: 15),
 - the delay before refreshing the status of an X3D device in milliseconds (default: 2000),
 - the alarm access code (6 digits only), used in alarm actions descriptors.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from aiohttp import ClientError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api import LifedomusApi, LifedomusApiError
from .const import (
    CONF_ALARM_CODE,
    CONF_NAME,
    CONF_SITE_KEY,
    CONF_SITE_LABEL,
    CONF_USER_KEY,
    CONF_UUID,
    CONF_VERSION,
    DISCOVERY_TIMEOUT_S,
    DOMAIN,
    MANUAL_SELECT_LABEL,
    MANUAL_SELECT_VALUE,
    OPTION_UPDATE_INTERVAL,
    OPTION_UPDATE_INTERVAL_DEFAULT,
    LdDeviceCategory,
)
from .discovery import async_discover_lifedomus

_LOGGER = logging.getLogger(__name__)

STEP_PASSWORD_ONLY_SCHEMA: Final = vol.Schema({vol.Required(CONF_PASSWORD): str})

CLEAR_ALARM_CODE: Final = "clear_alarm_code"


class LifedomusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Lifedomus."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow instance."""
        self._host: str | None = None
        self._name: str | None = None
        self._uuid: str | None = None
        self._version: str | None = None
        self._site_key: str | None = None
        self._site_label: str | None = None
        self._user_key: str | None = None
        self._password: str | None = None
        self._session_key: str | None = None
        self._alarm_device_key: str | None = None
        self._alarm_code: str | None = None
        self._stored_alarm_code: str | None = None

        # Keep track of a reconfigure flow and the entry being updated
        self._reconfigure_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler for Lifedomus."""
        return LifedomusOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the flow by discovering or entering a gateway host."""
        return await self.async_step_discover(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-run the configuration steps using the existing entry context.

        This step reloads current data (host, site, user, password) from the
        existing config entry and jumps to the authentication step. On success,
        the existing entry will be updated and reloaded instead of creating a new one.
        """
        entry_id = self.context.get("entry_id")
        if not entry_id:
            return self.async_abort(reason="unknown")

        config_entry = self.hass.config_entries.async_get_entry(entry_id)
        if config_entry is None:
            return self.async_abort(reason="unknown")

        # Mark this flow as a reconfigure flow and preload current values.
        self._reconfigure_entry = config_entry
        data = config_entry.data
        self._host = str(data.get(CONF_HOST) or "")
        self._uuid = str(data.get(CONF_UUID) or "")
        self._site_key = str(data.get(CONF_SITE_KEY) or "")
        self._site_label = str(data.get(CONF_SITE_LABEL) or "")
        self._user_key = str(data.get(CONF_USER_KEY) or "")
        self._password = str(data.get(CONF_PASSWORD) or "")
        self._stored_alarm_code = str(data.get(CONF_ALARM_CODE, "") or "")

        # Jump directly to auth which will also re-run alarm detection/validation.
        return await self.async_step_auth()

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover gateways and let the user pick one or choose manual entry.

        If no gateway is discovered, jump directly to the manual host step.
        """
        errors: dict[str, str] = {}

        discovered_hosts: dict[str, str] = {
            f"{d.name} ({d.host}) [{d.uuid}]": d.host
            for d in await async_discover_lifedomus(
                self.hass, timeout=DISCOVERY_TIMEOUT_S
            )
        }

        # If nothing discovered, go straight to manual host entry.
        if not discovered_hosts:
            return await self.async_step_gateway_manual()

        # Always include a "manual entry" choice in addition to discovered gateways.
        selectable: dict[str, str] = {MANUAL_SELECT_LABEL: MANUAL_SELECT_VALUE}
        selectable.update(discovered_hosts)

        if user_input is None or CONF_HOST not in user_input:
            data_schema = vol.Schema({vol.Required(CONF_HOST): vol.In(selectable)})
            return self.async_show_form(
                step_id="discover", data_schema=data_schema, errors=errors
            )

        host = selectable.get(user_input[CONF_HOST]) or user_input[CONF_HOST]
        if host == MANUAL_SELECT_VALUE:
            return await self.async_step_gateway_manual()

        # A discovered host was selected.
        if not host:
            errors["base"] = "unknown"
            data_schema = vol.Schema({vol.Required(CONF_HOST): vol.In(selectable)})
            return self.async_show_form(
                step_id="discover", data_schema=data_schema, errors=errors
            )

        self._host = host
        return await self.async_step_site_select()

    async def async_step_gateway_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to manually enter the gateway host."""
        errors: dict[str, str] = {}

        data_schema = vol.Schema({vol.Required(CONF_HOST): str})

        if user_input is None:
            return self.async_show_form(
                step_id="gateway_manual", data_schema=data_schema, errors=errors
            )

        host = str(user_input.get(CONF_HOST, "")).strip()
        if not host:
            errors["base"] = "unknown"
            return self.async_show_form(
                step_id="gateway_manual", data_schema=data_schema, errors=errors
            )

        self._host = host
        return await self.async_step_site_select()

    async def async_step_site_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a site from the already selected gateway."""
        errors: dict[str, str] = {}

        if self._host is None:
            # No host selected yet: return to discover step.
            return await self.async_step_discover(user_input)

        api = LifedomusApi(
            self.hass, self._host, verify_ssl=False, request_timeout=10.0
        )

        # Get UUID
        try:
            self._uuid = await api.async_get_uuid()
        except LifedomusApiError:
            return self.async_abort(reason="invalid_uuid")

        # Get version
        try:
            self._version = await api.async_get_version()
        except LifedomusApiError:
            return self.async_abort(reason="invalid_version")

        # Fetch sites
        try:
            sites = await api.async_get_site_list()
        except LifedomusApiError:
            return self.async_abort(reason="no_site_configured")

        # Build a mapping "label -> site_key".
        options: dict[str, str] = {}
        for s in sites:
            label = getattr(s, "label", None)
            site_key = getattr(s, "site_key", None)
            if not label or not site_key:
                continue
            options[site_key] = label

        # First display: show the list of sites by labels.
        if user_input is None or CONF_SITE_KEY not in user_input:
            data_schema = vol.Schema({vol.Required(CONF_SITE_KEY): vol.In(options)})
            return self.async_show_form(
                step_id="site_select", data_schema=data_schema, errors=errors
            )

        self._site_key = user_input[CONF_SITE_KEY]

        await self.async_set_unique_id(f"{self._uuid}:{self._site_key}")
        self._abort_if_unique_id_configured()

        self._site_label = options[user_input[CONF_SITE_KEY]]
        return await self.async_step_user_select()

    async def async_step_user_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fetch site user list and let the user choose a nickname.

        No transient mappings or nickname are stored; only user_key is kept after selection.
        """
        errors: dict[str, str] = {}

        if not self._host or not self._site_key:
            return self.async_abort(reason="unknown")

        api = LifedomusApi(
            self.hass, self._host, verify_ssl=False, request_timeout=10.0
        )

        # Fetch users
        try:
            users = await api.async_get_user_list(self._site_key)
        except LifedomusApiError:
            return self.async_abort(reason="no_user_configured")

        # Build a mapping "nickname -> user_key".
        options: dict[str, str] = {}
        for u in users:
            nickname = getattr(u, "nickname", None)
            user_key = getattr(u, "user_key", None)
            if not nickname or not user_key:
                continue
            options[user_key] = nickname

        # First display: show the list of users by nicknames.
        if user_input is None or CONF_USER_KEY not in user_input:
            data_schema = vol.Schema({vol.Required(CONF_USER_KEY): vol.In(options)})
            return self.async_show_form(
                step_id="user_select", data_schema=data_schema, errors=errors
            )

        self._user_key = user_input[CONF_USER_KEY]
        return await self.async_step_password()

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password of the previously selected user."""
        errors: dict[str, str] = {}

        if not self._host or not self._site_key or not self._user_key:
            return self.async_abort(reason="unknown")

        if user_input is None:
            return self.async_show_form(
                step_id="password", data_schema=STEP_PASSWORD_ONLY_SCHEMA, errors=errors
            )

        self._password = user_input[CONF_PASSWORD]
        return await self.async_step_auth()

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Authenticate against the gateway using the API session refresh helper.

        This leverages LifedomusApi._async_refresh_session to perform User/Login,
        avoiding duplicate SOAP envelope construction and raw HTTP handling here.
        The Login action is a POST endpoint under /DomoBox/User/Login/, which
        matches the documented URL shape and SOAP payload building rules.
        """
        errors: dict[str, str] = {}

        if (
            not self._host
            or not self._site_key
            or not self._user_key
            or not self._password
        ):
            return self.async_abort(reason="unknown")

        api = LifedomusApi(
            self.hass,
            self._host,
            verify_ssl=False,
            request_timeout=OPTION_UPDATE_INTERVAL_DEFAULT,
        )

        # Provide credentials for the Login call; session_key is obtained from the API.
        api.set_auth_context(
            site_key=self._site_key,
            user_key=self._user_key,
            password=self._password,
        )

        try:
            # Perform the Login by checking the session key to validate the password.
            await api.async_refresh_session()
            self._session_key = getattr(api, "_session_key", None)
            if not self._session_key:
                errors["base"] = "invalid_auth"
                _LOGGER.debug("Login succeeded but no session key was returned")
                return self.async_show_form(
                    step_id="password",
                    data_schema=STEP_PASSWORD_ONLY_SCHEMA,
                    errors=errors,
                )
        except LifedomusApiError as err:
            # Map any API/XML/auth error to invalid_auth to let the user retry.
            errors["base"] = "invalid_auth"
            _LOGGER.debug("Login failed: %s", err)
            return self.async_show_form(
                step_id="password",
                data_schema=STEP_PASSWORD_ONLY_SCHEMA,
                errors=errors,
            )
        except ClientError as err:
            # Map connection errors to cannot_connect.
            errors["base"] = "cannot_connect"
            _LOGGER.debug("Login connectivity error: %s", err)
            return self.async_show_form(
                step_id="password",
                data_schema=STEP_PASSWORD_ONLY_SCHEMA,
                errors=errors,
            )

        # Detect alarm device after successful authentication and branch accordingly.
        self._alarm_device_key = await self._async_detect_alarm_device(api)
        if self._alarm_device_key:
            return await self.async_step_alarm_code()

        return await self._async_finish()

    async def _async_detect_alarm_device(self, api: LifedomusApi) -> str | None:
        """Return first alarm device_key if any is present on the site."""
        try:
            returns = await api.async_request(
                namespace="Mobile",
                action="GetDevicesFromCatg",
                params={
                    "category_clsid": LdDeviceCategory.SURVEILLANCE_PROTECTION,
                },
            )
        except LifedomusApiError as err:
            _LOGGER.debug("Alarm device detection failed: %s", err)
            return None

        for ret in returns:
            for dev_el in ret.findall("device"):
                key_el = dev_el.find("device_key")
                if key_el is not None and key_el.text:
                    key = key_el.text.strip()
                    if key:
                        return key
        return None

    def _build_alarm_code_schema(self, has_existing_code: bool) -> vol.Schema:
        """Build and return the voluptuous schema for the alarm code step."""
        schema_dict: dict[Any, Any] = {vol.Optional(CONF_ALARM_CODE, default=""): str}
        if has_existing_code:
            schema_dict[vol.Optional(CLEAR_ALARM_CODE, default=False)] = bool
        return vol.Schema(schema_dict)

    @staticmethod
    def _is_valid_alarm_code(code: str) -> bool:
        """Return True when the provided code matches the required 6-digit format."""
        return bool(re.fullmatch(r"[0-9]{6}", code))

    async def _async_verify_alarm_code(self, code: str) -> tuple[bool, str | None]:
        """Verify the provided alarm code against the gateway.

        Returns:
            A tuple (allowed, error_base) where:
              - allowed is True when the gateway grants USER access for the code,
              - error_base is a translation key to display at form level when a connectivity
                problem occurred (e.g. 'cannot_connect'); None otherwise.
        """
        if (
            not self._host
            or not self._site_key
            or not self._user_key
            or not self._password
        ):
            return False, "cannot_connect"

        api = LifedomusApi(
            self.hass,
            self._host,
            verify_ssl=False,
            request_timeout=OPTION_UPDATE_INTERVAL_DEFAULT,
        )
        api.set_auth_context(
            site_key=self._site_key or "",
            user_key=self._user_key or "",
            password=self._password or "",
        )

        try:
            await api.async_refresh_session()
        except (LifedomusApiError, ClientError):
            return False, "cannot_connect"

        try:
            returns = await api.async_request(
                namespace="Mobile",
                action="GetAlarmeAccessLevel",
                params={
                    "site_key": self._site_key,
                    "device_key": self._alarm_device_key,
                    "access_code": code,
                },
            )
        except LifedomusApiError:
            return False, "cannot_connect"

        result_text: str | None = None
        for ret in returns:
            if ret.text:
                result_text = ret.text.strip().upper()
                break

        return (result_text == "USER"), None

    def _should_display_alarm_form(
        self, user_input: dict[str, Any] | None, has_existing_code: bool
    ) -> bool:
        """Return True when the alarm code form should be displayed first.

        Rules:
        - On initial display, user_input is None.
        - During reconfiguration, the form can be shown without CONF_ALARM_CODE
          when an existing code is already stored (checkbox-only display).
        """
        return user_input is None or (
            CONF_ALARM_CODE not in user_input and not has_existing_code
        )

    def _normalize_alarm_form_input(
        self, user_input: dict[str, Any] | None, has_existing_code: bool
    ) -> tuple[str, bool]:
        """Normalize alarm form input into (code, clear_requested)."""
        ui: dict[str, Any] = user_input or {}
        code = str(ui.get(CONF_ALARM_CODE, "")).strip()
        clear_requested = (
            bool(ui.get(CLEAR_ALARM_CODE, False)) if has_existing_code else False
        )
        return code, clear_requested

    async def _apply_reconfigure_semantics(
        self, code: str, clear_requested: bool
    ) -> ConfigFlowResult | None:
        """Apply reconfigure-specific semantics; return a final result if handled.

        Reconfigure rules:
        - empty code + no clear -> keep existing code (no change)
        - empty code + clear -> explicit clear
        When a rule applies, finish the flow immediately.
        """
        if self._reconfigure_entry is None:
            return None

        if code == "" and not clear_requested:
            self._alarm_code = None
            return await self._async_finish()

        if code == "" and clear_requested:
            self._alarm_code = ""
            return await self._async_finish()

        return None

    async def async_step_alarm_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the alarm access code and validate it or skip.

        Reconfiguration:
        - empty code -> keep stored value unless 'clear' is requested,
        - 'clear' checkbox allows clearing the stored code,
        - non-empty code must be 6 digits and is validated before saving.
        """
        errors: dict[str, str] = {}

        has_existing_code = bool(self._reconfigure_entry and self._stored_alarm_code)
        data_schema = self._build_alarm_code_schema(has_existing_code)

        def show_form() -> ConfigFlowResult:
            """Return the alarm code form with current errors."""
            return self.async_show_form(
                step_id="alarm_code", data_schema=data_schema, errors=errors
            )

        result: ConfigFlowResult | None = None

        # Preconditions: if any essential context is missing or there is no alarm device,
        # skip this step and finish the flow.
        if (
            not self._host
            or not self._site_key
            or not self._user_key
            or not self._password
            or not self._alarm_device_key
        ):
            result = await self._async_finish()
        elif self._should_display_alarm_form(user_input, has_existing_code):
            # First-time display (or checkbox-only display during reconfiguration).
            result = show_form()
        else:
            # Normalize input and apply reconfigure-specific semantics if any.
            code, clear_requested = self._normalize_alarm_form_input(
                user_input, has_existing_code
            )

            maybe_result = await self._apply_reconfigure_semantics(
                code, clear_requested
            )
            if maybe_result is not None:
                result = maybe_result
            elif code == "":
                # Initial configuration: empty means skip and do not save a code.
                self._alarm_code = None
                result = await self._async_finish()
            elif not self._is_valid_alarm_code(code):
                errors[CONF_ALARM_CODE] = "invalid_alarm_code"
                result = show_form()
            else:
                # Verify the code against the gateway.
                allowed, err_base = await self._async_verify_alarm_code(code)
                if err_base is not None:
                    errors["base"] = err_base
                    result = show_form()
                elif allowed:
                    self._alarm_code = code
                    result = await self._async_finish()
                else:
                    errors["base"] = "alarm_code_denied"
                    result = show_form()

        # Defensive fallback to ensure a single exit with a non-None result.
        if result is None:
            result = show_form()

        return result

    async def _async_finish(self) -> ConfigFlowResult:
        """Finalize the flow and create or update the hub device entry.

        - On initial setup: create the config entry and register the hub device.
        - On reconfigure: update the existing entry, update the hub device, and reload it.
        """
        if (
            not self._host
            or not self._site_key
            or not self._user_key
            or not self._session_key
        ):
            return self.async_abort(reason="unknown")

        if self._reconfigure_entry is not None:
            # Update only the alarm code unless other fields need to change too.
            current_data = dict(self._reconfigure_entry.data)
            # Decide which code to store:
            # - None  -> keep existing value unchanged
            # - ""    -> explicit clear
            # - "xxxxxx" -> new validated code
            if self._alarm_code is None:
                new_code_to_store = current_data.get(CONF_ALARM_CODE, "")
            else:
                new_code_to_store = self._alarm_code

            current_data[CONF_ALARM_CODE] = new_code_to_store

            # Persist and reload entry for the change to take effect immediately.
            self.hass.config_entries.async_update_entry(
                self._reconfigure_entry, data=current_data
            )
            await self.hass.config_entries.async_reload(
                self._reconfigure_entry.entry_id
            )

            return self.async_abort(reason="reconfigure_successful")

        # Initial configuration: create the entry as usual.
        entry_data: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_NAME: self._site_label,
            CONF_UUID: self._uuid,
            CONF_VERSION: self._version,
            CONF_SITE_KEY: self._site_key,
            CONF_SITE_LABEL: self._site_label,
            CONF_USER_KEY: self._user_key,
            CONF_PASSWORD: self._password,
            CONF_ALARM_CODE: self._alarm_code or "",
        }

        return self.async_create_entry(
            title=self._site_label or "Lifedomus",
            data=entry_data,
        )


class LifedomusOptionsFlowHandler(OptionsFlow):
    """Handle Lifedomus options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options handler."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        current_interval = int(
            self._config_entry.options.get(
                OPTION_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL_DEFAULT
            )
        )

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Build schema defaults using last submitted values or current options.
        def _default_val(key: str, fallback: Any) -> Any:
            if user_input is None:
                return fallback
            return user_input.get(key, fallback)

        data_schema = vol.Schema(
            {
                vol.Required(
                    OPTION_UPDATE_INTERVAL,
                    default=int(_default_val(OPTION_UPDATE_INTERVAL, current_interval)),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate the flow cannot connect to the host."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate provided credentials are invalid."""
