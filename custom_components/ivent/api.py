"""API client for i-Vent ventilation unit via local UDP + protobuf protocol.

Protocol reverse-engineered from PCAP capture of the i-Vent mobile app.
Communication is via UDP port 1028 using raw protobuf wire format.

Message structure:
  Outer envelope: field1=msg_type, field2=1, field4=inner_message_bytes
  Inner message (request):
    f1=device_id(fixed64), f2=nonce(fixed32), f3=0, f4=0,
    f5=session_token, f6=timestamp, f7=protocol_version(2), fN=payload
  Inner message (response):
    f1=device_id(fixed64), f2=nonce(fixed32), f3=0, f4=session_token,
    f5=0, f6=timestamp, f7=protocol_version(1), f65=device_info

Sensor data is in the discovery response (msg type 257), nested at:
  inner.f65 -> f10 (sensor data protobuf with fields 1-13)
  inner.f65 -> f8 (firmware string)
  inner.f65 -> f9 (device name string)
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass

from .const import (
    MSG_DEVICE_STATE,
    MSG_DISCOVERY_A,
    MSG_HEARTBEAT,
    MSG_SCHEDULE,
    MSG_STATUS_PING,
    PROTOCOL_VERSION,
    SCHED_DIRECTION,
    SCHED_END_TIME,
    SCHED_FAN_LEVEL,
    SCHED_FLAG_A,
    SCHED_FLAG_B,
    SCHED_MODE,
    SCHED_MODE_RECOVERY,
    SCHED_MODE_VENTILATION,
    SCHED_SETPOINT,
    SCHED_START_TIME,
    SCHED_SUB_MODE,
    UDP_PORT,
)
from .proto import (
    decode_fields,
    encode_field_bytes,
    encode_field_fixed32,
    encode_field_fixed64,
    encode_field_varint,
    get_field,
    varint_to_signed32,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for waiting on UDP responses
UDP_TIMEOUT = 5.0
# Delay between messages to avoid device rate-limiting
MSG_DELAY = 0.3


@dataclass
class IVentDeviceStatus:
    """Represents current status of an i-Vent unit."""

    device_id: str
    name: str
    is_on: bool
    fan_speed: str  # off, low, medium, high, boost
    mode: str  # recovery, supply, exhaust
    supply_temp: float | None
    exhaust_temp: float | None
    outdoor_temp: float | None
    indoor_temp: float | None
    co2: int | None  # ppm, from i-Qube sensor
    humidity: float | None
    filter_status: str | None  # ok, replace
    firmware: str | None
    target_temp: int | None  # Temperature setpoint (16-33°C)


# Fan speed mapping: protobuf field 8 value -> named speed
FAN_SPEED_MAP = {
    0: "off",
    1: "low",
    2: "low",
    3: "medium",
    4: "high",
    5: "boost",
}

# Schedule slot nonces — persistent IDs for the device's 3 schedule slots.
# Discovered from PCAP: same nonces used across all sessions.
SCHEDULE_NONCES = [0, 115407251, 2081680875]

FAN_SPEED_TO_PROTO = {
    "off": 0,
    "low": 1,
    "medium": 3,
    "high": 4,
    "boost": 5,
}

# Mode mapping: protobuf field 7 value -> named mode
MODE_MAP = {
    0: "off",
    1: "supply",
    2: "exhaust",
    3: "exhaust",
    4: "recovery",
}

MODE_TO_PROTO = {
    "recovery": 4,
    "supply": 1,
    "exhaust": 2,
}


class IVentUdpProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol handler for i-Vent communication."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self._response_queue: asyncio.Queue[tuple[bytes, tuple[str, int]]] = asyncio.Queue()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._response_queue.put_nowait((data, addr))

    def error_received(self, exc: Exception) -> None:
        _LOGGER.warning("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        _LOGGER.debug("UDP connection lost: %s", exc)

    async def receive(self, timeout: float = UDP_TIMEOUT) -> tuple[bytes, tuple[str, int]] | None:
        """Wait for a response with timeout."""
        try:
            return await asyncio.wait_for(self._response_queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    def drain_queue(self) -> None:
        """Clear any pending responses."""
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


class IVentApiClient:
    """Client for communicating with i-Vent ventilation unit via local UDP."""

    def __init__(
        self,
        host: str,
        device_id: int,
        session_token: int,
    ) -> None:
        self._host = host
        self._device_id = device_id
        self._session_token = session_token
        self._protocol: IVentUdpProtocol | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._connected = False
        # Cache last known sensor data for control commands
        self._last_sensor_data: dict | None = None

    async def connect(self) -> None:
        """Create the UDP socket bound to source port 1028.

        The i-Vent device only responds to packets from source port 1028.
        """
        if self._connected:
            return
        loop = asyncio.get_running_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            IVentUdpProtocol,
            local_addr=("0.0.0.0", UDP_PORT),
            remote_addr=(self._host, UDP_PORT),
        )
        self._connected = True
        _LOGGER.debug("UDP socket created for %s:%d (source port %d)", self._host, UDP_PORT, UDP_PORT)

    async def disconnect(self) -> None:
        """Close the UDP socket."""
        if self._transport:
            self._transport.close()
            self._transport = None
            self._protocol = None
            self._connected = False

    def _generate_nonce(self) -> int:
        return struct.unpack("<I", os.urandom(4))[0]

    def _build_inner_message(self, command_field: int | None = None, command_data: bytes | None = None) -> bytes:
        """Build the inner protobuf message."""
        msg = b""
        msg += encode_field_fixed64(1, self._device_id)
        msg += encode_field_fixed32(2, self._generate_nonce())
        msg += encode_field_varint(3, 0)
        msg += encode_field_varint(4, 0)
        msg += encode_field_varint(5, self._session_token)
        msg += encode_field_varint(6, int(time.time()))
        msg += encode_field_varint(7, PROTOCOL_VERSION)
        if command_field is not None and command_data is not None:
            msg += encode_field_bytes(command_field, command_data)
        return msg

    def _build_packet(self, msg_type: int, command_field: int | None = None, command_data: bytes | None = None) -> bytes:
        """Build a complete outer envelope packet."""
        inner = self._build_inner_message(command_field, command_data)
        packet = b""
        packet += encode_field_varint(1, msg_type)
        packet += encode_field_varint(2, 1)
        packet += encode_field_bytes(4, inner)
        return packet

    @staticmethod
    def _build_broadcast_discovery() -> bytes:
        """Build a generic discovery packet without device-specific credentials.

        Used for network scanning — sends device_id=0, session_token=0
        so all i-Vent devices on the network respond.
        """
        inner = b""
        inner += encode_field_fixed64(1, 0)  # no specific device
        inner += encode_field_fixed32(2, struct.unpack("<I", os.urandom(4))[0])
        inner += encode_field_varint(3, 0)
        inner += encode_field_varint(4, 0)
        inner += encode_field_varint(5, 0)  # no session token
        inner += encode_field_varint(6, int(time.time()))
        inner += encode_field_varint(7, PROTOCOL_VERSION)
        packet = b""
        packet += encode_field_varint(1, MSG_DISCOVERY_A)
        packet += encode_field_varint(2, 1)
        packet += encode_field_bytes(4, inner)
        return packet

    async def _send_and_receive(self, packet: bytes, timeout: float = UDP_TIMEOUT) -> bytes | None:
        """Send a packet and wait for a response."""
        if not self._connected or not self._protocol or not self._transport:
            await self.connect()
        self._protocol.drain_queue()
        self._transport.sendto(packet)
        result = await self._protocol.receive(timeout)
        if result is None:
            return None
        return result[0]

    async def _send_no_wait(self, packet: bytes) -> None:
        """Send a packet without waiting for response."""
        if not self._connected or not self._protocol or not self._transport:
            await self.connect()
        _LOGGER.warning(
            "IVENT _send_no_wait: sending %d bytes to %s:%d, transport=%s",
            len(packet), self._host, UDP_PORT, self._transport,
        )
        try:
            self._transport.sendto(packet)
            _LOGGER.warning("IVENT _send_no_wait: sendto completed")
        except Exception as e:
            _LOGGER.error("IVENT _send_no_wait: sendto FAILED: %s", e)

    def _parse_discovery_response(self, data: bytes) -> tuple[dict | None, str | None, str | None]:
        """Parse a discovery response for sensor data, firmware, and device name.

        Discovery response structure:
          outer: f1=msg_type, f2=1, f4=inner_bytes
          inner: f1=device_id, f2=nonce, ..., f65=device_info_bytes
          f65:   f7=hw_version, f8=firmware, f9=device_name, f10=sensor_data_bytes
          f10:   f1-f13 = sensor readings

        Returns (sensor_data_dict, firmware_str, device_name_str).
        """
        try:
            outer = decode_fields(data)
        except (ValueError, struct.error) as e:
            _LOGGER.debug("Failed to decode outer envelope: %s", e)
            return None, None, None

        inner_data = get_field(outer, 4)
        if not isinstance(inner_data, bytes):
            return None, None, None

        try:
            inner = decode_fields(inner_data)
        except (ValueError, struct.error):
            return None, None, None

        # Look for field 65 (device info)
        f65_data = get_field(inner, 65)
        if not isinstance(f65_data, bytes):
            _LOGGER.debug("No field 65 in response (got fields: %s)",
                         [fn for fn, _, _ in inner if fn > 10])
            return None, None, None

        try:
            f65_fields = decode_fields(f65_data)
        except (ValueError, struct.error):
            return None, None, None

        # Extract firmware (f8) and device name (f9)
        firmware = None
        device_name = None
        f8 = get_field(f65_fields, 8)
        if isinstance(f8, bytes):
            firmware = f8.decode("utf-8", errors="replace")
        f9 = get_field(f65_fields, 9)
        if isinstance(f9, bytes):
            device_name = f9.decode("utf-8", errors="replace")

        # Extract sensor data from f10
        f10_data = get_field(f65_fields, 10)
        if not isinstance(f10_data, bytes) or len(f10_data) < 10:
            _LOGGER.debug("No sensor data in f65.f10 (f65 fields: %s)",
                         [fn for fn, _, _ in f65_fields])
            return None, firmware, device_name

        try:
            sensor_fields = decode_fields(f10_data)
        except (ValueError, struct.error):
            return None, firmware, device_name

        sensor_data = {}
        for fn, _, val in sensor_fields:
            if isinstance(val, int) and val > 0x7FFFFFFFFFFFFFFF:
                val = varint_to_signed32(val)
            sensor_data[fn] = val

        _LOGGER.debug(
            "Parsed discovery: firmware=%s, name=%s, sensors=%s",
            firmware, device_name, sensor_data,
        )
        # TEMP: dump raw sensor fields at WARNING level for temperature calibration
        _LOGGER.warning(
            "IVENT RAW f10 hex=%s fields=%s",
            f10_data.hex(),
            {fn: val for fn, _, val in sensor_fields},
        )
        return sensor_data, firmware, device_name

    def _sensor_data_to_status(
        self,
        sensor_data: dict,
        device_id_str: str,
        firmware: str | None = None,
        device_name: str | None = None,
    ) -> IVentDeviceStatus:
        """Convert raw protobuf sensor data to IVentDeviceStatus.

        Field mapping (reverse-engineered, some uncertain):
          f1  = extract/exhaust duct temp °C (changes over time)
          f2  = supply duct temp °C after heat exchange (stable)
          f3  = humidity %
          f4  = signed, dynamic — possibly fresh air intake temp
          f5  = signed, dynamic — unknown differential
          f6  = signed, dynamic — unknown differential
          f7  = mode (4=recovery, 1=supply, 2=exhaust)
          f8  = fan level (0=off, 1-2=low, 3=med, 4=high, 5=boost)
          f9  = 0 (unknown flag)
          f10 = setpoint or constant (does NOT change — not outdoor temp)
          f11 = flag (0 or 1)
          f12 = fan percentage (0-100, live value)
          f13 = signed, dynamic — unknown derived value
        """
        exhaust_temp = sensor_data.get(1)
        supply_temp = sensor_data.get(2)
        humidity = sensor_data.get(3)
        outdoor_temp = None
        target_temp = sensor_data.get(10)  # Confirmed: f10 = temperature setpoint

        mode_raw = sensor_data.get(7, 0)
        fan_level = sensor_data.get(8, 0)
        fan_pct = sensor_data.get(12, 0)

        fan_speed_name = FAN_SPEED_MAP.get(fan_level, "medium")
        if fan_pct == 0 and fan_level == 0:
            fan_speed_name = "off"

        mode_name = MODE_MAP.get(mode_raw, "recovery")
        is_on = fan_pct > 0 or fan_level > 0

        return IVentDeviceStatus(
            device_id=device_id_str,
            name=device_name or "i-Vent Rekuperator",
            is_on=is_on,
            fan_speed=fan_speed_name,
            mode=mode_name,
            supply_temp=float(supply_temp) if supply_temp is not None else None,
            exhaust_temp=float(exhaust_temp) if exhaust_temp is not None else None,
            outdoor_temp=float(outdoor_temp) if outdoor_temp is not None else None,
            indoor_temp=None,  # No reliable indoor ambient sensor identified yet
            co2=None,
            humidity=float(humidity) if humidity is not None else None,
            filter_status=None,
            firmware=firmware,
            target_temp=int(target_temp) if target_temp is not None else None,
        )

    async def discover(self) -> bool:
        """Send discovery and check if device responds."""
        await self.connect()
        pkt = self._build_packet(MSG_DISCOVERY_A)
        response = await self._send_and_receive(pkt, timeout=3.0)
        if response:
            _LOGGER.info("i-Vent device responded to discovery (%d bytes)", len(response))
            return True
        _LOGGER.warning("No response to discovery from %s", self._host)
        return False

    async def scan_network(self, subnet_prefix: str = "192.168.1", start: int = 1, end: int = 254) -> list[dict]:
        """Scan the network for all i-Vent devices.

        Uses connected UDP sockets (one per IP) because HA runs in Docker
        and NAT requires connected sockets to route responses back.

        Temporarily disconnects the main socket, scans each IP sequentially,
        then reconnects the original socket.

        Returns list of dicts with device info for each discovered device.
        """
        # 1. Close existing socket so we can rebind port 1028
        was_connected = self._connected
        original_host = self._host
        await self.disconnect()
        await asyncio.sleep(0.1)

        devices = {}
        total = end - start + 1

        _LOGGER.warning("Network scan: probing %s.%d-%d on UDP %d (%d IPs)",
                         subnet_prefix, start, end, UDP_PORT, total)

        for i in range(start, end + 1):
            ip = f"{subnet_prefix}.{i}"
            try:
                # Create connected socket to this specific IP
                loop = asyncio.get_running_loop()
                transport, protocol = await loop.create_datagram_endpoint(
                    IVentUdpProtocol,
                    local_addr=("0.0.0.0", UDP_PORT),
                    remote_addr=(ip, UDP_PORT),
                )

                # Send both generic (no device_id) and device-specific discovery
                # Generic discovery should make any i-Vent device respond
                generic_pkt = self._build_broadcast_discovery()
                transport.sendto(generic_pkt)

                # Wait for response (short timeout per IP)
                result = await protocol.receive(timeout=0.3)

                # If no response to generic, try device-specific
                if result is None:
                    specific_pkt = self._build_packet(MSG_DISCOVERY_A)
                    transport.sendto(specific_pkt)
                    result = await protocol.receive(timeout=0.3)

                transport.close()
                # Small delay for socket cleanup before rebind
                await asyncio.sleep(0.02)

                if result is None:
                    continue

                data, addr = result
                sd, fw, dn = self._parse_discovery_response(data)

                # Get device ID from response
                try:
                    outer = decode_fields(data)
                    inner_data = get_field(outer, 4)
                    if isinstance(inner_data, bytes):
                        inner = decode_fields(inner_data)
                        dev_id_raw = get_field(inner, 1)
                        dev_id = hex(dev_id_raw) if isinstance(dev_id_raw, int) else "unknown"
                    else:
                        dev_id = "unknown"
                except (ValueError, struct.error):
                    dev_id = "unknown"

                if dev_id != "unknown":
                    devices[ip] = {
                        "ip": ip,
                        "device_id": dev_id,
                        "device_id_int": dev_id_raw if isinstance(dev_id_raw, int) else 0,
                        "name": dn or "unknown",
                        "firmware": fw,
                        "sensors": sd or {},
                    }
                    _LOGGER.warning("Network scan: FOUND device at %s — %s (ID: %s, FW: %s, sensors: %s)",
                                    ip, dn or "unknown", dev_id, fw or "unknown", sd or {})

            except OSError as e:
                # Expected for most IPs (connection refused, network unreachable, etc.)
                _LOGGER.debug("Network scan: %s — %s", ip, e)
                await asyncio.sleep(0.01)
            except Exception as e:
                _LOGGER.debug("Network scan: %s — unexpected: %s", ip, e)
                await asyncio.sleep(0.01)

            if (i - start + 1) % 50 == 0:
                _LOGGER.warning("Network scan: probed %d/%d IPs, found %d device(s) so far",
                                i - start + 1, total, len(devices))

        # 2. Reconnect original socket
        self._host = original_host
        if was_connected:
            await self.connect()

        result = list(devices.values())
        _LOGGER.warning("Network scan complete: found %d device(s): %s", len(result), result)
        return result

    async def get_status(self, device_id: str) -> IVentDeviceStatus:
        """Get current status by sending discovery and parsing response.

        The discovery response (msg type 257) contains sensor data in
        field 65 -> field 10. This is the primary data source.
        """
        await self.connect()

        # Send discovery packet (primary data source)
        pkt = self._build_packet(MSG_DISCOVERY_A)
        self._protocol.drain_queue()
        self._transport.sendto(pkt)

        # Collect responses, looking for one with sensor data
        sensor_data = None
        firmware = None
        device_name = None
        deadline = time.monotonic() + UDP_TIMEOUT

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            result = await self._protocol.receive(timeout=min(remaining, 1.0))
            if result is None:
                continue
            data, addr = result
            _LOGGER.debug("Received %d bytes from %s", len(data), addr)
            sd, fw, dn = self._parse_discovery_response(data)
            if sd:
                sensor_data = sd
                firmware = fw
                device_name = dn
                break

        if sensor_data is None:
            # Retry once with a heartbeat first then discovery
            _LOGGER.debug("No sensor data in first attempt, retrying with heartbeat + discovery")
            hb_pkt = self._build_packet(MSG_HEARTBEAT, command_field=96, command_data=b"")
            self._transport.sendto(hb_pkt)
            await asyncio.sleep(MSG_DELAY)

            self._protocol.drain_queue()
            self._transport.sendto(pkt)

            result = await self._protocol.receive(timeout=3.0)
            if result:
                data, addr = result
                sd, fw, dn = self._parse_discovery_response(data)
                if sd:
                    sensor_data = sd
                    firmware = fw
                    device_name = dn

        if sensor_data is None:
            _LOGGER.warning("No sensor data received from %s", self._host)
            raise ConnectionError(f"No response from i-Vent device at {self._host}")

        # Cache sensor data for control commands
        self._last_sensor_data = sensor_data

        return self._sensor_data_to_status(sensor_data, device_id, firmware, device_name)

    def _build_schedule_settings(
        self,
        mode: int,
        setpoint: int,
        fan_level: int,
        direction: int,
        sub_mode: int,
    ) -> bytes:
        """Build the f88.f8 settings block for a schedule command.

        Args:
            mode: HVAC mode (0=ventilation, 2=recovery)
            setpoint: Temperature setpoint in °C (16-33)
            fan_level: Fan level (1=low, 2=medium+)
            direction: Air direction (1=supply, 2=extract)
            sub_mode: Sub-mode correlating with direction (1 or 2)
        """
        now = int(time.time())
        f8 = b""
        f8 += encode_field_varint(SCHED_MODE, mode)
        f8 += encode_field_varint(SCHED_SETPOINT, setpoint)
        f8 += encode_field_varint(SCHED_DIRECTION, direction)
        f8 += encode_field_varint(SCHED_FAN_LEVEL, fan_level)
        f8 += encode_field_varint(SCHED_SUB_MODE, sub_mode)
        f8 += encode_field_varint(SCHED_START_TIME, now + 3600)  # 1h ahead
        f8 += encode_field_varint(SCHED_END_TIME, now)           # "now"
        f8 += encode_field_varint(SCHED_FLAG_A, 65)              # 0x41
        f8 += encode_field_varint(SCHED_FLAG_B, 65)              # 0x41
        return f8

    def _build_schedule_payload(
        self,
        mode: int,
        setpoint: int,
        fan_level: int,
        direction: int,
        sub_mode: int,
        schedule_nonce: int = 0,
    ) -> bytes:
        """Build the f88 payload wrapping the settings block.

        IMPORTANT: The device expects specific wire types:
          f88.f1 = fixed32 (wire type 5), NOT varint
          f88.f99 = fixed64 (wire type 1), NOT varint
        Using wrong wire types causes the device to silently drop the packet.

        Args:
            schedule_nonce: Incrementing value per schedule pair (0 for first).
        """
        f8_block = self._build_schedule_settings(mode, setpoint, fan_level, direction, sub_mode)
        f88 = b""
        f88 += encode_field_fixed32(1, schedule_nonce)  # Must be fixed32, not varint
        f88 += encode_field_bytes(8, f8_block)
        f88 += encode_field_fixed64(99, 258)  # Must be fixed64, not varint
        return f88

    async def send_schedule(
        self,
        mode: int,
        setpoint: int,
        fan_level: int,
    ) -> None:
        """Send a schedule/settings command (type 4370) to the device.

        The app sends 6 packets per command: 3 schedule slot nonces × 2 directions.
        The nonces are persistent slot IDs discovered from PCAP analysis.
        Both extract (dir=2) and supply (dir=1) must be sent for each nonce.
        """
        await self.connect()

        for nonce in SCHEDULE_NONCES:
            for direction in (2, 1):  # extract first, then supply
                # sub_mode must match direction (from PCAP analysis)
                sub_mode = direction
                f88 = self._build_schedule_payload(
                    mode=mode, setpoint=setpoint, fan_level=fan_level,
                    direction=direction, sub_mode=sub_mode, schedule_nonce=nonce,
                )
                pkt = self._build_packet(MSG_SCHEDULE, command_field=88, command_data=f88)
                resp = await self._send_and_receive(pkt, timeout=2.0)
                _LOGGER.warning(
                    "IVENT send_schedule: nonce=%d dir=%d sub=%d resp=%s resp_hex=%s",
                    nonce, direction, sub_mode,
                    f"{len(resp)}B" if resp else "NONE/TIMEOUT",
                    resp.hex()[:100] if resp else "N/A",
                )
                await asyncio.sleep(0.1)

        _LOGGER.warning(
            "IVENT send_schedule: sent 6 pkts mode=%d setpoint=%d fan=%d",
            mode, setpoint, fan_level,
        )

    async def _send_toggle(self, on: bool) -> bytes | None:
        """Send a 4358 device state toggle command (on/off).

        The app uses these to apply schedule changes:
          f72.f1 = 0 (off) or 1 (on), varint
          f72.f99 = 2, fixed64
        """
        f72 = encode_field_varint(1, 1 if on else 0)
        f72 += encode_field_fixed64(99, 2)
        pkt = self._build_packet(MSG_DEVICE_STATE, command_field=72, command_data=f72)
        resp = await self._send_and_receive(pkt, timeout=2.0)
        _LOGGER.warning(
            "IVENT _send_toggle: on=%s pkt_hex=%s resp=%s resp_hex=%s",
            on,
            pkt.hex()[:120],
            f"{len(resp)}B" if resp else "NONE/TIMEOUT",
            resp.hex()[:120] if resp else "N/A",
        )
        return resp

    async def _send_status_readback(self) -> bytes | None:
        """Send a 4358 status readback command (f72.f99=16).

        The app sends this before toggle commands to read current device state.
        """
        f72 = encode_field_varint(99, 16)
        pkt = self._build_packet(MSG_DEVICE_STATE, command_field=72, command_data=f72)
        resp = await self._send_and_receive(pkt, timeout=2.0)
        _LOGGER.warning(
            "IVENT status_readback: resp=%s resp_hex=%s",
            f"{len(resp)}B" if resp else "NONE/TIMEOUT",
            resp.hex()[:120] if resp else "N/A",
        )
        return resp

    async def _apply_schedule(self) -> None:
        """Toggle device off then on to apply pending schedule changes.

        The i-Vent device requires a power cycle via 4358 commands
        after schedule (4370) changes for them to take immediate effect.
        Precede with status readback as the app does.
        """
        _LOGGER.debug("Applying schedule with readback + off/on toggle")
        await self._send_status_readback()
        await asyncio.sleep(0.3)
        await self._send_toggle(on=False)
        await asyncio.sleep(0.5)
        await self._send_toggle(on=True)

    def _get_current_settings(self) -> tuple[int, int, int]:
        """Get current mode, setpoint, and fan_level from cached sensor data.

        Returns (mode_proto, setpoint, fan_level) where:
          mode_proto: 0=ventilation, 2=recovery (SCHED_MODE values)
          setpoint: from sensor f10
          fan_level: mapped from sensor f8 to schedule fan_level
        """
        if not self._last_sensor_data:
            return SCHED_MODE_RECOVERY, 21, 1  # Safe defaults

        mode_raw = self._last_sensor_data.get(7, 4)  # sensor f7 = mode
        setpoint = self._last_sensor_data.get(10, 21)  # sensor f10 = setpoint

        # Map sensor mode (0=off, 1=supply, 2=exhaust, 4=recovery) to schedule mode
        if mode_raw == 4:
            sched_mode = SCHED_MODE_RECOVERY
        else:
            sched_mode = SCHED_MODE_VENTILATION

        # Map sensor fan level (f8: 0-5) to schedule fan level (1-2)
        fan_raw = self._last_sensor_data.get(8, 1)
        if fan_raw <= 2:
            sched_fan = 1
        else:
            sched_fan = 2

        return sched_mode, setpoint, sched_fan

    async def set_fan_speed(self, device_id: str, speed: str) -> bool:
        """Set fan speed by sending schedule + toggle to apply."""
        proto_val = FAN_SPEED_TO_PROTO.get(speed)
        if proto_val is None:
            _LOGGER.error("Unknown fan speed: %s", speed)
            return False

        sched_mode, setpoint, _ = self._get_current_settings()

        # Map named speed to schedule fan_level
        if speed in ("off", "low"):
            sched_fan = 1
        else:
            sched_fan = 2

        await self.send_schedule(mode=sched_mode, setpoint=setpoint, fan_level=sched_fan)
        await self._apply_schedule()
        return True

    async def set_mode(self, device_id: str, mode: str) -> bool:
        """Set operating mode by sending schedule + toggle to apply."""
        if mode == "recovery":
            sched_mode = SCHED_MODE_RECOVERY
        elif mode in ("supply", "exhaust"):
            sched_mode = SCHED_MODE_VENTILATION
        else:
            _LOGGER.error("Unknown mode: %s", mode)
            return False

        _, setpoint, sched_fan = self._get_current_settings()
        await self.send_schedule(mode=sched_mode, setpoint=setpoint, fan_level=sched_fan)
        await self._apply_schedule()
        return True

    async def set_temperature(self, device_id: str, temperature: float) -> bool:
        """Set target temperature by sending schedule + toggle to apply."""
        setpoint = max(16, min(33, int(round(temperature))))
        sched_mode, _, sched_fan = self._get_current_settings()
        await self.send_schedule(mode=sched_mode, setpoint=setpoint, fan_level=sched_fan)
        await self._apply_schedule()
        return True

    async def turn_on(self, device_id: str) -> bool:
        """Turn on the unit."""
        _, setpoint, sched_fan = self._get_current_settings()
        await self.send_schedule(
            mode=SCHED_MODE_RECOVERY, setpoint=setpoint, fan_level=max(sched_fan, 1),
        )
        await self._send_toggle(on=True)
        return True

    async def turn_off(self, device_id: str) -> bool:
        """Turn off the unit."""
        _, setpoint, _ = self._get_current_settings()
        await self.send_schedule(
            mode=SCHED_MODE_VENTILATION, setpoint=setpoint, fan_level=1,
        )
        await self._send_toggle(on=False)
        return True
