"""Star Citizen mobiGlas star map automation.

Deliberately free of tkinter so it can be exercised from a plain script and
dropped into the app (or upstream's module layout) unchanged. It talks to
``win_input`` for keys and mouse, ``win_ocr`` for reading the screen, and
takes ``speak`` / ``log`` callbacks for everything user-facing.

All coordinates are physical device pixels — the same space screenshots and
OCR bounding boxes use — so nothing needs converting anywhere in the chain.
"""

import difflib
import re
import time

import win_input as wi
import win_ocr


# Measured from 3840x2160 screenshots, confirmed by a live OCR run.
DEFAULT_SETTINGS = {
    "search_x": 760,
    "search_y": 272,
    "search_field": {"left": 380, "top": 238, "width": 790, "height": 82},
    "dropdown": {"left": 390, "top": 325, "width": 750, "height": 880},
    "verify_region": {"left": 3140, "top": 1430, "width": 470, "height": 320},
    "destination_region": {"left": 2680, "top": 560, "width": 760, "height": 220},
    # Bottom-left location breadcrumb: "STANTON > HURSTON > 0.00 0.00 12.85GM".
    # The first segment is the star system you are actually in.
    # Starts right of the location-pin icon: OCR reads that glyph as "9".
    "breadcrumb": {"left": 340, "top": 1750, "width": 1000, "height": 110},
    # The button under the info panel states the target's routability in the
    # game's own words: "ROUTE 1625.28 / 7082.64 SCU", "TARGET IS IN ANOTHER
    # SYSTEM", or "INVALID TARGET".
    "target_status": {"left": 380, "top": 1210, "width": 820, "height": 100},
    "current_system": "Stanton",
    "auto_detect_system": True,
    "block_cross_system": True,

    # Two things here are checked rather than waited out, because a fixed
    # delay guessed wrong on both of them during the first live run: the
    # mobiGlas open animation took longer than 1s so the click into the
    # search bar was swallowed, and typing then went nowhere.
    # Each poll is an OCR read costing ~0.7s, so this is roughly a 10s
    # ceiling. A live run needed all 6 of the original 6 attempts, which is
    # no margin at all; the loop exits the moment the map appears, so a
    # generous ceiling costs nothing on a fast open.
    "map_open_attempts": 15,
    "search_attempts": 3,      # click/type/confirm loop
    "delay_after_f2": 0.8,     # small head start before the first poll
    "delay_click": 0.35,       # click -> field focused
    "delay_type": 0.9,         # typing finished -> results populated

    # Clicking a result row selects it AND flies the camera. Enter is not
    # needed — confirmed in game. The wait is for the zoom to settle before
    # R will register.
    "delay_select": 0.8,       # small head start before polling
    "delay_route": 0.8,        # ditto after R

    # The HUD lags the keypress. Measured: 1.5s after R the keybind list
    # still said SET ROUTE, and only changed to CANCEL ROUTE around 3s. So
    # both transitions are polled rather than waited out.
    "hud_poll_attempts": 8,
    "hud_poll_interval": 0.3,
    "eta_retry_delay": 0.6,   # panel names the target before the travel time

    "press_enter_after_click": False,
    "verify_route": True,
    "type_interval": 0.04,
}

MODE_DEFAULT = "DEFAULT"
MODE_MAP = "MAP"

# The bottom-right keybind list is a state machine we can read:
#   map open, nothing selected  ->  STEP BACK / GO TO SELECTION / ...
#   a target is selected        ->  SET ROUTE      appears
#   a course is plotted         ->  CANCEL ROUTE   replaces it
MAP_OPEN_TEXT = "LOCAL MAP"
SELECT_TEXT = "SET ROUTE"
VERIFY_TEXT = "CANCEL ROUTE"

