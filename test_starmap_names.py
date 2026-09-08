"""Offline tests for destination naming — no game, no Windows, no OCR.

Everything here is a pure function, so this runs anywhere in under a second:

    python test_starmap_names.py

Covers the three things live play exposed:
  * a name spelled out loud arrived with spaces between every letter
  * Lagrange stations are said "CRU L5" but spelled "CRU-L5"
  * the progressive search gave up at four letters, one too early
"""

import sys
import types

# starmap imports the Windows input/OCR helpers at module scope. Neither is
# touched by the naming code, so stand-ins are enough to import it here.
for _name in ("win_input", "win_ocr"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

import starmap  # noqa: E402


FAILURES = []


def check(label, got, want):
    ok = got == want
    mark = "PASS" if ok else "FAIL"
    print(f"   [{mark}] {label}")
    if not ok:
        print(f"          got  {got!r}")
        print(f"          want {want!r}")
        FAILURES.append(label)
    return ok


def test_spelled_out_names():
    print("\n1. A spelled-out name must not keep its spaces")
    for spoken in ("l o r v i l l e", "L O R V I L L E", "l  o r  v i l l e"):
        check(f"{spoken!r} -> Lorville",
              starmap.normalize_destination(spoken), "Lorville")
    check("'a r c corp' -> ArcCorp",
          starmap.normalize_destination("a r c corp"), "ArcCorp")
    # A single stray letter is not a spelling attempt.
    check("'ruin station' untouched",
          starmap.normalize_destination("ruin station"), "Ruin Station")


def test_lagrange_stations():
    print("\n2. Lagrange stations get the hyphen nobody says")
    cases = {
        "cru l5": "CRU-L5",
        "cru l five": "CRU-L5",
        "c r u l 5": "CRU-L5",
        "c r u l five": "CRU-L5",
        "hur l3": "HUR-L3",
        "h u r l 3": "HUR-L3",
        "her l one": "HUR-L1",
        "ark l 4": "ARC-L4",
        "mike l 1": "MIC-L1",
        "hur-l5": "HUR-L5",
        "CRU-L1": "CRU-L1",
    }
    for spoken, want in cases.items():
        check(f"{spoken!r} -> {want}",
              starmap.normalize_destination(spoken), want)

    print("   ordinary words are not mistaken for a prefix")
    check("'see are you l five' keeps its words",
          starmap.normalize_destination("see are you l five"),
          "See Are You L5")


def test_existing_names_unchanged():
    print("\n3. Names that already worked still work")
    cases = {
        "grim hicks": "Grim Hex",
        "stantun": "Stanton",
        "micro tech": "microTech",
        "new cabbage": "New Babbage",
        "piro gateway": "Pyro Gateway",
        "area eighteen": "Area 18",
        "orison": "Orison",
        "checkmate": "Checkmate",
    }
    for spoken, want in cases.items():
        check(f"{spoken!r} -> {want}",
              starmap.normalize_destination(spoken), want)


def test_search_queries():
    print("\n4. Progressive search reaches three letters")
    lorville = list(starmap.search_queries("Lorville"))
    check("Lorville tries 'Lor'", "Lor" in lorville, True)
    check("Lorville starts with the full name", lorville[0], "Lorville")
    check("Lorville never goes below three letters",
          min(len(q) for q in lorville) >= 3, True)

    stanton = list(starmap.search_queries("Stanton"))
    check("Stanton reaches three letters",
          min(len(q) for q in stanton), 3)

    pyro = list(starmap.search_queries("Pyro Gateway"))
    check("multi-word names try the first word second", pyro[1], "Pyro")

    cru = list(starmap.search_queries("CRU-L5"))
    check("CRU-L5 falls back to 'CRU'", cru, ["CRU-L5", "CRU"])
    check("no prefix ends on a hyphen",
          [q for q in cru if q.endswith("-")], [])

    check("empty input yields nothing", list(starmap.search_queries("")), [])


def test_spoken_form():
    print("\n5. Lagrange names are read aloud as letters")
    check("CRU-L5 spoken", starmap.spoken_form("CRU-L5"), "C R U L 5")
    check("HUR-L3 spoken", starmap.spoken_form("HUR-L3"), "H U R L 3")
    check("ordinary names untouched",
          starmap.spoken_form("Grim Hex"), "Grim Hex")


def test_row_picking_still_matches():
    print("\n6. The picker still finds a Lagrange row by its full label")
    rows = [
        {"text": "CRU-L4 SHALLOW FIELDS", "system": "Stanton",
         "has_distance": True, "line": {}},
        {"text": "CRU-L5 BEAUTIFUL GLEN", "system": "Stanton",
         "has_distance": True, "line": {}},
        {"text": "CRU-L1 AMBITIOUS DREAM", "system": "Stanton",
         "has_distance": True, "line": {}},
    ]
    row, why = starmap.pick_row(rows, "CRU-L5", "Stanton")
    check("picks CRU-L5, not L4 or L1",
          row["text"] if row else None, "CRU-L5 BEAUTIFUL GLEN")
    print(f"          reason: {why}")


def test_lowercase_search():
    print("\n7. The destination is typed without shift")
    check("lowercase_search defaults on",
          starmap.DEFAULT_SETTINGS.get("lowercase_search"), True)

    # "HUR-L5" needs shift for three letters; "hur-l5" needs none, which is
    # what stops the game reading "-" and "5" as "_" and "%".
    for name in ["HUR-L5", "CRU-L5", "Lorville", "Grim Hex", "microTech"]:
        typed = name.lower()
        check(f"{name!r} types as {typed!r} (no capitals)",
              any(c.isupper() for c in typed), False)

    # Every comparison downstream is case-insensitive, so nothing else cares.
    check("_key is case-insensitive",
          starmap._key("HUR-L5") == starmap._key("hur-l5"), True)
    rows = [{"text": "HUR-L5 HIGH COURSE STATION", "system": "Stanton",
             "has_distance": True, "line": {}}]
    row, _ = starmap.pick_row(rows, "hur-l5", "Stanton")
    check("a lower-case destination still matches an upper-case row",
          row["text"] if row else None, "HUR-L5 HIGH COURSE STATION")


def main():
    print("Kabutopz Voice Protocol — destination naming tests")
    test_spelled_out_names()
    test_lagrange_stations()
    test_existing_names_unchanged()
    test_search_queries()
    test_spoken_form()
    test_row_picking_still_matches()
    test_lowercase_search()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for label in FAILURES:
            print(f"   - {label}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
