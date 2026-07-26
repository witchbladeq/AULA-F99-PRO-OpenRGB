#!/usr/bin/env python3
"""AULA F99 Pro HID RGB client + CLI.

USB IDs from Dev/kb/F99Pro/KB.ini:
  Wired    258A:010C
  Wireless 3554:FA09

Protocol: 20-byte HID output reports, report ID 0x13
(SinoWealth / AULA F87 family — same IDs as F99).

Requires: pip install hidapi
Close OemDrv.exe before use.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    import hid
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install hidapi: pip install hidapi") from exc

WIRED_VID, WIRED_PID = 0x258A, 0x010C
WIRELESS_VID, WIRELESS_PID = 0x3554, 0xFA09

REPORT_ID = 0x13
CMD_READ = 0x44
CMD_WRITE = 0x04
CMD_COLOR = 0x09
CMD_PERKEY = 0x02
CMD_SAVE = 0x0A
CMD_STREAM = 0x88

SUB_CONFIG = 0x0A
SUB_CONFIRM = 0x01
SUB_PALETTE = 0x25
SUB_PERKEY = 0x1C

# Software effect index -> name (text.xml tc_kb_ledN)
EFFECTS: dict[int, str] = {
    0: "OFF",
    1: "Fixed_on",
    2: "Respire",
    3: "Rainbow",
    4: "Flash_away",
    5: "Raindrops",
    6: "Rainbow_wheel",
    7: "Ripples_shining",
    8: "Stars_twinkle",
    9: "Shadow_disappear",
    10: "Retro_snake",
    11: "Neon_stream",
    12: "Reaction",
    13: "Sine_wave",
    14: "Retinue scanning",
    15: "Rotating windmill",
    16: "Colorful waterfall",
    17: "Blossoming",
    18: "Rotating storm",
    21: "Self-define",
}

# From F99Pro/KB.ini [KEY] — (name, led_index) in OpenRGB channel order
KEYS: list[tuple[str, int]] = [
    ("Esc", 0), ("F1", 12), ("F2", 18), ("F3", 24), ("F4", 30),
    ("F5", 36), ("F6", 42), ("F7", 48), ("F8", 54), ("F9", 60),
    ("F10", 66), ("F11", 72), ("F12", 78),
    ("`", 1), ("1", 7), ("2", 13), ("3", 19), ("4", 25), ("5", 31),
    ("6", 37), ("7", 43), ("8", 49), ("9", 55), ("0", 61), ("-", 67),
    ("=", 73), ("Backspace", 79),
    ("Delete", 84), ("ScrLk", 90), ("NumLock", 91), ("Num/", 97),
    ("Num*", 103), ("Num-", 109),
    ("Tab", 2), ("Q", 8), ("W", 14), ("E", 20), ("R", 26), ("T", 32),
    ("Y", 38), ("U", 44), ("I", 50), ("O", 56), ("P", 62), ("[", 68),
    ("]", 74), ("\\", 80), ("Calc", 96), ("Home", 85),
    ("Num7", 92), ("Num8", 98), ("Num9", 104), ("Num+", 110),
    ("CapsLock", 3), ("A", 9), ("S", 15), ("D", 21), ("F", 27), ("G", 33),
    ("H", 39), ("J", 45), ("K", 51), ("L", 57), (";", 63), ("'", 69),
    ("Enter", 81), ("Num4", 93), ("Num5", 99), ("Num6", 105),
    ("LShift", 4), ("Z", 10), ("X", 16), ("C", 22), ("V", 28), ("B", 34),
    ("N", 40), ("M", 46), (",", 52), (".", 58), ("/", 64), ("RShift", 82),
    ("Up", 88), ("Num1", 94), ("Num2", 100), ("Num3", 106),
    ("LCtrl", 5), ("LWin", 11), ("LAlt", 17), ("Space", 35), ("RAlt", 53),
    ("FN", 59), ("PgDn", 87), ("Left", 83), ("Down", 89), ("Right", 95),
    ("Num0", 101), ("Num.", 107), ("NumEnter", 112), ("PgUp", 86),
    ("Wheel", 108),
]

NUM_OPENRGB_LEDS = len(KEYS)  # 100

# Keyboard LEDs look brighter/cooler than other devices. Scale channels so
# OpenRGB (255, 150, 38) lands as (254, 92, 16) on the hardware.
COLOR_GAIN_DEFAULT = (254 / 255, 92 / 150, 16 / 38)


def correct_rgb(
    r: int,
    g: int,
    b: int,
    gain: tuple[float, float, float] = COLOR_GAIN_DEFAULT,
) -> tuple[int, int, int]:
    """Apply per-channel gain so keyboard tone matches other devices."""
    return (
        max(0, min(255, round(r * gain[0]))),
        max(0, min(255, round(g * gain[1]))),
        max(0, min(255, round(b * gain[2]))),
    )

# Factory config / palette templates (15-byte payloads) from AULA F87 OEM captures
# — same SinoWealth protocol as F99 (258A:010C / 3554:FA09).
_CFG_TEMPLATE = [
    bytes([0x0E, 0x00, 0x03, 0x03, 0x01, 0x00, 0x00, 0x04, 0x04, 0x07, 0x00, 0x00, 0x20, 0x03, 0x00]),
    bytes([0x0E, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02, 0x01, 0x00, 0xFF, 0x0A, 0x00, 0x00, 0x00]),
    bytes([0x0E, 0x01, 0x00, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    bytes([0x0E, 0xFF, 0xFF, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47]),
    bytes([0x0E, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47]),
    bytes([0x0E, 0x04, 0x47, 0x04, 0x47, 0x04, 0x47, 0x04, 0x37, 0x04, 0x37, 0x04, 0x37, 0x04, 0x37]),
    bytes([0x0E, 0x07, 0x47, 0x07, 0x47, 0x07, 0x44, 0x07, 0x44, 0x07, 0x44, 0x07, 0x44, 0x07, 0x44]),
    bytes([0x0E, 0x07, 0x44, 0x07, 0x44, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04]),
    bytes([0x02, 0x5A, 0xA5, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
]

# First 21 OEM palette payloads; seq 21–35 = zeros; seq 36 = trailer
_PAL_TEMPLATE = [
    bytes([0x0E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
    bytes([0x0E, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00]),
    bytes([0x0E, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]),
    bytes([0x0E, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
]
_PAL_ZEROS = bytes([0x0E] + [0x00] * 14)
_PAL_LAST = bytes([0x08, 0x00, 0x00, 0x5A, 0xA5, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def checksum(data: bytes | bytearray) -> int:
    return sum(data[:19]) & 0xFF


def make_frag(cmd: int, sub: int, seq: int, payload: bytes | bytearray = b"") -> bytes:
    buf = bytearray(20)
    buf[0] = REPORT_ID
    buf[1] = cmd & 0xFF
    buf[2] = sub & 0xFF
    buf[3] = seq & 0xFF
    pl = bytes(payload)[:15]
    buf[4 : 4 + len(pl)] = pl
    buf[19] = checksum(buf)
    return bytes(buf)


def hex_bytes(data: bytes | bytearray) -> str:
    return " ".join(f"{b:02X}" for b in data)


@dataclass
class HidInfo:
    path: bytes
    vid: int
    pid: int
    product: str
    usage_page: int
    interface: int


def enumerate_aula() -> list[HidInfo]:
    out: list[HidInfo] = []
    for d in hid.enumerate():
        vid = d.get("vendor_id") or 0
        pid = d.get("product_id") or 0
        if (vid, pid) not in (
            (WIRED_VID, WIRED_PID),
            (WIRELESS_VID, WIRELESS_PID),
        ):
            continue
        out.append(
            HidInfo(
                path=d["path"],
                vid=vid,
                pid=pid,
                product=d.get("product_string") or "",
                usage_page=d.get("usage_page") or 0,
                interface=d.get("interface_number") if d.get("interface_number") is not None else -1,
            )
        )
    return out


def pick_control_device(prefer: str = "auto") -> HidInfo:
    """Prefer vendor usage pages FF02/FF04 (wireless) or FF00+ (wired)."""
    devs = enumerate_aula()
    if not devs:
        raise RuntimeError(
            "AULA F99 not found. Plug USB-C or 2.4G receiver, close OemDrv.exe."
        )

    def score(info: HidInfo) -> tuple:
        vendor = 1 if 0xFF00 <= info.usage_page <= 0xFFFF else 0
        prefer_match = 0
        if prefer == "wired" and info.vid == WIRED_VID:
            prefer_match = 1
        if prefer == "wireless" and info.vid == WIRELESS_VID:
            prefer_match = 1
        if prefer == "auto":
            prefer_match = 1
        # Prefer FF02/FF04 as documented for wireless
        page_rank = 2 if info.usage_page in (0xFF02, 0xFF04, 0xFF00) else vendor
        return (prefer_match, page_rank, -info.interface)

    ranked = sorted(devs, key=score, reverse=True)
    # Must be a vendor page for control
    for info in ranked:
        if 0xFF00 <= info.usage_page <= 0xFFFF:
            return info
    raise RuntimeError(
        "Found AULA device but no vendor HID collection (0xFFxx). "
        f"Seen: {[(hex(d.vid), hex(d.pid), hex(d.usage_page)) for d in devs]}"
    )


class Keyboard:
    def __init__(
        self,
        prefer: str = "auto",
        verbose: bool = False,
        *,
        color_gain: Optional[tuple[float, float, float]] = COLOR_GAIN_DEFAULT,
    ) -> None:
        self.verbose = verbose
        self.color_gain = color_gain
        self.info = pick_control_device(prefer)
        self.dev = hid.device()
        self.dev.open_path(self.info.path)
        self.dev.set_nonblocking(False)
        mode = "wired" if self.info.vid == WIRED_VID else "wireless"
        print(
            f"Opened {mode} {self.info.vid:04X}:{self.info.pid:04X} "
            f"usage_page=0x{self.info.usage_page:04X} iface={self.info.interface}"
        )

    def _tone(self, r: int, g: int, b: int) -> tuple[int, int, int]:
        if self.color_gain is None:
            return (r & 0xFF, g & 0xFF, b & 0xFF)
        return correct_rgb(r, g, b, self.color_gain)

    def close(self) -> None:
        try:
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "Keyboard":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def drain(self) -> None:
        """Clear leftover HID input (echoes) so the next read_config is clean."""
        for _ in range(64):
            data = self.dev.read(64, timeout_ms=1)
            if not data:
                break

    def write_frag(self, frag: bytes, wait_echo: bool = True) -> Optional[bytes]:
        if self.verbose:
            print(f"TX {hex_bytes(frag)}")
        n = self.dev.write(frag)
        if n < 0:
            raise RuntimeError("HID write failed")
        if not wait_echo:
            return None
        deadline = time.time() + 0.35
        while time.time() < deadline:
            data = self.dev.read(64, timeout_ms=30)
            if data:
                raw = bytes(data)
                if self.verbose:
                    print(f"RX {hex_bytes(raw[:20])}")
                return raw
        return None

    def read_config(self) -> tuple[list[bytearray], bool]:
        """Return (frags, complete). Incomplete wireless reads → pure OEM template."""
        self.drain()
        self.write_frag(make_frag(CMD_READ, SUB_CONFIRM, 0), wait_echo=False)
        frags: dict[int, bytearray] = {}
        deadline = time.time() + 2.5
        while time.time() < deadline and len(frags) < 10:
            data = self.dev.read(64, timeout_ms=100)
            if not data:
                continue
            raw = bytearray(data[:20])
            if len(raw) < 20:
                continue
            if raw[0] != REPORT_ID or raw[1] != CMD_READ:
                continue
            frags[raw[3]] = raw
            if self.verbose:
                print(f"RX cfg seq={raw[3]} {hex_bytes(raw)}")

        if len(frags) == 10:
            return [frags[i] for i in range(10)], True

        print(f"Warning: config read {len(frags)}/10 — using OEM template")
        out = [
            bytearray(make_frag(CMD_WRITE, SUB_CONFIG, i, _CFG_TEMPLATE[i]))
            for i in range(10)
        ]
        return out, False

    def write_config(self, frags: list[bytearray]) -> None:
        for i, f in enumerate(frags):
            f = bytearray(f)
            f[1] = CMD_WRITE
            if i == 0:
                f[8] = 0x01  # confirm
                f[14] = 0x00  # apply must be 0 on write
            f[19] = checksum(f)
            self.write_frag(bytes(f))
            frags[i] = f

    def write_palette(
        self,
        color: Optional[tuple[int, int, int]] = None,
        *,
        wait_echo: bool = True,
    ) -> None:
        """37-fragment palette. Custom RGB in seq=1 payload offsets 8/9/10 + 12=FF."""
        for seq in range(37):
            if seq < len(_PAL_TEMPLATE):
                payload = bytearray(_PAL_TEMPLATE[seq])
            elif seq == 36:
                payload = bytearray(_PAL_LAST)
            else:
                payload = bytearray(_PAL_ZEROS)

            if seq == 1 and color is not None:
                payload[8] = color[0] & 0xFF
                payload[9] = color[1] & 0xFF
                payload[10] = color[2] & 0xFF
                payload[12] = 0xFF
            self.write_frag(
                make_frag(CMD_COLOR, SUB_PALETTE, seq, payload),
                wait_echo=wait_echo,
            )

    def save(self, *, wait_echo: bool = True) -> None:
        self.write_frag(
            make_frag(CMD_SAVE, SUB_CONFIRM, 0, bytes([0x04, 0x07])),
            wait_echo=wait_echo,
        )

    def set_effect(
        self,
        effect: int,
        *,
        brightness: int = 4,
        speed: int = 2,
        color: Optional[tuple[int, int, int]] = (255, 0, 0),
        colorful: bool = False,
    ) -> None:
        if effect not in EFFECTS and effect != 0:
            raise ValueError(f"unknown effect {effect}")
        brightness = max(0, min(4, brightness))
        speed = max(0, min(4, speed))
        is_off = effect in (0, 20)
        if is_off:
            color = None
            colorful = False

        cfg, _complete = self.read_config()
        eff_byte = 0 if is_off else effect
        cfg[0][15] = eff_byte & 0xFF
        # 0x01 = custom/colorful; 0x03 = default
        cfg[0][17] = 0x01 if (colorful or color is not None) else 0x03
        if not is_off and 1 <= effect <= 18:
            self._patch_effect_params(cfg, effect, brightness, speed, colorful)
        self.write_config(cfg)
        # Always wait for echoes — wireless drops burst writes otherwise
        self.write_palette(color, wait_echo=True)
        self.save(wait_echo=True)
        print(
            f"Effect {effect}: {EFFECTS.get(effect, '?')} "
            f"bri={brightness} spd={speed} color={color}"
        )

    def set_solid(self, r: int, g: int, b: int, *, brightness: int = 4) -> None:
        """Whole-keyboard solid via Fixed_on + palette (echo-safe)."""
        r, g, b = self._tone(r, g, b)
        self.set_effect(1, brightness=brightness, color=(r, g, b), colorful=False)

    def set_solid_palette(self, r: int, g: int, b: int) -> None:
        """Faster solid update when Fixed_on is already active — palette + save only."""
        r, g, b = self._tone(r, g, b)
        self.write_palette((r, g, b), wait_echo=True)
        self.save(wait_echo=True)
        print(f"Palette color=({r}, {g}, {b})")

    @staticmethod
    def _patch_effect_params(
        cfg: list[bytearray], effect: int, bri: int, speed: int, colorful: bool
    ) -> None:
        # speed high nibble; low nibble 0x7=colorful 0x0=single
        speed_byte = ((speed & 0xF) << 4) | (0x7 if colorful else 0x0)
        if 1 <= effect <= 6:
            base = 7 + (effect - 1) * 2
            frag = cfg[4]
        elif 7 <= effect <= 13:
            base = 5 + (effect - 7) * 2
            frag = cfg[5]
        else:
            base = 5 + (effect - 14) * 2
            frag = cfg[6]
        if base + 1 < 19:
            frag[base] = bri & 0xFF
            frag[base + 1] = speed_byte

    def set_perkey(self, led_colors: dict[int, tuple[int, int, int]]) -> None:
        """Write self-define map (effect 21) then stream is not needed."""
        cfg, _ = self.read_config()
        cfg[0][15] = 21
        cfg[0][17] = 0x01
        self.write_config(cfg)

        planes = [bytearray(126), bytearray(126), bytearray(126)]
        for idx, (r, g, b) in led_colors.items():
            if 0 <= idx < 126:
                planes[0][idx] = r & 0xFF
                planes[1][idx] = g & 0xFF
                planes[2][idx] = b & 0xFF

        seq = 0
        for plane in planes:
            for block in range(9):
                chunk = plane[block * 14 : (block + 1) * 14]
                payload = bytearray(15)
                payload[0] = 0x0E
                payload[1 : 1 + len(chunk)] = chunk
                self.write_frag(make_frag(CMD_PERKEY, SUB_PERKEY, seq, payload))
                seq += 1
        trailer = bytes([0x06, 0x00, 0x00, 0x5A, 0xA5])
        self.write_frag(make_frag(CMD_PERKEY, SUB_PERKEY, 27, trailer))
        self.save()
        print(f"Per-key map written ({len(led_colors)} keys)")

    def arm_stream(self, warmup_idles: int = 4) -> None:
        """OEM audio-dance path: idle frames only, no config write."""
        idle = make_frag(CMD_STREAM, 0x01, 0, bytes([0x23]))
        for _ in range(warmup_idles):
            self.write_frag(idle, wait_echo=False)
            time.sleep(0.012)

    def arm_perkey(self) -> None:
        """Switch to self-define (effect 21) once for per-key streaming."""
        cfg, _ = self.read_config()
        cfg[0][15] = 21
        cfg[0][17] = 0x01
        self.write_config(cfg)
        self.save()
        print("Armed per-key mode (effect 21)")

    def fill(self, r: int, g: int, b: int) -> None:
        r, g, b = self._tone(r, g, b)
        colors = {led: (r, g, b) for _name, led in KEYS}
        self.set_perkey(colors)

    def stream_frame(
        self,
        led_colors: dict[int, tuple[int, int, int]],
        *,
        wait_echo: bool = False,
        quantize: int = 64,
    ) -> None:
        """Real-time RGB via CMD 0x88 color groups (OpenRGB / audio-dance path)."""
        from collections import defaultdict

        if self.color_gain is not None:
            led_colors = {
                i: self._tone(r, g, b) for i, (r, g, b) in led_colors.items()
            }

        if not led_colors:
            self.write_frag(
                make_frag(CMD_STREAM, 0x01, 0, bytes([0x23])), wait_echo=wait_echo
            )
            return

        q = max(1, quantize) if quantize else 1
        data = bytearray()
        while True:
            color_to_leds: dict[tuple[int, int, int], list[int]] = defaultdict(list)
            for idx, (r, g, b) in led_colors.items():
                if not (r or g or b):
                    continue
                rq = min(255, ((r + q // 2) // q) * q)
                gq = min(255, ((g + q // 2) // q) * q)
                bq = min(255, ((b + q // 2) // q) * q)
                color_to_leds[(rq, gq, bq)].append(idx & 0xFF)

            data = bytearray()
            for (r, g, b), indices in sorted(
                color_to_leds.items(), key=lambda kv: len(kv[1]), reverse=True
            ):
                for i in range(0, len(indices), 255):
                    chunk = indices[i : i + 255]
                    data.extend([r, g, b, len(chunk), *chunk])

            if len(data) <= 14 * 14 or q >= 256:
                break
            q *= 2

        if not data:
            self.write_frag(
                make_frag(CMD_STREAM, 0x01, 0, bytes([0x23])), wait_echo=wait_echo
            )
            return

        chunks: list[bytes] = []
        for i in range(0, len(data), 14):
            chunks.append(bytes(data[i : i + 14]))
            if len(chunks) >= 14:
                break

        n = len(chunks)
        for seq, chunk in enumerate(chunks):
            buf = bytearray(20)
            buf[0] = REPORT_ID
            buf[1] = CMD_STREAM
            buf[2] = n
            buf[3] = seq
            is_last = seq == n - 1
            buf[4] = (0x10 + len(chunk)) if is_last else 0x1E
            buf[5 : 5 + len(chunk)] = chunk
            buf[19] = checksum(buf)
            self.write_frag(bytes(buf), wait_echo=wait_echo)

    def stream_perkey_frame(
        self, led_colors: dict[int, tuple[int, int, int]], *, wait_echo: bool = False
    ) -> None:
        """Fire-and-forget 28-fragment per-key RGB frame (no save)."""
        if self.color_gain is not None:
            led_colors = {
                i: self._tone(r, g, b) for i, (r, g, b) in led_colors.items()
            }
        planes = [bytearray(126), bytearray(126), bytearray(126)]
        for idx, (r, g, b) in led_colors.items():
            if 0 <= idx < 126:
                planes[0][idx] = r & 0xFF
                planes[1][idx] = g & 0xFF
                planes[2][idx] = b & 0xFF

        seq = 0
        for plane in planes:
            for block in range(9):
                chunk = plane[block * 14 : (block + 1) * 14]
                payload = bytearray(15)
                payload[0] = 0x0E
                payload[1 : 1 + len(chunk)] = chunk
                self.write_frag(
                    make_frag(CMD_PERKEY, SUB_PERKEY, seq, payload), wait_echo=wait_echo
                )
                seq += 1
        trailer = bytes([0x06, 0x00, 0x00, 0x5A, 0xA5])
        self.write_frag(
            make_frag(CMD_PERKEY, SUB_PERKEY, 27, trailer), wait_echo=wait_echo
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AULA F99 Pro RGB control")
    p.add_argument("--wired", action="store_true")
    p.add_argument("--wireless", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--raw-color",
        action="store_true",
        help="Disable tone matching (send RGB unchanged)",
    )
    p.add_argument(
        "--gain",
        nargs=3,
        type=float,
        metavar=("R", "G", "B"),
        default=None,
        help="Override per-channel gain (default matches 255,150,38 -> 254,92,16)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List HID interfaces")
    sub.add_parser("effects", help="List effect IDs")
    sub.add_parser("keys", help="List key -> LED index")

    e = sub.add_parser("effect", help="Set hardware effect 0-18 / 21")
    e.add_argument("id", type=int)
    e.add_argument("--bri", type=int, default=4)
    e.add_argument("--speed", type=int, default=2)
    e.add_argument("--color", nargs=3, type=int, metavar=("R", "G", "B"), default=[255, 0, 0])
    e.add_argument("--colorful", action="store_true")

    c = sub.add_parser("color", help="Fixed_on with RGB")
    c.add_argument("r", type=int)
    c.add_argument("g", type=int)
    c.add_argument("b", type=int)
    c.add_argument("--bri", type=int, default=4)

    f = sub.add_parser("fill", help="Per-key fill all keys")
    f.add_argument("r", type=int)
    f.add_argument("g", type=int)
    f.add_argument("b", type=int)

    k = sub.add_parser("key", help="Set one key by name then apply fill map")
    k.add_argument("name")
    k.add_argument("r", type=int)
    k.add_argument("g", type=int)
    k.add_argument("b", type=int)

    sub.add_parser("off", help="Turn lighting off (effect 0)")

    r = sub.add_parser("raw", help="Send one 20-byte hex fragment")
    r.add_argument("hex")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    prefer = "auto"
    if args.wired:
        prefer = "wired"
    if args.wireless:
        prefer = "wireless"

    if args.cmd == "list":
        for d in enumerate_aula():
            print(
                f"{d.vid:04X}:{d.pid:04X} page=0x{d.usage_page:04X} "
                f"iface={d.interface} {d.product}"
            )
        return 0
    if args.cmd == "effects":
        for i, name in EFFECTS.items():
            print(f"{i:2d}  {name}")
        return 0
    if args.cmd == "keys":
        for i, (name, led) in enumerate(KEYS):
            print(f"{i:3d}  {name:12} LED={led}")
        return 0

    try:
        gain: Optional[tuple[float, float, float]]
        if args.raw_color:
            gain = None
        elif args.gain is not None:
            gain = (args.gain[0], args.gain[1], args.gain[2])
        else:
            gain = COLOR_GAIN_DEFAULT
        with Keyboard(prefer=prefer, verbose=args.verbose, color_gain=gain) as kb:
            if args.cmd == "effect":
                c = tuple(args.color)  # type: ignore[assignment]
                if kb.color_gain is not None and not args.colorful:
                    c = kb._tone(c[0], c[1], c[2])
                kb.set_effect(
                    args.id,
                    brightness=args.bri,
                    speed=args.speed,
                    color=c,
                    colorful=args.colorful,
                )
            elif args.cmd == "color":
                kb.set_solid(args.r, args.g, args.b, brightness=getattr(args, "bri", 4))
            elif args.cmd == "fill":
                kb.fill(args.r, args.g, args.b)
            elif args.cmd == "key":
                match = next((led for name, led in KEYS if name.lower() == args.name.lower()), None)
                if match is None:
                    print(f"Unknown key {args.name}", file=sys.stderr)
                    return 1
                kb.set_perkey({match: kb._tone(args.r, args.g, args.b)})
            elif args.cmd == "off":
                kb.set_effect(0)
            elif args.cmd == "raw":
                data = bytes.fromhex(args.hex.replace(" ", ""))
                if len(data) != 20:
                    raise ValueError("need exactly 20 bytes")
                kb.write_frag(data)
            else:
                return 2
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
