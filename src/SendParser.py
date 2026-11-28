"""The key actions an AHK Send string stands for: braces, modifier symbols, {Blind}, {Raw}, {Text} and {Click}."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from yorha import KeyCodes
from yorha.KeyCodes import KeyCode

PRESS = "press"
DOWN = "down"
# {Key DownTemp}: down, but a later non-blind Send may lift the modifier and leave it up
DOWN_TEMP = "downtemp"
# {Key DownR}: down, and a later non-blind Send that lifts the modifier puts it back down at its end
DOWN_REMEMBERED = "downr"
UP = "up"
CLICK = "click"
DOWN_KINDS = (DOWN, DOWN_TEMP, DOWN_REMEMBERED)

_BRACE = re.compile(r"\{([^}]+|\})\}")
_BRACE_BODY = re.compile(r"^(?P<name>.+?)(?:\s+(?P<arg>\S+))?$")
_BLIND = re.compile(r"^\{Blind([\^!+#<>]*)\}", re.IGNORECASE)
_CLICK = re.compile(r"^click(?:\s+(?P<options>.*))?$", re.IGNORECASE | re.DOTALL)
_DOWN_ARGS = {"down": DOWN, "downtemp": DOWN_TEMP, "downr": DOWN_REMEMBERED}
RAW_MODE = "raw"
TEXT_MODE = "text"
_MODE_SWITCHES = {"{raw}": RAW_MODE, "{text}": TEXT_MODE}
# Text mode turns only these into keystrokes; every other character goes as a Unicode packet.
_TEXT_MODE_KEYS = {"\r": KeyCode(0x0D, 0, False), "\n": KeyCode(0x0D, 0, False), "\t": KeyCode(0x09),
                   "\b": KeyCode(0x08)}


@dataclass(frozen=True)
class KeyAction:
    """One Send unit: a key pressed (down then up), held down or released; `char` is set for a Unicode packet
    and `click` holds the options of a {Click}. `wrapped` marks the modifier down and up a modifier symbol or
    a shifted character put around a key."""
    key: KeyCode
    kind: str = PRESS
    char: str = ""
    click: str = ""
    wrapped: bool = False


def BlindModifiers(keys: str) -> str | None:
    """None when `keys` is not in Blind mode, else the modifier symbols {Blind^+} still releases."""
    match = _BLIND.match(keys)
    if match is None:
        return None
    return "".join(symbol for symbol in match[1] if symbol in KeyCodes.MODIFIER_SEND_VK)


def ParseSend(keys: str) -> list[KeyAction]:
    """The key actions of a Send string, modifiers wrapped around the key they precede. {Raw} and {Text} take
    effect from where they appear to the end of the string."""
    actions: list[KeyAction] = []
    modifiers = ""
    blind = _BLIND.match(keys)
    index = 0 if (blind is None) else blind.end()
    while index < len(keys):
        mode = _ModeSwitch(keys, index)
        if mode is not None:
            return actions + _LiteralActions(keys[index + len(f"{{{mode}}}"):], mode)
        char = keys[index]
        if (char in KeyCodes.MODIFIER_SEND_VK) and (index + 1 < len(keys)):
            modifiers += char
            index += 1
            continue
        brace = _BRACE.match(keys, index) if (char == "{") else None
        if brace is not None:
            actions.extend(_Wrap(modifiers, _BraceActions(brace[1])))
            index = brace.end()
        else:
            actions.extend(_Wrap(modifiers, _CharActions(char)))
            index += 1
        modifiers = ""
    return actions


def _ModeSwitch(keys: str, index: int) -> str | None:
    for switch, mode in _MODE_SWITCHES.items():
        if keys[index:index + len(switch)].lower() == switch:
            return mode
    return None


def _LiteralActions(text: str, mode: str) -> list[KeyAction]:
    actions: list[KeyAction] = []
    # `r`n is a single Enter in Text mode (two in Raw mode, like AHK)
    if mode == TEXT_MODE:
        text = text.replace("\r\n", "\n")
    for char in text:
        if mode == RAW_MODE:
            actions.extend(_CharActions(char))
        elif char in _TEXT_MODE_KEYS:
            actions.append(KeyAction(_TEXT_MODE_KEYS[char]))
        else:
            actions.append(KeyAction(KeyCode(0), PRESS, char))
    return actions


def _BraceActions(body: str) -> list[KeyAction]:
    if body.lower() == "blind":
        return []
    click = _CLICK.match(body)
    if click is not None:
        return [KeyAction(KeyCode(0), CLICK, "", click["options"] or "")]
    match = _BRACE_BODY.match(body.strip()) if (len(body) > 1) else None
    if match is None:
        return _CharActions(body)
    name, arg = match["name"], (match["arg"] or "").lower()
    # A typeable character goes through the layout, which may add Shift: {$ 2}, {! down}
    if (len(name) == 1) and not (name.isascii() and name.isalnum()):
        return _WithArg(_CharActions(name), arg)
    key = KeyCodes.GetKeyCode(name)
    if key is None:
        raise ValueError(f"Unknown key name in Send: {{{body}}}")
    return _WithArg([KeyAction(key)], arg)


def _WithArg(actions: list[KeyAction], arg: str) -> list[KeyAction]:
    """The argument applies to the key itself; the modifiers wrapped around it keep their own down and up."""
    if arg == "":
        return actions
    if arg in _DOWN_ARGS:
        return [action if action.wrapped else replace(action, kind=_DOWN_ARGS[arg]) for action in actions]
    if arg == "up":
        return [action if action.wrapped else replace(action, kind=UP) for action in actions]
    if arg.isdigit():
        return actions * int(arg)
    raise ValueError(f"Unknown Send key argument: {arg}")


def _CharActions(char: str) -> list[KeyAction]:
    if char == "\r":
        return [KeyAction(_TEXT_MODE_KEYS["\r"])]
    resolved = KeyCodes.CharKey(char)
    if resolved is None:
        return [KeyAction(KeyCode(0), PRESS, char)]
    key, modifiers = resolved
    return _Wrap(modifiers, [KeyAction(key)])


def _Wrap(modifiers: str, actions: list[KeyAction]) -> list[KeyAction]:
    if (not modifiers) or (not actions):
        return actions
    held = [KeyCode(KeyCodes.MODIFIER_SEND_VK[symbol], 0, symbol == "#") for symbol in modifiers]
    downs = [KeyAction(key, DOWN_TEMP, wrapped=True) for key in held]
    ups = [KeyAction(key, UP, wrapped=True) for key in reversed(held)]
    return downs + actions + ups