# Speech recognition mangles Star Citizen proper nouns. Seeded from the
# routes Nate actually flies; grow it from the history log.
DESTINATION_ALIASES = {
    "grim hicks": "Grim Hex", "grimhex": "Grim Hex", "grim ex": "Grim Hex",
    "grim hex": "Grim Hex",
    "micro tech": "microTech", "microtech": "microTech",
    "micro-tech": "microTech",
    "arc corp": "ArcCorp", "ark corp": "ArcCorp", "arccorp": "ArcCorp",
    "day mar": "Daymar", "damar": "Daymar", "daymar": "Daymar",
    "hurstin": "Hurston", "houston": "Hurston", "hurston": "Hurston",
    "crusaders": "Crusader", "crusader": "Crusader",
    "piro gateway": "Pyro Gateway", "pyro gate way": "Pyro Gateway",
    "pyro gateway": "Pyro Gateway",
    "nix gateway": "Nyx Gateway", "knicks gateway": "Nyx Gateway",
    "nicks gateway": "Nyx Gateway", "nyx gateway": "Nyx Gateway",
    "terra gate way": "Terra Gateway", "tara gateway": "Terra Gateway",
    "terra gateway": "Terra Gateway",
    "orleans": "Orison", "o'rison": "Orison", "horizon": "Orison",
    "orison": "Orison",
    "lorvile": "Lorville", "lore ville": "Lorville", "lorville": "Lorville",
    "area eighteen": "Area 18", "area18": "Area 18", "area 18": "Area 18",
    "new babage": "New Babbage", "new cabbage": "New Babbage",
    "new babbage": "New Babbage",
    "levski": "Levski", "lipsky": "Levski", "lefsky": "Levski",
    "checkmate": "Checkmate", "ruin station": "Ruin Station",
    # Reported by Nate from live use.
    "stantun": "Stanton", "standon": "Stanton", "stanton": "Stanton",
    "stanten": "Stanton", "stan ton": "Stanton",
}

# Words that appear in the breadcrumb but are never a star system name.
_BREADCRUMB_NOISE = {"SYSTEM", "GM", "KM", "MM"}

_HEADER_PATTERN = re.compile(r"^(.*?)\s*SYSTEM\s*$", re.IGNORECASE)
_RESULTS_PATTERN = re.compile(r"^\s*RESULTS?\b", re.IGNORECASE)
# OCR reads "69.55Gm" as things like "x. 69.556m", so only its shape is
# trustworthy — never its value.
_DISTANCE_PATTERN = re.compile(r"\d[\d.,]*\s*[a-z]{0,2}m\b", re.IGNORECASE)


# --- spelled-out speech and Lagrange station names ----------------------
#
# Two things the recogniser does that used to produce garbage in the search
# field:
#
#   1. Spelling a name out loud comes back as separate words. "L O R V I L
#      L E" was typed verbatim, spaces and all, and matched nothing.
#   2. Lagrange station names are said as a prefix plus a point — "CRU L5" —
#      and arrive as "c r u l five". The game spells them "CRU-L5", with a
#      hyphen that is never spoken.
#
# Both are fixed before the alias table is consulted, so an alias can still
# override the reconstruction.

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "won": "1", "juan": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3", "tree": "3", "free": "3",
    "four": "4", "for": "4", "fore": "4",
    "five": "5", "hive": "5",
}

# Spoken forms of the four Stanton Lagrange prefixes. The mapping is only
# ever applied when an "L<n>" token follows, which makes even the loose
# entries ("crew", "mike") safe.
_LAGRANGE_PREFIXES = {
    "hur": "HUR", "her": "HUR", "hurr": "HUR", "hurt": "HUR", "hair": "HUR",
    "cru": "CRU", "crew": "CRU", "crue": "CRU", "cruz": "CRU", "true": "CRU",
    "arc": "ARC", "ark": "ARC", "arch": "ARC",
    "mic": "MIC", "mike": "MIC", "mick": "MIC", "mik": "MIC", "mick's": "MIC",
}

_L_WORDS = {"l", "el", "ell", "al"}
_LAGRANGE_POINT = re.compile(r"^l[1-5]$")
_LAGRANGE_NAME = re.compile(r"^[A-Z]{3}-L[1-5]$")


def _as_point_digit(token):
    """Return '1'-'5' if this token is a Lagrange point number."""
    if token in _DIGIT_WORDS:
        digit = _DIGIT_WORDS[token]
        return digit if digit in "12345" else None
    if len(token) == 1 and token in "12345":
        return token
    return None


