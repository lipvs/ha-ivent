"""Constants for the i-Vent integration."""

DOMAIN = "ivent"
MANUFACTURER = "i-Vent"

# Config keys
CONF_HOST = "host"
CONF_DEVICE_ID = "device_id"
CONF_SESSION_TOKEN = "session_token"
CONF_API_KEY = "api_key"
CONF_LOCATION_ID = "location_id"
CONF_GROUP_ID = "group_id"
CONF_GROUP_NAME = "group_name"

# Legacy config keys (for migration)
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# UDP protocol constants
UDP_PORT = 1028
DEFAULT_DEVICE_IP = "192.168.1.164"

# Protocol message types (outer field 1)
MSG_DISCOVERY_A = 257
MSG_DISCOVERY_B = 258
MSG_POLL_A = 267
MSG_POLL_B = 268
MSG_HEARTBEAT = 279
MSG_STATUS_PING = 281
MSG_DEVICE_STATE = 4358   # Quick command (f72): on/off toggle + status readback
MSG_SCHEDULE = 4370       # Settings write (f88): mode, setpoint, fan — the real control msg

# Protocol version
PROTOCOL_VERSION = 2

# Schedule/settings field numbers (inside f88.f8)
SCHED_MODE = 1          # 0=ventilation, 2=recovery
SCHED_SETPOINT = 2      # Temperature setpoint °C (16-33)
SCHED_DIRECTION = 3     # 1=supply, 2=extract (always send both)
SCHED_FAN_LEVEL = 4     # 1=low, 2=medium+
SCHED_SUB_MODE = 5      # Correlates with direction (1 or 2)
SCHED_START_TIME = 6    # Unix timestamp (schedule start)
SCHED_END_TIME = 7      # Unix timestamp (schedule end / "now")
SCHED_FLAG_A = 8        # Always 65 (0x41)
SCHED_FLAG_B = 9        # Always 65 (0x41)

# HVAC mode mapping for schedule commands
SCHED_MODE_RECOVERY = 2
SCHED_MODE_VENTILATION = 0

# Fan speed modes
SPEED_OFF = "off"
SPEED_LOW = "low"
SPEED_MEDIUM = "medium"
SPEED_HIGH = "high"
SPEED_BOOST = "boost"

FAN_SPEEDS = [SPEED_OFF, SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH, SPEED_BOOST]

# Cloud API work modes
CLOUD_MODE_OFF = "IVentWorkOff"
CLOUD_MODE_RECOVERY = "IVentRecuperation1"
CLOUD_MODE_SUPPLY = "IVentOn"  # basic ventilation

# Cloud API special modes
CLOUD_SPECIAL_OFF = "IVentSpecialOff"
CLOUD_SPECIAL_BOOST = "IVentBoost"

# Mapping: HA fan mode -> (cloud speed, cloud special_mode)
# Cloud API has speed 1-3, no separate "boost" speed — boost is a special_mode
CLOUD_FAN_MODE_MAP = {
    "off": (1, CLOUD_SPECIAL_OFF),       # turn off via work_mode instead
    "low": (1, CLOUD_SPECIAL_OFF),
    "medium": (2, CLOUD_SPECIAL_OFF),
    "high": (3, CLOUD_SPECIAL_OFF),
    "boost": (3, CLOUD_SPECIAL_BOOST),
}

# Reverse mapping: (cloud speed, cloud special_mode) -> HA fan mode
CLOUD_SPEED_TO_FAN = {
    (1, False): "low",
    (2, False): "medium",
    (3, False): "high",
    (1, True): "boost",
    (2, True): "boost",
    (3, True): "boost",
}

# Update interval in seconds (poll every 30s for local UDP)
UPDATE_INTERVAL = 30
# Cloud poll interval (slower to avoid rate limits)
CLOUD_UPDATE_INTERVAL = 60
