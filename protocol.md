# AULA F99 Pro — HID RGB Protocol

Extracted from OEM app config (`reference/KB.ini`) and the SinoWealth /
AULA F87 family protocol (same USB IDs). Wireless dongle appears as
`3554:FA09`.

## USB IDs (`KB.ini` [OPT])

| Mode | VID | PID | Name |
|------|-----|-----|------|
| Wired | `0x258A` | `0x010C` | AULA F99 Wired / Pro |
| Wireless 2.4G | `0x3554` | `0xFA09` | AULA F99 Pro |

`MatrixLen=128`, `Name=AULA F99 Pro`.

Control uses **vendor HID** collections (`usage_page` `0xFF00`–`0xFFFF`).
On the wireless receiver both `0xFF02` and `0xFF04` accept commands.

## Wire format (20-byte output reports)

```
[0]  Report ID   = 0x13
[1]  Command
[2]  Sub-command
[3]  Sequence
[4..18] Payload (15 bytes)
[19] Checksum = sum(bytes[0:19]) & 0xFF
```

Each host fragment is normally echoed by the keyboard — read the echo
before the next fragment (except high-rate streaming).

### Commands

| Cmd | Name | Notes |
|-----|------|-------|
| `0x44` | READ | Request config (10 fragments back) |
| `0x04` | WRITE | Write config (10 fragments) |
| `0x09` | COLOR | Palette (37 fragments) |
| `0x02` | PERKEY | Per-key RGB planes (28 fragments) |
| `0x0A` | SAVE | Commit to flash |
| `0x88` | AUDIO / stream | Real-time color groups (OpenRGB path) |

Effect change = **Read → Write → Palette → Save**. Config fragment 0
byte 14 (apply flag) must be written as `0x00` or the firmware ignores
the update.

Effect number in config byte 15 is the **software index** from `LedOptN`
(1–18, 21=self-define), matching `tc_kb_led*` strings.

## Effects (`LedOpt` + `text.xml`)

| SW # | Name (`tc_kb_ledN`) | HW id (`LedOpt`) |
|------|---------------------|------------------|
| 1 | Fixed_on | 1 |
| 2 | Respire | 3 |
| 3 | Rainbow | 2 |
| 4 | Flash_away | 19 |
| 5 | Raindrops | 15 |
| 6 | Rainbow_wheel | 13 |
| 7 | Ripples_shining | 20 |
| 8 | Stars_twinkle | 16 |
| 9 | Shadow_disappear | 18 |
| 10 | Retro_snake | 5 |
| 11 | Neon_stream | 7 |
| 12 | Reaction | 17 |
| 13 | Sine_wave | 12 |
| 14 | Retinue scanning | 8 |
| 15 | Rotating windmill | 28 |
| 16 | Colorful waterfall | 30 |
| 17 | Blossoming | 14 |
| 18 | Rotating storm | 29 |
| 21 | Self-define (per-key) | 0 |
| 0 / 20 | OFF | — |

Brightness / speed UI range: **0–4** (`Light` / `Speed` in KB.ini).

## Key → LED index map (from `[KEY]` last field)

99 keys + wheel. Indices used by per-key / stream protocols:

| Key | LED | Key | LED | Key | LED |
|-----|-----|-----|-----|-----|-----|
| Esc | 0 | F1 | 12 | F2 | 18 |
| F3 | 24 | F4 | 30 | F5 | 36 |
| F6 | 42 | F7 | 48 | F8 | 54 |
| F9 | 60 | F10 | 66 | F11 | 72 |
| F12 | 78 | \` | 1 | 1–0 | 7,13,…61 |
| - | 67 | = | 73 | Backspace | 79 |
| Delete | 84 | ScrLk | 90 | NumLock | 91 |
| Num/ | 97 | Num* | 103 | Num- | 109 |
| Tab | 2 | Q–P | 8…62 | [ ] \\ | 68,74,80 |
| Calc | 96 | Home | 85 | Num7–9 | 92,98,104 |
| Num+ | 110 | Caps | 3 | A–' | 9…69 |
| Enter | 81 | Num4–6 | 93,99,105 | LShift | 4 |
| Z–/ | 10…64 | RShift | 82 | Up | 88 |
| Num1–3 | 94,100,106 | LCtrl | 5 | LWin | 11 |
| LAlt | 17 | Space | 35 | RAlt | 53 |
| FN | 59 | PgDn | 87 | Left | 83 |
| Down | 89 | Right | 95 | Num0 | 101 |
| Num. | 107 | NumEnter | 112 | PgUp | 86 |
| Wheel | 108 | | | | |

Full list is embedded in `kb.py` (`KEYS`).

## Atmosphere light bar (Esc–F1)

The RGB strip between **Esc** and **F1** is a separate **atmosphere /
battery indicator** channel. It is **not** part of the key LED map and is
**not** controlled by Fixed_on / palette / OpenRGB bridges (OEM software
also cannot sync it with the keys).

Hardware shortcuts (F99 Pro):

| Combo | Action |
|-------|--------|
| `Fn` + `Right Shift` | Cycle light-bar effect (keep pressing until off / static) |
| `Fn` + `/` | Cycle light-bar color |
| `Fn` + `Right Alt` | Cycle light-bar brightness (down to off) |
| `Fn` + `.` | Cycle light-bar speed |
| `Fn` + `B` | Battery indicator mode (5 green segments = charge) |

## OpenRGB integration

OpenRGB has **no** native AULA F99 detector in stable releases (and generic
Sinowealth detectors were disabled after brick reports). Use the Python
bridge:

```text
OpenRGB --E1.31--> kb_bridge.py --HID 0x13/0x88--> F99
```

See `kb_bridge.py` / OpenRGB fields in that file’s help.

**Close the OEM `OemDrv.exe` before using these tools** — only one
process should own the vendor HID interface.

## Tools

| File | Role |
|------|------|
| `kb.py` | HID library + CLI (effects, color, per-key, raw) |
| `kb_bridge.py` | OpenRGB E1.31 → keyboard stream |
| `protocol.md` | This document |
