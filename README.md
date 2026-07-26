# AULA F99 PRO OpenRGB

Unofficial OpenRGB bridge and HID tools for the **AULA F99 Pro** keyboard (wired `258A:010C` / 2.4G `3554:FA09`).

OpenRGB has no stable native AULA F99 detector. This project exposes the keyboard as an **E1.31 (sACN)** device on localhost and forwards colors over vendor HID.

```text
OpenRGB  --E1.31 UDP-->  kb_bridge.py  --HID 0x13 / 0x88-->  F99 Pro
```

## Requirements

- Windows (tested), Python 3.10+
- [OpenRGB](https://openrgb.org/)
- Close OEM `OemDrv.exe` before use (only one process may own the vendor HID interface)

```bash
pip install -r requirements.txt
```

## Quick start (OpenRGB)

1. Plug the keyboard (USB-C or 2.4G receiver).
2. Start the bridge:

```bash
python kb_bridge.py
```

3. In OpenRGB: **Settings → Manually added devices → Add device → E1.31**

| Field | Value |
|-------|-------|
| Name | AULA F99 Pro (any) |
| IP (Unicast) | `127.0.0.1` |
| Start Universe | `1` |
| Start Channel | `1` |
| Number of LEDs | `100` |
| Universe Size | `512` |

4. Rescan / update device list, set a **static** color on the E1.31 device.

### Modes

| Command | Behavior |
|---------|----------|
| `python kb_bridge.py` | One color for the whole board (best for static OpenRGB colors) |
| `python kb_bridge.py --per-key` | Map all 100 OpenRGB LEDs to keys (effects / rainbow OK) |
| `python kb_bridge.py --rgb-order bgr` | Swap channel order if colors look wrong |

## CLI (`kb.py`)

Direct HID control without OpenRGB:

```bash
python kb.py list
python kb.py effect Fixed_on
python kb.py color 255 40 0
python kb.py --help
```

## Files

| File | Role |
|------|------|
| `kb_bridge.py` | OpenRGB E1.31 → keyboard |
| `kb.py` | HID library + CLI |
| `protocol.md` | Reverse-engineered HID protocol |
| `reference/KB.ini` | OEM key / LED map excerpt |

## Notes

- The Esc–F1 atmosphere / battery light bar is **not** part of the key LED map and is not driven by this bridge (hardware `Fn` shortcuts only). See `protocol.md`.
- Default path collapses multi-color OpenRGB frames to one keyboard color so static paints stay clean.
- Use at your own risk; this is unofficial reverse-engineering, not affiliated with AULA / SinoWealth / OpenRGB.
