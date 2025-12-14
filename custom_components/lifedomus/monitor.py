"""SSH monitoring tunnel and XML push dispatcher for Lifedomus.

This module maintains a stable SSH tunnel to the Lifedomus gateway using the
'ld-remote' account on port 51023. It opens a direct-tcpip channel equivalent
to a local forward (-L) targeting 'ld-remote:8090' on the gateway and reads
incoming XML notifications. On each notification, it triggers targeted coordinator
refreshes for the impacted device or category.

Initial states and regular polling remain handled by the existing platform
coordinators, which expose async_fetch_device_snapshot() helpers.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Any, Final, Protocol, cast, runtime_checkable
from xml.etree.ElementTree import Element

import asyncssh
from defusedxml import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .api import LifedomusApi, LifedomusApiError
from .const import (
    DOMAIN,
    LD_CLSID_SYSTEM_VARIABLES,
    LD_MONITOR_SSH_PORT,
    LD_MONITOR_SSH_USER,
    LD_MONITOR_TUNNEL_PORT,
    LD_STATE_ALARM_OPERATINGMODE,
    LD_STATE_ALARM_ZONESTATUS,
    LD_STATE_LIGHT,
    LD_STATE_POSITION_PERCENTAGE,
    LD_STATE_SETPOINT_6POS,
    LD_STATE_SOCKET,
    LD_STATE_THERMOSTAT,
    LD_STATE_TRIGGERED,
    LD_STATE_VALUE,
    PATTERN_DEVICE_KEY,
)

# Accepted state CLSIDs for push filtering
ACCEPTED_STATE_CLSIDS: Final[frozenset[str]] = frozenset(
    {
        LD_STATE_ALARM_OPERATINGMODE,
        LD_STATE_ALARM_ZONESTATUS,
        LD_STATE_LIGHT,
        LD_STATE_POSITION_PERCENTAGE,  # Used both for dimmers and covers
        LD_STATE_SETPOINT_6POS,
        LD_STATE_SOCKET,
        LD_STATE_THERMOSTAT,
        LD_STATE_TRIGGERED,
        LD_STATE_VALUE,
    }
)

_LOGGER = logging.getLogger(__name__)

LOG_PREVIEW_MAX_CHARS: Final[int] = 4096
READ_CHUNK_SIZE: Final[int] = 65536
RX_MAX_BUFFER_BYTES: Final[int] = 2_000_000


@runtime_checkable
class _SnapshotCoordinator(Protocol):
    """Coordinator interface exposing per-device snapshot fetch and listener notification."""

    data: dict[str, Any]

    async def async_fetch_device_snapshot(self, device_key: str) -> Any: ...
    def async_set_updated_data(self, data: dict[str, Any]) -> None: ...


class LifedomusMonitor:
    """Maintain an SSH monitoring tunnel and dispatch XML notifications."""

    def __init__(self, hass: HomeAssistant, api: LifedomusApi, host: str) -> None:
        """Initialize the monitor."""
        self._hass = hass
        self._api = api
        self._host = host
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

        # SSH connection and direct TCP channel to the remote push service
        self._conn: asyncssh.SSHClientConnection | None = None
        self._rdr: asyncssh.SSHReader[bytes] | None = None
        self._wtr: asyncssh.SSHWriter | None = None

        # Dedup gate for noisy bursts
        self._throttle: dict[str, float] = {}
        self._throttle_interval = 0.4  # seconds

        # Incremental receive buffer used to frame complete XML documents
        self._rx_buf: bytearray = bytearray()

    async def async_start(self) -> None:
        """Start the background monitor task."""
        if self._task is None:
            self._stopping.clear()
            self._task = self._hass.loop.create_task(
                self._runner(), name="lifedomus_monitor"
            )

    def _iter_coordinators_with_snapshot(self) -> list[_SnapshotCoordinator]:
        """Return all integration coordinators that can fetch per-device snapshots.

        A coordinator is considered eligible when:
         - it lives under hass.data[DOMAIN],
         - it exposes a dict-like 'data',
         - it implements an async 'async_fetch_device_snapshot(device_key)' coroutine.
        """
        shared = self._hass.data.setdefault(DOMAIN, {})
        coords: list[_SnapshotCoordinator] = []
        if not isinstance(shared, dict):
            return coords

        for value in shared.values():
            # Check 'data' shape first
            data = getattr(value, "data", None)
            if not isinstance(data, dict):
                continue

            # Check for a coroutine-typed 'async_fetch_device_snapshot'
            fetch_obj = getattr(value, "async_fetch_device_snapshot", None)
            if fetch_obj is None or not asyncio.iscoroutinefunction(fetch_obj):
                continue

            coords.append(cast(_SnapshotCoordinator, value))

        return coords

    def _get_alarm_coordinator(self) -> _SnapshotCoordinator | None:
        """Return the alarm coordinator if available and eligible."""
        shared = self._hass.data.setdefault(DOMAIN, {})
        if not isinstance(shared, dict):
            return None
        cand = shared.get("alarm_coordinator")
        if cand is None:
            return None
        data = getattr(cand, "data", None)
        fetch_obj = getattr(cand, "async_fetch_device_snapshot", None)
        if isinstance(data, dict) and asyncio.iscoroutinefunction(fetch_obj):
            return cast(_SnapshotCoordinator, cand)
        return None

    def _xml_preview(self, raw: bytes, *, limit: int = LOG_PREVIEW_MAX_CHARS) -> str:
        """Return a safe, size-bounded UTF-8 preview for logs.

        The preview is intended for observability to visualize the incoming
        XML notifications from the SSH tunnel without risking excessive log volume.
        """
        text: str = raw.decode("utf-8", errors="replace")
        if len(text) > limit:
            return f"{text[:limit]}… [truncated]"
        return text

    async def async_stop(self) -> None:
        """Stop the background monitor task and release resources."""
        self._stopping.set()

        # Proactively close the SSH connection to abort any in-flight channel setup
        conn = self._conn
        if conn is not None:
            with suppress(asyncssh.Error, OSError):
                conn.close()
                await conn.wait_closed()

        task = self._task
        if task is not None:
            task.cancel()
            # Suppress both cancellation and transport errors while the task unwinds
            with suppress(asyncio.CancelledError, asyncssh.Error, OSError):
                await task
            self._task = None

        await self._close_resources()

    async def _close_resources(self) -> None:
        """Close the direct TCP channel and SSH connection."""
        if self._wtr is not None:
            with suppress(asyncssh.Error, OSError):
                self._wtr.close()
                await self._wtr.wait_closed()
            self._wtr = None
        self._rdr = None

        if self._conn is not None:
            with suppress(asyncssh.Error, OSError):
                self._conn.close()
                await self._conn.wait_closed()
            self._conn = None

    async def _open_ssh_connection(self) -> None:
        """Establish the SSH connection using the SecureConnect private key."""
        key_text = await self._api.async_get_monitor_private_key()
        key = asyncssh.import_private_key(key_text)
        self._conn = await asyncssh.connect(
            self._host,
            port=LD_MONITOR_SSH_PORT,
            username=LD_MONITOR_SSH_USER,
            client_keys=[key],
            known_hosts=None,  # Accept host key for this managed tunnel
            keepalive_interval=30,
            keepalive_count_max=3,
        )
        _LOGGER.info(
            "Lifedomus SSH monitor connected to %s:%s",
            self._host,
            LD_MONITOR_SSH_PORT,
        )

    async def _open_direct_channel(self) -> None:
        """Open the direct TCP channel to the remote push service and set typed streams."""
        if self._conn is None:
            raise OSError("SSH connection is not established")

        try:
            rdr, wtr = await self._conn.open_connection(
                LD_MONITOR_SSH_USER,
                LD_MONITOR_TUNNEL_PORT,
                encoding=None,  # ensure bytes -> SSHReader[bytes]
            )
        except asyncssh.ChannelOpenError as ch_err:
            _LOGGER.error(
                "Lifedomus SSH monitor: direct channel refused to %s:%s "
                "(reason=%s, code=%s)",
                LD_MONITOR_SSH_USER,
                LD_MONITOR_TUNNEL_PORT,
                ch_err.reason,
                getattr(ch_err, "code", "n/a"),
            )
            raise
        except (asyncssh.Error, OSError) as err:
            _LOGGER.error(
                "Lifedomus SSH monitor: failed opening channel to %s:%s: %s",
                LD_MONITOR_SSH_USER,
                LD_MONITOR_TUNNEL_PORT,
                err,
            )
            raise

        # Narrow types for static checkers
        self._rdr = cast(asyncssh.SSHReader[bytes], rdr)
        self._wtr = cast(asyncssh.SSHWriter, wtr)
        _LOGGER.info(
            "Lifedomus SSH monitor opened channel to remote %s:%s",
            LD_MONITOR_SSH_USER,
            LD_MONITOR_TUNNEL_PORT,
        )

    async def _read_loop(self) -> bool:
        """Read remote stream until closed or stop requested. Return True if closed by stop."""
        if self._rdr is None:
            return True

        while not self._stopping.is_set():
            chunk = await self._rdr.read(READ_CHUNK_SIZE)
            if not chunk:
                # Remote closed the channel
                return False

            # Keepalive payloads are a single NUL byte; ignore them silently.
            if chunk == b"\x00":
                _LOGGER.debug("Lifedomus tunnel keepalive (NUL) received")
                continue

            await self._ingest_chunk(chunk)

        return True

    async def _runner(self) -> None:
        """Main loop which establishes the SSH session and reads the remote stream."""
        backoff = 2.0
        while not self._stopping.is_set():
            try:
                # 1) SSH connection
                await self._open_ssh_connection()

                # 2) Direct TCP channel (equivalent to ssh -L ... -> ld-remote:8090)
                if self._stopping.is_set():
                    break
                await self._open_direct_channel()

                # 3) Reset backoff after successful connection and read the stream
                backoff = 2.0
                closed_by_stop = await self._read_loop()

                if closed_by_stop:
                    _LOGGER.info("Lifedomus SSH monitor channel closed")
                else:
                    _LOGGER.warning(
                        "Lifedomus SSH monitor channel closed, attempting reconnect"
                    )

            except (asyncssh.Error, OSError, LifedomusApiError) as err:
                if self._stopping.is_set():
                    _LOGGER.debug("Lifedomus SSH monitor shutting down: %s", err)
                else:
                    _LOGGER.warning("Lifedomus SSH monitor error: %s", err)
            finally:
                await self._close_resources()

            # Reconnect with backoff unless stopping
            if self._stopping.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 300.0)  # Cap at 5 minutes

    async def _ingest_chunk(self, chunk: bytes) -> None:
        """Accumulate incoming bytes, extract complete XML frames and process them.

        This method:
         - strips NUL bytes appearing inside the stream (defensive),
         - removes non-printable leading noise until the first '<',
         - frames one complete XML document at a time,
         - deserializes each document and dispatches it independently.
        """
        if not chunk:
            return

        # Drop any stray NUL bytes which may appear between frames
        if b"\x00" in chunk:
            chunk = chunk.replace(b"\x00", b"")

        # Append to the incremental buffer
        self._rx_buf.extend(chunk)

        # Extract and process as many complete XML frames as available
        while True:
            frame = self._pop_next_xml_frame()
            if frame is None:
                break

            # Log a safe preview of the single XML frame
            _LOGGER.debug(
                "Lifedomus tunnel XML frame received (%d bytes):\n%s",
                len(frame),
                self._xml_preview(frame),
            )

            # Deserialize for basic sanity; parsing failures are logged and skipped
            xml_text: str = frame.decode("utf-8", errors="replace")

            try:
                # Parse the XML document to validate it's well-formed
                # (content-specific extraction can be added later if needed)
                ET.fromstring(xml_text)
            except ET.ParseError as err:
                _LOGGER.debug("Invalid XML frame skipped: %s", err)
                continue

            # Process a single notification document
            await self._process_xml_notification(xml_text)

        # Keep buffer bounded to avoid unbounded growth on long-lived streams
        if len(self._rx_buf) > RX_MAX_BUFFER_BYTES:
            # Drop older half; only the tail may contain an incomplete document
            del self._rx_buf[: len(self._rx_buf) // 2]

    def _prepare_root_start(self, buf: bytearray) -> int | None:
        """Normalize buffer to the root start tag and return the index of '>'. None if incomplete."""
        # Skip leading noise until first '<'
        lt = buf.find(b"<")
        if lt == -1:
            return None
        if lt > 0:
            del buf[:lt]

        # Optional XML declaration
        if buf.startswith(b"<?xml"):
            end_decl = buf.find(b"?>", 5)
            if end_decl == -1:
                return None
            del buf[: end_decl + 2]
            lt2 = buf.find(b"<")
            if lt2 == -1:
                return None
            if lt2 > 0:
                del buf[:lt2]

        # Expect a root start tag '<name ...>' or '<name/>'
        gt = buf.find(b">")
        if gt == -1:
            return None
        return gt

    @staticmethod
    def _extract_root_name(buf: bytearray, gt: int) -> bytes | None:
        """Return the root element name between '<' and the first separator, or None if incomplete."""
        j = 1
        while j < gt:
            c = buf[j]
            if c in (ord(" "), ord("\t"), ord("\r"), ord("\n"), ord("/"), ord(">")):
                break
            j += 1
        if j <= 1:
            return None
        return buf[1:j]

    @staticmethod
    def _is_self_closing(buf: bytearray, gt: int) -> bool:
        """Return True if the root tag is self-closing ('<root .../>')."""
        return gt > 0 and buf[gt - 1] == ord("/")

    @staticmethod
    def _skip_tag_like_sections(buf: bytearray, start: int) -> int | None:
        """Skip comments, CDATA and processing instructions starting at 'start'.

        Returns the index just after the skipped section, or None if incomplete.
        """
        if buf.startswith(b"<!--", start):
            endc = buf.find(b"-->", start + 4)
            return None if endc == -1 else endc + 3
        if buf.startswith(b"<![CDATA[", start):
            endc = buf.find(b"]]>", start + 9)
            return None if endc == -1 else endc + 3
        if buf.startswith(b"<?", start):
            endc = buf.find(b">", start + 2)
            return None if endc == -1 else endc + 1
        return start

    def _find_matching_close(
        self, buf: bytearray, root_name: bytes, start_pos: int
    ) -> int | None:
        """Return index after the matching closing tag for the given root, or None if incomplete."""
        open_pat = b"<" + root_name
        close_pat = b"</" + root_name + b">"

        pos = start_pos
        depth = 1
        while True:
            next_lt = buf.find(b"<", pos)
            if next_lt == -1:
                return None  # Need more data

            # Skip comments/CDATA/PIs
            skipped = self._skip_tag_like_sections(buf, next_lt)
            if skipped is None:
                return None
            if skipped != next_lt:
                pos = skipped
                continue

            # Closing tag of the root?
            if buf.startswith(close_pat, next_lt):
                end_close = next_lt + len(close_pat)
                depth -= 1
                if depth <= 0:
                    return end_close
                pos = end_close
                continue

            # Opening tag with the same name increases depth (nested same-name elements)
            if buf.startswith(open_pat, next_lt):
                sep_idx = next_lt + len(open_pat)
                if sep_idx < len(buf) and buf[sep_idx] in (
                    ord(" "),
                    ord("\t"),
                    ord("\r"),
                    ord("\n"),
                    ord(">"),
                    ord("/"),
                ):
                    depth += 1

            # Move past this tag
            gt2 = buf.find(b">", next_lt + 1)
            if gt2 == -1:
                return None
            pos = gt2 + 1

    def _pop_next_xml_frame(self) -> bytes | None:
        """Return the next complete XML document as bytes, or None if incomplete.

        Framing strategy:
         - Skip leading noise until '<' (defensive against non-printable prefixes).
         - Skip optional XML declaration '<?xml ...?>'.
         - Identify the root start tag and find its matching closing tag with a
           lightweight depth counter when nested tags have the same name.
        """
        buf = self._rx_buf
        result: bytes | None = None

        # Normalize buffer to the root start and find the '>' index
        gt = self._prepare_root_start(buf)
        if gt is None:
            return None

        # Extract root name
        root_name = self._extract_root_name(buf, gt)
        if root_name is None:
            return None

        # Self-closing single-tag document: '<root .../>'
        if self._is_self_closing(buf, gt):
            end = gt + 1
            result = bytes(buf[:end])
            del buf[:end]
            return result

        # Search for matching closing tag with a lightweight depth counter
        end_close = self._find_matching_close(buf, root_name, gt + 1)
        if end_close is None:
            return None

        result = bytes(buf[:end_close])
        del buf[:end_close]
        return result

    async def _process_xml_notification(self, xml_text: str) -> None:
        """Process one <State .../> message with strict attribute validation.

        Expected shape:
            <State clsid="CLSID-STATE-..." device_key="DEVC_..."/>
            or
            <State clsid="CLSID-STATE-VALUE" system_variable_key="CLSID-SYSTEM-..."/>

        Rules:
        - Only the root element <State .../> is accepted.
        - 'clsid' must be in ACCEPTED_STATE_CLSIDS.
        - 'device_key' must match PATTERN_DEVICE_KEY, or 'system_variable_key' must be valid.
        - On success, refresh only this device if it already exists in a coordinator.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as err:
            _LOGGER.debug("Skipping malformed XML frame: %s", err)
            return

        if root.tag != "State":
            _LOGGER.debug("XML frame ignored (root element is not <State/>)")
            return

        clsid = root.attrib.get("clsid", "")
        device_key = root.attrib.get("device_key", "")
        system_variable_key = root.attrib.get("system_variable_key", "")

        if clsid not in ACCEPTED_STATE_CLSIDS:
            _LOGGER.debug("State ignored (clsid %s not accepted)", clsid)
            return

        if system_variable_key and system_variable_key in LD_CLSID_SYSTEM_VARIABLES:
            _LOGGER.debug("System variable notification: %s", system_variable_key)
            self._hass.async_create_task(
                self._refresh_system_variable(system_variable_key, root)
            )
            return

        if not device_key or not PATTERN_DEVICE_KEY.fullmatch(device_key):
            _LOGGER.debug("State ignored (invalid or missing device_key)")
            return

        _LOGGER.debug("Notification: %s -> %s", clsid, device_key)

        # Throttle and refresh only if the device already exists
        now = asyncio.get_running_loop().time()
        last = self._throttle.get(device_key, 0.0)
        if now - last < self._throttle_interval:
            return

        self._throttle[device_key] = now
        self._hass.async_create_task(self._refresh_existing_device(device_key, clsid))

    async def _refresh_existing_device(
        self, device_key: str, clsid: str | None = None
    ) -> None:
        """Refresh a device snapshot on coordinators that already know this device.

        When the state comes from the alarm domain (operating mode or zone status),
        refresh only the shared alarm coordinator for efficiency. This ensures that
        zone status changes (LD_STATE_ALARM_ZONESTATUS) propagate to
        LifedomusAlarmZoneSwitch entities, which listen to the alarm coordinator.

        For other state types, fall back to iterating all eligible coordinators.
        """
        targets: list[_SnapshotCoordinator] = []

        # Target the alarm coordinator on alarm-related notifications, including zone status.
        if clsid in (LD_STATE_ALARM_OPERATINGMODE, LD_STATE_ALARM_ZONESTATUS):
            alarm_coord = self._get_alarm_coordinator()
            if alarm_coord is not None and device_key in alarm_coord.data:
                targets = [alarm_coord]

        if not targets:
            targets = self._iter_coordinators_with_snapshot()

        for coord in targets:
            if device_key not in coord.data:
                continue
            try:
                updated = await coord.async_fetch_device_snapshot(device_key)
            except LifedomusApiError as err:
                _LOGGER.debug(
                    "Existing-device refresh failed on %s for %s: %s",
                    getattr(coord, "name", type(coord).__name__),
                    device_key,
                    err,
                )
                continue

            if updated is None:
                continue

            new_data = dict(coord.data)
            new_data[device_key] = updated
            coord.async_set_updated_data(new_data)

    async def _refresh_system_variable(self, variable_key: str, root: Element) -> None:
        """Refresh a system variable sensor from a push notification.

        Push notifications for system variables contain only the clsid and system_variable_key.
        The actual value must be fetched via the API using async_get_system_variable.

        Args:
            variable_key: The system variable key (e.g., CLSID-SYSTEM-WEB).
            root: The XML <State/> element (used for potential future enhancements).
        """
        shared = self._hass.data.setdefault(DOMAIN, {})
        config = LD_CLSID_SYSTEM_VARIABLES.get(variable_key)

        if not config:
            return

        registry = er.async_get(self._hass)

        if config.value_type is bool:
            system_binary_sensors = shared.get("system_binary_sensors", {})
            binary_sensor = system_binary_sensors.get(variable_key)
            if binary_sensor is not None:
                entity_id = binary_sensor.entity_id
                if entity_id:
                    entry = registry.async_get(entity_id)
                    if entry and entry.disabled:
                        return
                await binary_sensor.async_update()
                binary_sensor.async_write_ha_state()
        else:
            system_sensors = shared.get("system_sensors", {})
            sensor = system_sensors.get(variable_key)
            if sensor is not None:
                entity_id = sensor.entity_id
                if entity_id:
                    entry = registry.async_get(entity_id)
                    if entry and entry.disabled:
                        return
                await sensor.async_update()
                sensor.async_write_ha_state()