def _condense_spoken(cleaned):
    """Rebuild spelled-out and hyphenated names from loose spoken words."""
    tokens = [t for t in re.split(r"[\s]+", cleaned) if t]

    # Pass 0: split an already-hyphenated name back into its two parts so
    # that pass 3 rebuilds it with the game's casing. "hur-l5" typed by
    # hand should end up identical to "hur l five" spoken aloud.
    split = []
    for token in tokens:
        match = re.match(r"^([a-z]{3})-(l[1-5])$", token)
        if match:
            split.extend(match.groups())
        else:
            split.append(token)
    tokens = split

    # Pass 1: fuse an "L" token with the point number after it, so that the
    # letter-run collapse below cannot swallow the L into the prefix.
    fused = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        stripped = token.replace("-", "")
        if _LAGRANGE_POINT.match(stripped):
            fused.append(stripped)
            index += 1
            continue
        if token in _L_WORDS and index + 1 < len(tokens):
            digit = _as_point_digit(tokens[index + 1])
            if digit:
                fused.append("l" + digit)
                index += 2
                continue
        fused.append(token)
        index += 1

    # Pass 2: collapse runs of two or more single letters into one word.
    # "l o r v i l l e" -> "lorville";  "c r u l5" -> "cru l5".
    collapsed = []
    spelled = set()          # indices of tokens the pilot spelled out
    run = []

    def flush_run():
        if len(run) >= 2:
            spelled.add(len(collapsed))
            collapsed.append("".join(run))
        else:
            collapsed.extend(run)
        run.clear()

    for token in fused:
        if len(token) == 1 and token.isalpha():
            run.append(token)
        else:
            flush_run()
            collapsed.append(token)
    flush_run()

    # Pass 3: join a Lagrange prefix to its point with the hyphen the game
    # uses but nobody says.
    #
    # An unknown three-letter word only counts as a prefix when it was
    # spelled out letter by letter. Otherwise "see are you l five" turns
    # into "YOU-L5" — an ordinary word swept up by its own length.
    joined = []
    index = 0
    while index < len(collapsed):
        token = collapsed[index]
        following = collapsed[index + 1] if index + 1 < len(collapsed) else ""
        if _LAGRANGE_POINT.match(following):
            prefix = _LAGRANGE_PREFIXES.get(token)
            if prefix is None and index in spelled and len(token) == 3:
                prefix = token.upper()
            if prefix:
                joined.append(f"{prefix}-{following.upper()}")
                index += 2
                continue
        joined.append(token)
        index += 1

    return joined


def _lookup_alias(cleaned):
    """Exact, then longest-prefix, lookup in the alias table."""
    if cleaned in DESTINATION_ALIASES:
        return DESTINATION_ALIASES[cleaned]

    # Try progressively shorter prefixes so "take me to grim hicks please"
    # still resolves.
    words = cleaned.split()
    for size in range(len(words), 0, -1):
        candidate = " ".join(words[:size])
        if candidate in DESTINATION_ALIASES:
            return DESTINATION_ALIASES[candidate]
    return None


def normalize_destination(spoken):
    """Map a spoken phrase onto the name the game actually uses."""
    cleaned = " ".join(str(spoken).strip().lower().split())

    resolved = _lookup_alias(cleaned)
    if resolved:
        return resolved

    tokens = _condense_spoken(cleaned)
    condensed = " ".join(tokens)
    if condensed != cleaned:
        resolved = _lookup_alias(condensed)
        if resolved:
            return resolved

    return " ".join(
        token if _LAGRANGE_NAME.match(token) else token.title()
        for token in tokens
    )


def spoken_form(name):
    """How a name should be read aloud.

    "CRU-L5" spoken as written comes out of the speech engine as a mangled
    word; as separate letters it is understood.
    """
    text = str(name or "")
    if _LAGRANGE_NAME.match(text):
        prefix, point = text.split("-")
        return " ".join(prefix) + " " + " ".join(point)
    return text


