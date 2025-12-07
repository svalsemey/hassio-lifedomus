"""Lifedomus multicast discovery helpers.

This module implements the UDP multicast probe used by Lifedomus gateways to
respond with their name, IP, and UUID. It is used by the config flow and
startup routine to propose zero-configuration setup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import socket
import struct
from typing import Final

from homeassistant.core import HomeAssistant

from .const import (
    DISCOVERY_MCAST_ADDR,
    DISCOVERY_MCAST_PORT,
    DISCOVERY_PACKET_PREFIX,
    DISCOVERY_PACKET_SUFFIX,
    DISCOVERY_TIMEOUT_S,
)

# Response packet layout constants
RESP_MIN_TOTAL_LEN: Final[int] = 10
RESP_MIN_UUID_SECTION_TOTAL_LEN: Final[int] = 42
RESP_IDX_EXPECTED_LEN: Final[int] = 2
RESP_IDX_NAME_LEN: Final[int] = 5
RESP_NAME_START: Final[int] = 6
RESP_UUID_LEN: Final[int] = 40
RESP_UUID_TRAILER_LEN: Final[int] = 1


@dataclass(frozen=True)
class LifedomusDiscoveredDevice:
    """Container for a discovered Lifedomus gateway."""

    name: str
    host: str
    uuid: str


def _build_probe_payload(source_port: int) -> bytes:
    """Build the discovery probe payload."""
    payload = bytearray(DISCOVERY_PACKET_PREFIX)
    payload.extend(source_port.to_bytes(length=2, byteorder="big"))
    payload.extend(DISCOVERY_PACKET_SUFFIX)
    return bytes(payload)


def _is_basic_length_valid(data: bytes) -> bool:
    """Return True when the packet has at least the minimum total length."""
    return bool(data) and len(data) >= RESP_MIN_TOTAL_LEN


def _has_expected_length(data: bytes) -> bool:
    """Validate the 'expected length' byte against the actual packet length."""
    try:
        return data[RESP_IDX_EXPECTED_LEN] == len(data)
    except IndexError:
        return False


def _extract_name(data: bytes) -> str | None:
    """Extract and decode the gateway name from the response, or None on failure."""
    try:
        name_len = data[RESP_IDX_NAME_LEN]
        start = RESP_NAME_START
        end = start + name_len
        if end > len(data):
            return None
        return data[start:end].decode("ascii")
    except (IndexError, UnicodeDecodeError):
        return None


def _extract_uuid(data: bytes) -> str | None:
    """Extract and decode the UUID from the tail section, or None on failure."""
    if len(data) < RESP_MIN_UUID_SECTION_TOTAL_LEN:
        return None
    start = -(RESP_UUID_LEN + RESP_UUID_TRAILER_LEN)
    end = -RESP_UUID_TRAILER_LEN
    try:
        return data[start:end].decode("ascii")
    except UnicodeDecodeError:
        return None


def _parse_response(
    data: bytes, addr: tuple[str, int]
) -> LifedomusDiscoveredDevice | None:
    """Parse a discovery response into a structured result.

    The parser performs a sequence of small validations with early exits to keep
    branching low while maintaining strictness:
      - basic length check,
      - expected total length byte matches actual length,
      - name slice is within bounds and ASCII-decodable,
      - UUID tail section has the required minimal size and is ASCII-decodable.
    """
    if not _is_basic_length_valid(data):
        return None

    if not _has_expected_length(data):
        return None

    name = _extract_name(data)
    if name is None:
        return None

    uuid = _extract_uuid(data)
    if uuid is None:
        return None

    host = addr[0]
    return LifedomusDiscoveredDevice(name=name, host=host, uuid=uuid)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Datagram protocol to collect discovery responses."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.results: dict[str, LifedomusDiscoveredDevice] = {}
        self.on_connection = asyncio.get_running_loop().create_future()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        if not self.on_connection.done():
            self.on_connection.set_result(True)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        parsed = _parse_response(data, addr)
        if parsed is None:
            return
        # Use UUID as unique key to deduplicate responses.
        self.results[parsed.uuid] = parsed

    def error_received(self, exc: Exception) -> None:
        # Ignore individual datagram errors; discovery is best-effort.
        return

    def connection_lost(self, exc: Exception | None) -> None:
        return


async def async_discover_lifedomus(
    hass: HomeAssistant, timeout: float = DISCOVERY_TIMEOUT_S
) -> list[LifedomusDiscoveredDevice]:
    """Send a multicast probe and collect Lifedomus discovery responses."""
    loop = asyncio.get_running_loop()

    # Create and configure UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        # Bind to an ephemeral port to embed it in the payload
        sock.bind(("", 0))
        # Set TTL to 1 to limit to local segment
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 1))
        # Make socket non-blocking for asyncio
        sock.setblocking(False)

        # Build asyncio transport/protocol
        protocol = _DiscoveryProtocol()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            sock=sock,
        )

        try:
            # Wait until protocol is ready
            await protocol.on_connection

            # Build payload containing the bound source port
            port = sock.getsockname()[1]
            payload = _build_probe_payload(port)

            # Send probe to multicast group
            transport.sendto(payload, (DISCOVERY_MCAST_ADDR, DISCOVERY_MCAST_PORT))

            try:
                # Collect responses for the given timeout window
                await asyncio.sleep(timeout)
            finally:
                transport.close()
        finally:
            # Transport owns the socket; no manual close here.
            pass
    except OSError:
        # Best-effort discovery: return empty on socket errors
        return []

    return list(protocol.results.values())
