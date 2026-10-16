"""Lifedomus config flow.

Flows provided by this module:
 - user: pick a discovered gateway (or enter its host), select a site and a
   user, enter the password, then register the 6-digit access code of the
   alarm panel when the site has one.
 - reauth: ask for a new password once the gateway rejects the stored one.
 - reconfigure: change the gateway host and keep, replace or clear the stored
   alarm code.
 - options: polling interval; the entry is reloaded automatically on change.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any, Final

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback

from .api import LifedomusApi, LifedomusApiError, LifedomusAuthError
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

CLEAR_ALARM_CODE: Final = "clear_alarm_code"
ALARM_CODE_PATTERN: Final = re.compile(r"[0-9]{6}")
# Requests issued by the flow fail fast so the user is not left waiting.
FLOW_REQUEST_TIMEOUT_S: Final = 10.0

STEP_HOST_SCHEMA: Final = vol.Schema(
    {vol.Required(CONF_HOST): vol.All(str, vol.Strip, vol.Length(min=1))}
)
STEP_PASSWORD_SCHEMA: Final = vol.Schema({vol.Required(CONF_PASSWORD): str})
OPTIONS_SCHEMA: Final = vol.Schema(
    {
        vol.Required(
            OPTION_UPDATE_INTERVAL, default=OPTION_UPDATE_INTERVAL_DEFAULT
        ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600))
    }
)


class LifedomusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Lifedomus."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow state collected across steps."""
        self._host = ""
        self._uuid = ""
        self._version = ""
        self._site_key = ""
        self._site_label = ""
        self._user_key = ""
        self._password = ""
        self._gateway_choices: dict[str, str] = {}
        self._sites: dict[str, str] = {}
        # Authenticated client, available once the password step succeeded.
        self._api: LifedomusApi | None = None
        self._alarm_device_key: str | None = None
        # None keeps the stored code during reconfiguration; "" clears it.
        self._alarm_code: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler for Lifedomus."""
        return LifedomusOptionsFlowHandler()

    def _new_api(self) -> LifedomusApi:
        """Return an unauthenticated client for the selected host."""
        return LifedomusApi(
            self.hass,
            self._host,
            verify_ssl=False,
            request_timeout=FLOW_REQUEST_TIMEOUT_S,
        )

    async def _async_load_gateway(self) -> str | None:
        """Fetch the gateway identity and its sites; return an error key on failure."""
        api = self._new_api()
        try:
            self._uuid = await api.async_get_uuid()
            self._version = await api.async_get_version()
            sites = await api.async_get_site_list()
        except LifedomusApiError as err:
            _LOGGER.debug("Gateway %s is not usable: %s", self._host, err)
            return "cannot_connect"
        self._sites = {site.site_key: site.label for site in sites if site.label}
        return None if self._sites else "no_site_configured"

    async def _async_authenticate(self) -> str | None:
        """Log in with the collected credentials; return an error key on failure."""
        api = self._new_api()
        api.set_auth_context(
            site_key=self._site_key, user_key=self._user_key, password=self._password
        )
        try:
            await api.async_refresh_session()
        except LifedomusAuthError as err:
            _LOGGER.debug("Login refused by %s: %s", self._host, err)
            return "invalid_auth"
        except LifedomusApiError as err:
            _LOGGER.debug("Login failed on %s: %s", self._host, err)
            return "cannot_connect"
        self._api = api
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered gateway or switch to manual host entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_HOST] == MANUAL_SELECT_VALUE:
                return await self.async_step_gateway_manual()
            self._host = user_input[CONF_HOST]
            if (error := await self._async_load_gateway()) is None:
                return await self.async_step_site_select()
            errors["base"] = error
        else:
            discovered = await async_discover_lifedomus(
                self.hass, timeout=DISCOVERY_TIMEOUT_S
            )
            if not discovered:
                return await self.async_step_gateway_manual()
            self._gateway_choices = {MANUAL_SELECT_VALUE: MANUAL_SELECT_LABEL} | {
                device.host: f"{device.name} ({device.host}) [{device.uuid}]"
                for device in discovered
            }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST): vol.In(self._gateway_choices)}
            ),
            errors=errors,
        )

    async def async_step_gateway_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the gateway host when discovery found nothing or was skipped."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            if (error := await self._async_load_gateway()) is None:
                return await self.async_step_site_select()
            errors["base"] = error
        return self.async_show_form(
            step_id="gateway_manual", data_schema=STEP_HOST_SCHEMA, errors=errors
        )

    async def async_step_site_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a site of the gateway; the site identifies the config entry."""
        if user_input is None:
            return self.async_show_form(
                step_id="site_select",
                data_schema=vol.Schema(
                    {vol.Required(CONF_SITE_KEY): vol.In(self._sites)}
                ),
            )
        self._site_key = user_input[CONF_SITE_KEY]
        self._site_label = self._sites[self._site_key]
        await self.async_set_unique_id(f"{self._uuid}:{self._site_key}")
        self._abort_if_unique_id_configured()
        return await self.async_step_user_select()

    async def async_step_user_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the gateway user, displayed by nickname."""
        if user_input is not None:
            self._user_key = user_input[CONF_USER_KEY]
            return await self.async_step_password()
        try:
            users = await self._new_api().async_get_user_list(self._site_key)
        except LifedomusApiError:
            return self.async_abort(reason="cannot_connect")
        if not (choices := {user.user_key: user.nickname for user in users}):
            return self.async_abort(reason="no_user_configured")
        return self.async_show_form(
            step_id="user_select",
            data_schema=vol.Schema({vol.Required(CONF_USER_KEY): vol.In(choices)}),
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password of the selected user and validate it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            if (error := await self._async_authenticate()) is None:
                return await self.async_step_alarm_code()
            errors["base"] = error
        return self.async_show_form(
            step_id="password", data_schema=STEP_PASSWORD_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start a reauthentication flow once the gateway rejects the stored password."""
        self._host = entry_data[CONF_HOST]
        self._site_key = entry_data[CONF_SITE_KEY]
        self._user_key = entry_data[CONF_USER_KEY]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password and reload the entry once it is accepted."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            if (error := await self._async_authenticate()) is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_PASSWORD: self._password},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_PASSWORD_SCHEMA,
            description_placeholders={"host": self._host},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway host, then review the alarm code of the entry.

        The entered host must lead to the gateway and site of the entry.
        """
        entry = self._get_reconfigure_entry()
        self._site_key = entry.data[CONF_SITE_KEY]
        self._user_key = entry.data[CONF_USER_KEY]
        self._password = entry.data[CONF_PASSWORD]

        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            if (error := await self._async_load_gateway()) is None:
                await self.async_set_unique_id(f"{self._uuid}:{self._site_key}")
                self._abort_if_unique_id_mismatch()
                if (error := await self._async_authenticate()) is None:
                    return await self.async_step_alarm_code()
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_HOST_SCHEMA, {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )

    async def _async_detect_alarm_device(self, api: LifedomusApi) -> str | None:
        """Return the key of the first alarm panel of the site, if any."""
        try:
            returns = await api.async_request(
                namespace="Mobile",
                action="GetDevicesFromCatg",
                params={"category_clsid": LdDeviceCategory.SURVEILLANCE_PROTECTION},
            )
        except LifedomusApiError as err:
            _LOGGER.debug("Alarm device detection failed: %s", err)
            return None
        return next(
            (
                api.txt("device_key", dev_el)
                for ret in returns
                for dev_el in ret.findall("device")
                if api.txt("device_key", dev_el)
            ),
            None,
        )

    async def _async_verify_alarm_code(
        self, api: LifedomusApi, code: str
    ) -> str | None:
        """Check that the gateway grants USER access for the code; return an error key otherwise."""
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
            return "cannot_connect"
        level = next((ret.text.strip().upper() for ret in returns if ret.text), None)
        return None if level == "USER" else "alarm_code_denied"

    def _show_alarm_code_form(
        self, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Show the alarm code form; a clear checkbox is offered when a code is stored."""
        schema: dict[Any, Any] = {vol.Optional(CONF_ALARM_CODE, default=""): str}
        if self.source == SOURCE_RECONFIGURE and self._get_reconfigure_entry().data.get(
            CONF_ALARM_CODE
        ):
            schema[vol.Optional(CLEAR_ALARM_CODE, default=False)] = bool
        return self.async_show_form(
            step_id="alarm_code", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_alarm_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Register the access code of the alarm panel when the site has one.

        An empty code skips the step on initial setup and keeps the stored code
        during reconfiguration unless clearing is requested. A non-empty code
        must be 6 digits and is verified against the gateway before being saved.
        """
        if (api := self._api) is None:
            return self.async_abort(reason="unknown")

        if user_input is None:
            self._alarm_device_key = await self._async_detect_alarm_device(api)
            if self._alarm_device_key is None:
                return await self._async_finish()
            return self._show_alarm_code_form()

        if not (code := user_input[CONF_ALARM_CODE].strip()):
            keep_stored = self.source == SOURCE_RECONFIGURE and not user_input.get(
                CLEAR_ALARM_CODE, False
            )
            self._alarm_code = None if keep_stored else ""
            return await self._async_finish()
        if not ALARM_CODE_PATTERN.fullmatch(code):
            return self._show_alarm_code_form({CONF_ALARM_CODE: "invalid_alarm_code"})
        if (error := await self._async_verify_alarm_code(api, code)) is not None:
            return self._show_alarm_code_form({"base": error})
        self._alarm_code = code
        return await self._async_finish()

    async def _async_finish(self) -> ConfigFlowResult:
        """Create the config entry, or update and reload it during reconfiguration."""
        if self.source == SOURCE_RECONFIGURE:
            updates: dict[str, Any] = {
                CONF_HOST: self._host,
                CONF_VERSION: self._version,
            }
            if self._alarm_code is not None:
                updates[CONF_ALARM_CODE] = self._alarm_code
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=updates
            )

        return self.async_create_entry(
            title=self._site_label,
            data={
                CONF_HOST: self._host,
                CONF_NAME: self._site_label,
                CONF_UUID: self._uuid,
                CONF_VERSION: self._version,
                CONF_SITE_KEY: self._site_key,
                CONF_SITE_LABEL: self._site_label,
                CONF_USER_KEY: self._user_key,
                CONF_PASSWORD: self._password,
                CONF_ALARM_CODE: self._alarm_code or "",
            },
        )


class LifedomusOptionsFlowHandler(OptionsFlowWithReload):
    """Handle Lifedomus options; the entry is reloaded when they change."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the polling interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