def _key(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def same_system(a, b):
    """True when two system names refer to the same place.

    Deliberately forgiving about surrounding OCR noise. A breadcrumb read
    as "9 Stanton 0000 -0340" still means Stanton, and treating that as a
    different system is what made a destination in the pilot's own system
    look cross-system.
    """
    key_a, key_b = _key(a), _key(b)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    return key_a in key_b or key_b in key_a


def search_queries(destination, minimum=3, attempts=3):
    """Yield the full name, then progressively shorter prefixes of it.

    Speech recognition gets the *start* of a name right far more often than
    the end — "Stanton" comes back as "Stantun" or "Standon". Since the game
    filters the list as characters arrive, the correct row is visible after
    a few letters and only disappears once the wrong ones land. So when the
    full spelling finds nothing, try less of it.

    ``minimum`` is three letters, not four. "Lorville" heard as "Lorevile"
    used to bottom out at "Lorv", which still filters the row away; "Lor"
    leaves it on screen.
    """
    text = str(destination).strip()
    if not text:
        return

    seen = {text}
    yield text

    # Prefer whole-word prefixes: "Pyro Gateway" -> "Pyro" is a better guess
    # than "Pyro Gatew".
    words = text.split()
    if len(words) > 1:
        first = words[0]
        if len(first) >= minimum and first not in seen:
            seen.add(first)
            yield first

    length = len(text)
    for step in range(1, attempts + 1):
        cut = max(minimum, int(length * (1 - 0.25 * step)))
        if cut >= length:
            continue
        # A prefix must not end mid-punctuation: "CRU-L5" cut to "CRU-"
        # types a trailing hyphen that filters everything out.
        candidate = text[:cut].strip().rstrip("-'. ")
        if len(candidate) < minimum or candidate in seen:
            continue
        seen.add(candidate)
        yield candidate


def parse_results(lines):
    """Turn raw OCR lines into structured rows grouped by star system.

    Returns ``[{"text", "system", "has_distance", "line"}, ...]`` in visual
    order. Pure function, so the picker can be tested without a game running.
    """
    ordered = sorted(lines, key=lambda item: item.get("top", 0))
    rows = []
    current_system = None

    for index, line in enumerate(ordered):
        text = (line.get("text") or "").strip()
        if not text or _RESULTS_PATTERN.match(text):
            continue

        header = _HEADER_PATTERN.match(text)
        if header and header.group(1).strip():
            current_system = header.group(1).strip().title()
            continue

        # A distance sub-line sits just under its name line. It is not a row
        # of its own, but its presence marks the row above as in-system.
        if _DISTANCE_PATTERN.search(text) and len(_key(text)) <= 12:
            if rows:
                rows[-1]["has_distance"] = True
            continue

        rows.append({
            "text": text,
            "system": current_system,
            "has_distance": False,
            "line": line,
        })

    return rows


def pick_row(rows, destination, current_system, min_similarity=0.72):
    """Choose the result row to click.

    Two entries can share a name — "NYX GATEWAY" exists in both Stanton and
    Pyro — and the only thing telling them apart is the system header above
    them. From Stanton you want the Stanton one, so the header match
    dominates every other signal.

    Returns ``(row, reason)`` or ``(None, reason)``.
    """
    target = _key(destination)
    if not target:
        return None, "no destination given"

    system_key = _key(current_system or "")
    scored = []

    for row in rows:
        row_key = _key(row["text"])
        if not row_key:
            continue

        if row_key == target:
            match_score, how = 100, "exact"
        elif target in row_key or row_key in target:
            match_score, how = 70, "partial"
        else:
            ratio = _similar(row_key, target)
            if ratio < min_similarity:
                continue
            match_score, how = int(50 * ratio), f"fuzzy {ratio:.2f}"

        score = match_score
        reasons = [how]

        if system_key and _key(row["system"] or "") == system_key:
            score += 1000                      # the decisive signal
            reasons.append(f"in {row['system']}")
        elif row["system"]:
            reasons.append(f"in {row['system']}")

        if row["has_distance"]:
            score += 10                        # weak corroboration only
            reasons.append("has distance")

        scored.append((score, row, ", ".join(reasons)))

    if not scored:
        return None, f"no row matching '{destination}'"

    scored.sort(key=lambda item: -item[0])
    best_score, best_row, why = scored[0]

    if len(scored) > 1 and scored[1][0] == best_score:
        why += " (tie broken by position)"

    return best_row, why


class StarMapController:
    """Drives the mobiGlas star map: open, search, select, route, verify."""

    def __init__(self, settings=None, speak=None, log=None):
        self.settings = dict(DEFAULT_SETTINGS)
        if settings:
            self.settings.update(settings)

        self.mode = MODE_DEFAULT
        self.last_rows = []
        self.last_destination = None

        self._speak = speak or (lambda text: None)
        self._log = log or (lambda text, kind="info": None)

    # ---- helpers -------------------------------------------------------
    @property
    def current_system(self):
        return self.settings.get("current_system", "Stanton")

    def set_system(self, system):
        self.settings["current_system"] = str(system).strip().title()
        self._log(f"Current system set to {self.current_system}.")
        return self.current_system

    def _region(self, name):
        region = self.settings[name]
        return region["left"], region["top"], region["width"], region["height"]

    def _say_name(self, text):
        """Prefer our canonical spelling over whatever OCR read.

        The panel gave "Grim HEX", which the speech engine reads as an
        initialism. When the OCR name is the destination we asked for, say
        it the way the alias table spells it.
        """
        if not text:
            return spoken_form(self.last_destination or "")

        canonical = self.last_destination
        if canonical and (
            _key(canonical) == _key(text)
            or _similar(_key(canonical), _key(text)) >= 0.85
        ):
            return spoken_form(canonical)
        text = str(text)
        return spoken_form(text if _LAGRANGE_NAME.match(text) else text.title())

    # ---- reading the HUD -----------------------------------------------
    def read_hud_keys(self):
        """Read the bottom-right keybind list.

        One capture answers two questions: the map is open when it lists
        LOCAL MAP, and a course is set when it lists CANCEL ROUTE.
        """
        data = win_ocr.ocr_region(*self._region("verify_region"))
        text = " ".join(
            (line.get("text") or "").upper()
            for line in data.get("lines", [])
        )
        return re.sub(r"\s+", " ", text), data

    def map_is_open(self):
        text, data = self.read_hud_keys()
        if not data.get("ok"):
            return False
        return MAP_OPEN_TEXT in text or "MY LOCATION" in text

    def wait_for_hud(self, wanted, attempts=None, absent=False):
        """Poll the keybind list until ``wanted`` appears (or disappears).

        The HUD does not update on the same frame as the keypress. Measured
        on a live route: 1.5s after pressing R the list still read SET
        ROUTE, and only flipped to CANCEL ROUTE about 3s in. Polling makes
        that timing irrelevant instead of something to guess at.
        """
        attempts = attempts or self.settings["hud_poll_attempts"]
        for attempt in range(1, attempts + 1):
            text, data = self.read_hud_keys()
            if data.get("ok"):
                present = wanted in text
                if present != absent:
                    return True, attempt
            time.sleep(self.settings["hud_poll_interval"])
        return False, attempts

    def read_target_status(self):
        """Read the game's own verdict on the selected target.

        Returns ``(state, raw_text)`` where state is one of ``routable``,
        ``another_system``, ``invalid`` or ``None``.

        This beats inferring readiness from SET ROUTE for two reasons: it
        gives a *reason* rather than just an absence, and it still works
        when a course is already plotted — the case where SET ROUTE can
        never appear at all.
        """
        data = win_ocr.ocr_region(*self._region("target_status"))
        if not data.get("ok"):
            return None, ""

        text = " ".join(
            (line.get("text") or "").upper()
            for line in data.get("lines", [])
        )
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None, ""

        if "ANOTHER SYSTEM" in text:
            return "another_system", text
        if "INVALID" in text:
            return "invalid", text
        if "ROUTE" in text:
            return "routable", text
        return None, text

    def detect_current_system(self):
        """Read the star system from the map's location breadcrumb.

        Removes a whole class of error: a hand-set "current system" that no
        longer matches where the ship actually is would silently send the
        row picker after the wrong twin.
        """
        data = win_ocr.ocr_region(*self._region("breadcrumb"))
        if not data.get("ok"):
            return None

        text = " ".join(
            (line.get("text") or "").strip()
            for line in data.get("lines", [])
        ).strip()
        if not text:
            return None

        # Do NOT rely on the ">" separator: OCR does not recognise that
        # chevron glyph, so splitting on it returns the entire line
        # including the coordinates. Take the first real word instead —
        # the system name always leads, in both the "STANTON SYSTEM >"
        # and "STANTON > HURSTON >" forms.
        for word in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
            candidate = word.strip("'-")
            if candidate.upper() in _BREADCRUMB_NOISE:
                continue
            if len(candidate) > 15:
                continue
            return candidate.title()

        return None

    def sync_current_system(self):
        """Detect and adopt the current system. Returns the name, or None."""
        detected = self.detect_current_system()
        if not detected:
            self._log("Could not read the location breadcrumb; "
                      f"staying with {self.current_system}.")
            return None

        if not same_system(detected, self.current_system):
            self._log(f"Current system detected as {detected} "
                      f"(was {self.current_system}).")
            self.settings["current_system"] = detected
        return detected

    def read_search_field(self):
        """Return whatever text is currently in the search box."""
        data = win_ocr.ocr_region(*self._region("search_field"))
        text = " ".join(
            (line.get("text") or "").strip()
            for line in data.get("lines", [])
        ).strip()
        return text, data

    @staticmethod
    def _field_is_empty(text):
        key = _key(text)
        return not key or "searchlocation" in key

    # ---- map control ---------------------------------------------------
    def open_map(self, announce=True):
        """F2, then wait for the map to actually be up before clicking.

        The mobiGlas raise animation swallows clicks while it plays, and it
        is slower than any single delay worth hard-coding. So this polls the
        HUD until the map's own keybind list appears.
        """
        wi.tap_keybind("f2")
        time.sleep(self.settings["delay_after_f2"])

        opened = False
        for attempt in range(1, self.settings["map_open_attempts"] + 1):
            if self.map_is_open():
                opened = True
                self._log(f"Star map detected on screen (check {attempt}).")
                break

        if not opened:
            self._log(
                "Star map did not appear — is Star Citizen focused, and is "
                "F2 still bound to the map?",
                "error",
            )
            return False

        if not self.focus_search():
            return False

        self.mode = MODE_MAP
        if announce:
            self._speak("Ready to plot course.")
        return True

    def close_map(self):
        wi.tap_keybind("f2")
        self.mode = MODE_DEFAULT
        self._log("Star map closed.")
        return True

    def focus_search(self):
        """Click into the search field and confirm it took focus."""
        wi.click_at(
            self.settings["search_x"],
            self.settings["search_y"],
            physical=True,
        )
        time.sleep(self.settings["delay_click"])

        text, data = self.read_search_field()
        if not data.get("ok"):
            self._log(f"Could not read the search field: {data.get('error')}", "error")
            return False

        if not self._field_is_empty(text):
            wi.clear_text_field()
            time.sleep(0.2)

        self._log("Search bar focused.")
        return True

    def enter_destination(self, destination):
        """Type the destination and confirm the characters actually landed.

        The first live run typed into nothing because the click had been
        swallowed by the open animation, and nothing noticed. Reading the
        field back turns that silent failure into a retry.
        """
        attempts = self.settings["search_attempts"]

        for attempt in range(1, attempts + 1):
            wi.type_text(destination, interval=self.settings["type_interval"])
            time.sleep(self.settings["delay_type"])

            text, data = self.read_search_field()
            if not data.get("ok"):
                self._log(f"Search field unreadable: {data.get('error')}", "error")
                return False

            typed = _key(text)
            wanted = _key(destination)
            if wanted and (wanted in typed or _similar(typed, wanted) >= 0.8):
                self._log(f"Search field reads '{text}'.")
                return True

            self._log(
                f"Search field reads '{text}' — expected '{destination}'. "
                f"Retrying ({attempt}/{attempts}).",
                "error",
            )
            if not self.focus_search():
                return False
            wi.clear_text_field()
            time.sleep(0.2)

        return False

    def read_results(self):
        """OCR the dropdown and return structured rows."""
        data = win_ocr.ocr_region(*self._region("dropdown"))
        if not data.get("ok"):
            self._log(f"Could not read results: {data.get('error')}", "error")
            return [], data
        if data.get("black"):
            self._log(
                "Screen capture came back black — switch to Borderless "
                "Windowed.",
                "error",
            )
            return [], data

        rows = parse_results(data.get("lines", []))
        self.last_rows = rows
        return rows, data

    # ---- routing -------------------------------------------------------
    def route_to(self, spoken_destination):
        """Full sequence: search, pick the right row, select, route, verify.

        Returns ``(success, message)``.
        """
        destination = normalize_destination(spoken_destination)
        self.last_destination = destination

        if self.mode != MODE_MAP:
            if not self.open_map(announce=False):
                self._speak("I could not open the star map.")
                return False, "star map did not open"
        elif not self.focus_search():
            self._speak("I could not reach the search bar.")
            return False, "search bar not focused"

        if self.settings["auto_detect_system"]:
            self.sync_current_system()

        # Type progressively shorter prefixes until the row appears.
        #
        # The game filters as you type, so a mis-heard ending is fatal but a
        # mis-heard *start* is rare: "Stanton" heard as "Stantun" shows the
        # right row until the wrong letters arrive, then loses it. Typing
        # less is therefore more robust, and the OCR row picker still
        # fuzzy-matches against the full name.
        row = None
        why = "no attempt made"
        rows = []

        for attempt, query in enumerate(search_queries(destination), start=1):
            if attempt > 1:
                self._log(f"No match yet — retrying with '{query}'.")
                if not self.focus_search():
                    break
                wi.clear_text_field()
                time.sleep(0.2)
            else:
                self._log(f"Searching for {destination}.")

            if not self.enter_destination(query):
                self._speak(f"I could not type {destination} into the search bar.")
                return False, "destination text never reached the search field"

            rows, _ = self.read_results()
            if rows:
                row, why = pick_row(rows, destination, self.current_system)
                if row is not None:
                    if attempt > 1:
                        self._log(f"Found it by typing only '{query}'.")
                    break

        if row is None:
            if not rows:
                self._speak(f"No results for {destination}.")
                return False, "no results for that destination"
            self._speak(f"I could not find {destination} in the results.")
            return False, why

        # Star Citizen will not plot a course into another star system: the
        # target selects but SET ROUTE never appears. Rather than burning
        # eight polls discovering that, say what the pilot actually needs.
        if (
            self.settings["block_cross_system"]
            and row["system"]
            and not same_system(row["system"], self.current_system)
        ):
            gateway = f"{row['system']} Gateway"
            self._speak(
                f"{self._say_name(row['text'])} is in the {row['system']} "
                f"system. Travel to the {gateway} first."
            )
            message = (
                f"{row['text']} is in {row['system']}, not {self.current_system} "
                f"— route to the {gateway} first"
            )
            self._log(message)
            return False, message

        x, y = win_ocr.line_center(row["line"])
        self._log(f"Selecting '{row['text']}' at ({x}, {y}) — {why}.")

        # Was a course already set before we started? If so, CANCEL ROUTE is
        # already on screen and its mere presence proves nothing about THIS
        # route, so confirmation has to lean on the destination name instead.
        hud_before, _ = self.read_hud_keys()
        had_route = VERIFY_TEXT in hud_before

        # Clicking the row both selects the target and flies the camera to
        # it. Enter is not part of the sequence.
        wi.click_at(x, y, physical=True)
        time.sleep(self.settings["delay_select"])

        if self.settings["press_enter_after_click"]:
            wi.tap_keybind("enter")
            time.sleep(0.4)

        # Wait for the game to acknowledge the selection before pressing R.
        # SET ROUTE appearing is the game telling us it is ready to route.
        # Ask the game what it makes of the selection. Its own wording is
        # more informative than any absence we could infer, and unlike
        # SET ROUTE it is still meaningful when a course is already set.
        state = None
        raw = ""
        for attempt in range(1, self.settings["hud_poll_attempts"] + 1):
            state, raw = self.read_target_status()
            if state in ("routable", "another_system"):
                self._log(f"Target status after {attempt} check(s): {raw}")
                break
            time.sleep(self.settings["hud_poll_interval"])

        if state == "another_system":
            gateway = f"{row['system']} Gateway" if row["system"] else "the gateway"
            self._speak(
                f"{self._say_name(row['text'])} is in another system. "
                f"Travel to {gateway} first."
            )
            return False, f"game reports: {raw}"

        if state != "routable":
            if had_route:
                # SET ROUTE cannot appear while CANCEL ROUTE holds that slot,
                # so an unreadable button here is not proof of failure.
                self._log(
                    "Target status unreadable and a course was already set — "
                    "pressing R and confirming by destination name."
                )
            else:
                selected, tries = self.wait_for_hud(SELECT_TEXT)
                if not selected:
                    self._speak(
                        f"I selected {self._say_name(row['text'])}, "
                        f"but it did not take."
                    )
                    return False, (
                        f"selection never registered — no ROUTE button and "
                        f"{SELECT_TEXT} never appeared after {tries} checks"
                    )
                self._log(f"Target selected after {tries} check(s).")

        wi.tap_keybind("r")
        time.sleep(self.settings["delay_route"])

        if not self.settings["verify_route"]:
            self._speak(f"Course plotted to {self._say_name(row['text'])}.")
            return True, "routed (not verified)"

        return self._confirm_route(row, had_route=had_route)

    def _confirm_route(self, row, had_route=False):
        """Confirm the course is set, polling rather than sampling once.

        Two independent signals: CANCEL ROUTE replacing SET ROUTE in the
        keybind list, and the quantum panel naming the destination. When a
        route was already active before this one, CANCEL ROUTE was already
        on screen and only the name distinguishes the new route from the old.
        """
        wanted = _key(row["text"])
        routed = False
        name = None
        eta = None

        for attempt in range(1, self.settings["hud_poll_attempts"] + 1):
            hud_ok = self.verify_route()
            name, eta = self.read_destination()
            name_ok = bool(name) and (
                wanted in _key(name) or _similar(_key(name), wanted) >= 0.8
            )

            if hud_ok and (name_ok or not had_route):
                routed = True
                self._log(f"Course confirmed after {attempt} check(s).")
                break

            time.sleep(self.settings["hud_poll_interval"])

        # The panel names the destination before it fills in the travel
        # time, so a confirmation that lands early gets the name but no ETA.
        # One extra read rather than delaying every confirmation.
        if routed and name and eta is None:
            time.sleep(self.settings["eta_retry_delay"])
            retry_name, retry_eta = self.read_destination()
            if retry_eta:
                eta = retry_eta
                name = retry_name or name
                self._log(f"ETA arrived on a second read: {eta}.")

        if not routed:
            detail = (
                "the panel never named the new destination"
                if had_route
                else f"{VERIFY_TEXT} never appeared"
            )
            self._speak(
                f"I selected {self._say_name(row['text'])}, "
                f"but the course was not set."
            )
            return False, f"route not confirmed — {detail}"

        label = self._say_name(name or row["text"])

        if eta:
            self._speak(f"Course set to {label}. {eta}.")
            message = f"Course set to {label} ({eta})"
        else:
            self._speak(f"Course set to {label}.")
            message = f"Course set to {label}"

        self._log(message)
        return True, message

    def verify_route(self):
        """True when the game shows CANCEL ROUTE, meaning a course is set.

        Far more reliable than looking for the orange route line, which is
        thin, dashed, and easily hidden behind a planet.
        """
        text, data = self.read_hud_keys()
        if not data.get("ok"):
            self._log(f"Verification read failed: {data.get('error')}", "error")
            return False
        return VERIFY_TEXT in text

    def read_destination(self):
        """Read back what the game actually routed to: ``(name, eta)``.

        Speaking this rather than what we typed is what catches a wrong row
        even when the click itself succeeded.
        """
        data = win_ocr.ocr_region(*self._region("destination_region"))
        if not data.get("ok"):
            return None, None

        name = None
        eta = None
        for line in sorted(data.get("lines", []), key=lambda i: i.get("top", 0)):
            text = (line.get("text") or "").strip()
            if not text:
                continue

            upper = text.upper()
            if "QUANTUM" in upper or "NAVIGATE" in upper or "SCU" in upper:
                continue

            # OCR drops a leading "0h", so the panel's "0h 5m 30s" arrives as
            # "5m 30s". Hours are optional.
            eta_match = re.search(
                r"(?:(\d+)\s*h\s*)?(\d+)\s*m\s*(\d+)\s*s\b", text, re.IGNORECASE
            )
            if eta_match and eta is None:
                hours, minutes, seconds = (
                    int(value) if value else 0 for value in eta_match.groups()
                )
                parts = []
                if hours:
                    parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
                if minutes:
                    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
                if seconds:
                    parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
                eta = ", ".join(parts) if parts else None
                continue

            if name is None and re.search(r"[A-Za-z]{3}", text):
                name = text.strip()

        return name, eta
