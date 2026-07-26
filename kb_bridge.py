#!/usr/bin/env python3
"""OpenRGB E1.31 bridge for AULA F99 Pro.

Default: ONE color for the whole keyboard (average of OpenRGB LEDs).
That matches a static color in OpenRGB. Rainbow OpenRGB effects still
collapse to one muddy color — use --per-key only if you want per-key mapping.

  python kb_bridge.py
  python kb_bridge.py --rgb-order bgr
  python kb_bridge.py --per-key
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import time
from typing import Optional

from kb import KEYS, Keyboard, NUM_OPENRGB_LEDS, COLOR_GAIN_DEFAULT, correct_rgb

E131_PORT = 5568
ACN_PID = b"ASC-E1.17\x00\x00\x00"
# Solid path does full HID round-trips; keep this gentle on wireless
MIN_INTERVAL_SOLID = 0.25
MIN_INTERVAL_PERKEY = 0.05

RGB_ORDERS = {
    "rgb": (0, 1, 2),
    "rbg": (0, 2, 1),
    "grb": (1, 0, 2),
    "gbr": (1, 2, 0),
    "brg": (2, 0, 1),
    "bgr": (2, 1, 0),
}


def parse_e131(data: bytes) -> Optional[tuple[int, bytes]]:
    if len(data) < 126 or data[4:16] != ACN_PID:
        return None
    universe = struct.unpack("!H", data[113:115])[0]
    return universe, data[126:]


def apply_order(r: int, g: int, b: int, order: str) -> tuple[int, int, int]:
    vals = (r, g, b)
    i0, i1, i2 = RGB_ORDERS[order]
    return vals[i0], vals[i1], vals[i2]


def collapse_color(
    colors: dict[int, tuple[int, int, int]], mode: str
) -> tuple[int, int, int]:
    """Pick one RGB for the whole keyboard.

    Prefer the most common non-black color (static OpenRGB). Fall back to
    average when OpenRGB is running a multi-color effect.
    """
    vals = [c for c in colors.values() if c != (0, 0, 0)]
    if not vals:
        return (0, 0, 0)
    if mode == "first":
        return vals[0]

    # majority vote among quantized colors (ignore tiny noise)
    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b in vals:
        key = (r & ~7, g & ~7, b & ~7)
        buckets[key] = buckets.get(key, 0) + 1
    best = max(buckets.items(), key=lambda kv: kv[1])
    # If one color owns most keys → solid OpenRGB paint
    if best[1] >= max(3, len(vals) * 0.4):
        return best[0]

    if mode == "majority":
        return best[0]

    n = len(vals)
    return (
        sum(c[0] for c in vals) // n,
        sum(c[1] for c in vals) // n,
        sum(c[2] for c in vals) // n,
    )


class Bridge:
    def __init__(
        self,
        kb: Keyboard,
        *,
        universe: int,
        start_channel: int,
        interval: float,
        rgb_order: str,
        per_key: bool,
        collapse: str,
    ):
        self.kb = kb
        self.universe = universe
        self.start_channel = start_channel
        self.interval = interval
        self.rgb_order = rgb_order
        self.per_key = per_key
        self.collapse = collapse
        self._pending: Optional[dict[int, tuple[int, int, int]]] = None
        self._last_rgb: Optional[tuple[int, int, int]] = None
        self._last_map: Optional[tuple] = None
        self._last_t = 0.0
        self._task: Optional[asyncio.Task] = None
        self._busy = False
        self._solid_ready = False
        self.packets = 0
        self._logged = False
        self._warned_rainbow = False

    def handle(self, data: bytes) -> None:
        parsed = parse_e131(data)
        if parsed is None:
            return
        univ, dmx = parsed
        if univ != self.universe:
            return
        self.packets += 1
        idx = self.start_channel - 1

        raw: dict[int, tuple[int, int, int]] = {}
        for i, (_name, led) in enumerate(KEYS):
            off = idx + i * 3
            if off + 2 >= len(dmx):
                break
            r, g, b = apply_order(dmx[off], dmx[off + 1], dmx[off + 2], self.rgb_order)
            raw[led] = (r, g, b)

        if not raw:
            return

        if self.per_key:
            colors = raw
            nonzero = {c for c in raw.values() if c != (0, 0, 0)}
            if len(nonzero) > 12 and not self._warned_rainbow:
                print(
                    "Note: OpenRGB is sending many different key colors "
                    "(rainbow/effect). That is expected with --per-key."
                )
                self._warned_rainbow = True
        else:
            fill = collapse_color(raw, self.collapse)
            colors = {led: fill for _n, led in KEYS}
            nonzero = {c for c in raw.values() if c != (0, 0, 0)}
            if len(nonzero) > 12 and not self._warned_rainbow:
                print(
                    "Note: OpenRGB effect paints many colors; collapsing to "
                    f"one RGB={fill}. Use a static color, or --per-key."
                )
                self._warned_rainbow = True

        if not self._logged:
            sample = next(iter(colors.values()))
            print(
                f"OpenRGB -> keyboard RGB={sample}  "
                f"order={self.rgb_order}  "
                f"{'per-key' if self.per_key else 'single-color'}"
            )
            self._logged = True

        self._pending = colors
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush())

    async def _flush(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            pending = self._pending
            if pending is None:
                return
            if self._busy:
                continue
            self._pending = None

            now = time.monotonic()
            if self.per_key:
                key = tuple(sorted(pending.items()))
                if key == self._last_map and (now - self._last_t) < 0.35:
                    continue
            else:
                rgb = next(iter(pending.values()))
                if rgb == self._last_rgb:
                    continue

            self._busy = True
            try:
                if self.per_key:
                    await asyncio.to_thread(
                        self.kb.stream_perkey_frame, pending, wait_echo=False
                    )
                    self._last_map = tuple(sorted(pending.items()))
                else:
                    rgb = next(iter(pending.values()))
                    if not self._solid_ready:
                        # Full Fixed_on + palette once (must wait for echoes)
                        await asyncio.to_thread(
                            self.kb.set_solid, rgb[0], rgb[1], rgb[2]
                        )
                        self._solid_ready = True
                    else:
                        # Palette-only update — much faster, still echo-safe
                        await asyncio.to_thread(
                            self.kb.set_solid_palette, rgb[0], rgb[1], rgb[2]
                        )
                    self._last_rgb = rgb
                    print(f"Applied solid RGB={rgb}")
                self._last_t = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                print(f"HID update failed: {exc}")
                self._solid_ready = False
            finally:
                self._busy = False


class Proto(asyncio.DatagramProtocol):
    def __init__(self, bridge: Bridge):
        self.bridge = bridge

    def datagram_received(self, data: bytes, _addr) -> None:
        self.bridge.handle(data)


async def run(args: argparse.Namespace) -> int:
    prefer = "wireless" if args.wireless else ("wired" if args.wired else "auto")
    if args.raw_color:
        gain = None
    elif args.gain is not None:
        gain = (args.gain[0], args.gain[1], args.gain[2])
    else:
        gain = COLOR_GAIN_DEFAULT
    kb = Keyboard(prefer=prefer, verbose=args.verbose, color_gain=gain)

    try:
        if args.per_key:
            kb.arm_perkey()
        else:
            # Arm Fixed_on once with black; later OpenRGB colors update palette only
            kb.set_solid(0, 0, 0)
    except Exception as exc:  # noqa: BLE001
        print(f"Arm warning: {exc}")

    interval = args.interval
    if interval is None:
        interval = MIN_INTERVAL_PERKEY if args.per_key else MIN_INTERVAL_SOLID

    bridge = Bridge(
        kb,
        universe=args.universe,
        start_channel=args.start_channel,
        interval=interval,
        rgb_order=args.rgb_order,
        per_key=args.per_key,
        collapse=args.collapse,
    )
    if not args.per_key:
        bridge._solid_ready = True  # already armed Fixed_on above

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: Proto(bridge),
        local_addr=(args.bind, E131_PORT),
    )

    print(f"E1.31 on {args.bind}:{E131_PORT} universe={args.universe}")
    print(
        f"LEDs={NUM_OPENRGB_LEDS}  order={args.rgb_order}  "
        f"mode={'per-key' if args.per_key else 'single-color/' + args.collapse}"
    )
    if gain is None:
        print("Color tone: raw (no correction)")
    else:
        sample = correct_rgb(255, 150, 38, gain)
        print(f"Color tone: gain=({gain[0]:.3f},{gain[1]:.3f},{gain[2]:.3f})  "
              f"e.g. (255,150,38)->{sample}")
    print("OpenRGB: set a STATIC color on the E1.31 device (not a rainbow effect).")
    if args.per_key:
        print("--per-key: each OpenRGB LED maps to a key (effects = rainbow OK).")
    print("Bridge running. Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(10)
            if args.stats:
                print(f"packets={bridge.packets}")
    except asyncio.CancelledError:
        pass
    finally:
        transport.close()
        kb.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="OpenRGB E1.31 -> AULA F99 bridge")
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--universe", type=int, default=1)
    p.add_argument("--start-channel", type=int, default=1)
    p.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Min seconds between HID updates (default: 0.25 solid / 0.05 per-key)",
    )
    p.add_argument(
        "--rgb-order",
        choices=tuple(RGB_ORDERS),
        default="rgb",
        help="Try bgr if red/blue are swapped",
    )
    p.add_argument(
        "--per-key",
        action="store_true",
        help="Map all 100 OpenRGB LEDs to keys (rainbow effects will show)",
    )
    p.add_argument(
        "--collapse",
        choices=("majority", "average", "first"),
        default="majority",
        help="How to pick the single keyboard color from OpenRGB frame",
    )
    p.add_argument(
        "--raw-color",
        action="store_true",
        help="Disable tone matching (send OpenRGB RGB unchanged)",
    )
    p.add_argument(
        "--gain",
        nargs=3,
        type=float,
        metavar=("R", "G", "B"),
        default=None,
        help="Per-channel gain (default: 254/255 92/150 16/38)",
    )
    p.add_argument("--wired", action="store_true")
    p.add_argument("--wireless", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
