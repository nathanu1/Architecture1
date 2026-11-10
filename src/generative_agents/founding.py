"""Found a town that is yours: choose who lives there, name it, and move in residents you wrote.

The living town used to start as one fixed thing: the same ten of the paper's residents. This
module makes the founding a choice without touching the engine:

* **cast**: any number of the 25 Smallville residents, named, the default ten first, or drawn
  at random;
* **your own residents**: a short card per person (name, a sentence about them, optional
  routine and acquaintances). Each household gets a house on one of the plots the 35-resident
  variant already uses and validates (``scenarios/smallville_n35/neighborhood.yaml``), built by
  the same ``scenario.neighborhood.build`` that made that variant. The result is an ordinary
  scenario inside the town's own folder, together with a copy of the base scenario, so the
  folder can be moved to another machine and the town continues.

Residents you write are an extension: they are not in the paper's data, and a town that has
them is never compared with the paper's 25-agent numbers. They start without knowledge of the
seeded events (the builder refuses texts that mention them).
"""

from __future__ import annotations

import random
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .config import repo_path
from .scenario import neighborhood

BASE = "scenarios/smallville_n25"
PLOTS = "scenarios/smallville_n35/neighborhood.yaml"
DEFAULT_TEN = [
    "isabella_rodriguez",
    "maria_lopez",
    "klaus_mueller",
    "sam_moore",
    "wolfgang_schulz",
    "tom_moreno",
    "jane_moreno",
    "tamara_taylor",
    "carmen_ortiz",
    "ayesha_khan",
]
CARD_KEYS = {"name", "age", "traits", "about", "currently", "routine", "day", "knows", "works_at", "lives_with"}


class FoundingError(ValueError):
    """A founding choice that cannot be honored; the message says what to change."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def folder_name(town_name: str) -> str:
    return slug(town_name).replace("_", "-") or "town"


# ------------------------------------------------------------------------------------- cast
def premade() -> list[dict[str, Any]]:
    """The 25 Smallville residents: id, name, age and one line about each, in scenario order."""

    base = repo_path(BASE)
    out = []
    for aid in yaml.safe_load((base / "scenario.yaml").read_text())["agents"]:
        ident = yaml.safe_load((base / "agents" / f"{aid}.yaml").read_text())["identity"]
        out.append({"id": aid, "name": ident["name"], "age": ident["age"], "about": " ".join(str(ident["learned"]).split()).split(". ")[0].rstrip(".") + "."})
    return out


def choose_cast(count: int, cast: str | None = None, seed: int = 7) -> list[str]:
    """Which premade residents live in the town.

    ``cast`` is a comma-separated list of ids or names, or ``random`` for ``count`` residents
    drawn with ``seed``, or ``none``. Without it: the default ten first, then the rest in
    scenario order, ``count`` of them.
    """

    everyone = premade()
    ids = [p["id"] for p in everyone]
    if cast and cast.strip().lower() == "none":
        return []
    if cast and cast.strip().lower() == "random":
        if not 0 <= count <= len(ids):
            raise FoundingError(f"--residents must be between 0 and {len(ids)}")
        return sorted(random.Random(seed).sample(ids, count), key=ids.index)
    if cast:
        by_name = {slug(p["name"]): p["id"] for p in everyone} | {slug(p["name"].split()[0]): p["id"] for p in everyone}
        chosen = []
        for item in (c.strip() for c in cast.split(",") if c.strip()):
            aid = slug(item) if slug(item) in ids else by_name.get(slug(item))
            if aid is None:
                raise FoundingError(f"{item!r} is not one of the town's residents; `ga town --list-cast` shows them")
            if aid not in chosen:
                chosen.append(aid)
        return sorted(chosen, key=ids.index)
    if not 0 <= count <= len(ids):
        raise FoundingError(f"--residents must be between 0 and {len(ids)}")
    order = DEFAULT_TEN + [a for a in ids if a not in DEFAULT_TEN]
    return sorted(order[:count], key=ids.index)


# ------------------------------------------------------------------------------------ cards
def load_cards(path: str | Path) -> list[dict[str, Any]]:
    """Read and check a file of resident cards (a YAML list, or ``residents: [...]``)."""

    data = yaml.safe_load(Path(path).read_text())
    cards = data.get("residents") if isinstance(data, dict) else data
    if not isinstance(cards, list) or not cards:
        raise FoundingError(f"{path}: expected a list of residents, each with at least `name` and `about`")
    seen: set[str] = set()
    for card in cards:
        if not isinstance(card, dict) or not str(card.get("name") or "").strip():
            raise FoundingError(f"{path}: every resident needs a `name`")
        name = " ".join(str(card["name"]).split())
        card["name"] = name
        if len(name.split()) < 2:
            raise FoundingError(f"{name}: give a first and a last name")
        if not str(card.get("about") or "").strip():
            raise FoundingError(f"{name}: add `about`, one or two sentences on who they are and what they do")
        unknown = set(card) - CARD_KEYS
        if unknown:
            raise FoundingError(f"{name}: unknown field(s) {sorted(unknown)}; a card may have {sorted(CARD_KEYS)}")
        if slug(name) in seen:
            raise FoundingError(f"{name} is listed twice")
        seen.add(slug(name))
    names = {slug(c["name"]) for c in cards}
    for card in cards:
        mate = card.get("lives_with")
        if mate and slug(str(mate)) not in names:
            raise FoundingError(f"{card['name']}: lives_with {mate!r} is not another resident in this file")
    return cards


def _named(name: str, text: str, *, about: bool = False, people: frozenset[str] = frozenset()) -> str:
    """Identity texts name the person, as the paper's do; put the name in front if it is missing.

    "a carpenter who ..." becomes "<Name> is a carpenter who ...", "Rosa Delgado's son" becomes
    "<Name> is Rosa Delgado's son", and "bakes bread" becomes "<Name> bakes bread".
    """

    text = " ".join(str(text).split())
    if name.split()[0].lower() in text.lower():
        return text
    first = text.split()[0]
    proper = first.rstrip("'s").lower() in people
    article = first.lower() in ("a", "an", "the")
    lead = "is " if about and (article or proper) else ""
    body = text if proper else text[0].lower() + text[1:]
    return f"{name} {lead}{body}"


def _households(cards: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    where: dict[str, int] = {}
    for card in cards:
        key, mate = slug(card["name"]), slug(str(card.get("lives_with") or ""))
        if mate in where:
            where[key] = where[mate]
            groups[where[mate]].append(card)
        else:
            where[key] = len(groups)
            groups.append([card])
    # a card may name a housemate that comes later in the file
    for card in cards:
        key, mate = slug(card["name"]), slug(str(card.get("lives_with") or ""))
        if mate and where[key] != where[mate]:
            src, dst = where[key], where[mate]
            groups[dst].extend(groups[src])
            for c in groups[src]:
                where[slug(c["name"])] = dst
            groups[src] = []
    order = {slug(c["name"]): i for i, c in enumerate(cards)}  # households and their members in file order
    groups = [sorted(g, key=lambda c: order[slug(c["name"])]) for g in groups if g]
    return sorted(groups, key=lambda g: order[slug(g[0]["name"])])


def neighborhood_spec(cards: list[dict[str, Any]], town_name: str, base_rel: str = "../base/scenario.yaml") -> dict[str, Any]:
    """The ``neighborhood.yaml`` that moves ``cards`` into houses on the validated plots."""

    plots = yaml.safe_load(repo_path(PLOTS).read_text())
    small = [h for h in plots["houses"] if not h.get("rooms")]
    family = [h for h in plots["houses"] if h.get("rooms")]
    public = list(plots["public_places"])
    houses: list[dict[str, Any]] = []
    newcomers: list[dict[str, Any]] = []
    staff: dict[str, list[str]] = {}
    people = frozenset(part.lower() for c in cards for part in c["name"].split())
    for group in _households(cards):
        firsts = [c["name"].split()[0] for c in group]
        lasts = {c["name"].split()[-1] for c in group}
        if len(group) > 3:
            raise FoundingError(f"{', '.join(c['name'] for c in group)}: a house holds at most three residents")
        if len(group) == 1 and small:
            plot = small.pop(0)
            house = f"{group[0]['name']}'s house"
            houses.append({"name": house, "template": plot["template"], "at": list(plot["at"])})
            rooms = [f"the Ville:{house}:main room"]
        elif family:
            plot = family.pop(0)
            house = f"{lasts.pop()} family's house" if len(group) > 1 and len(lasts) == 1 else f"{' and '.join(firsts)}'s house"
            couple, single = (next(r for r in plot["rooms"] if (" and " in r) == want) for want in (True, False))
            if len(group) == 3:
                renamed = {couple: f"{firsts[0]} and {firsts[1]}'s bedroom", single: f"{firsts[2]}'s bedroom"}
                rooms = [renamed[couple], renamed[couple], renamed[single]]
            elif len(group) == 2:
                renamed = {couple: f"{firsts[0]}'s bedroom", single: f"{firsts[1]}'s bedroom"}
                rooms = [renamed[couple], renamed[single]]
            else:
                renamed = {couple: f"{firsts[0]}'s bedroom", single: "guest bedroom"}
                rooms = [renamed[couple]]
            houses.append({"name": house, "template": plot["template"], "at": list(plot["at"]), "rooms": renamed})
            rooms = [f"the Ville:{house}:{r}" for r in rooms]
        else:
            raise FoundingError(
                "the new neighborhood has six plots (four small houses, two family houses) and they are all taken; share houses with `lives_with`"
            )
        for card, room in zip(group, rooms, strict=True):
            name = card["name"]
            aid = slug(name)
            first, last = name.split()[0], " ".join(name.split()[1:])
            mates = [c["name"] for c in group if c is not card]
            seeds = [str(s) for s in (card.get("knows") or [])]
            seeds += [f"{m} lives with you in {house}" for m in mates]
            seeds.append("You moved to Smallville recently and do not know many people yet")
            newcomers.append(
                {
                    "id": aid,
                    "identity": {
                        "name": name,
                        "first_name": first,
                        "last_name": last,
                        "age": int(card.get("age") or 30),
                        "innate": " ".join(str(card.get("traits") or "friendly, curious, easygoing").split()),
                        "learned": _named(name, card["about"], about=True, people=people),
                        "currently": _named(
                            name, card.get("currently") or "has just moved to Smallville and is getting to know the town and its people.", people=people
                        ),
                        "lifestyle": _named(
                            name, card.get("routine") or "goes to bed around 11pm, wakes up around 7am, and eats dinner around 6pm.", people=people
                        ),
                        "living_area": room,
                        "daily_plan_req": _named(name, card.get("day") or "spends the day around town and likes to stop by Hobbs Cafe.", people=people),
                    },
                    "seeds": seeds,
                    "knows": public,
                }
            )
            if card.get("works_at"):
                staff.setdefault(f"the Ville:{str(card['works_at']).strip()}", []).append(aid)
    spec: dict[str, Any] = {
        "name": slug(town_name) or "town",
        "description": f"{town_name}: smallville_n25 plus {len(newcomers)} resident(s) written for this town (an extension, not part of the paper's setup)",
        "base": base_rel,
        "map": "map/the_ville_town.json",
        "street_tile": list(plots["street_tile"]),
        "margin": int(plots.get("margin", 1)),
        "openings": [list(o) for o in plots.get("openings", [])],
        "houses": houses,
        "public_places": public,
        "newcomers": newcomers,
    }
    if staff:
        spec["staff"] = staff
    return spec


def build_scenario(cards: list[dict[str, Any]], dest: str | Path, town_name: str) -> dict[str, Any]:
    """Write the town's own scenario under ``dest`` (``base/`` and ``town/``); returns the build report.

    ``dest/town/scenario.yaml`` is what the town runs on. ``dest/base`` is a copy of the base
    scenario, so the folder does not depend on where the package is installed.
    """

    dest = Path(dest)
    if (dest / "base").exists():
        shutil.rmtree(dest / "base")
    shutil.copytree(repo_path(BASE), dest / "base")
    (dest / "town").mkdir(parents=True, exist_ok=True)
    spec = neighborhood_spec(cards, town_name)
    spec_path = dest / "town" / "neighborhood.yaml"
    spec_path.write_text(
        "# Written by `ga town --newcomers`: the residents of this town that are not in the paper's data.\n"
        + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120)
    )
    try:
        report = neighborhood.build(spec_path)
    except ValueError as exc:
        raise FoundingError(_explain(str(exc))) from exc
    report["newcomer_names"] = [n["identity"]["name"] for n in spec["newcomers"]]
    return report


def _explain(message: str) -> str:
    if "seeded-event knowledge" in message:
        return message + ". Newcomers arrive without knowing about the town's party or election; leave those words out of the card."
    if "no opening hours" in message:
        return message + ". `works_at` is for places with opening hours: Hobbs Cafe, The Willows Market and Pharmacy, Harvey Oak Supply Store."
    if "already used" in message:
        return message + ". Pick a different name, or put that resident in the town with --cast."
    return message


def scenario_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "scenario" / "town" / "scenario.yaml"


__all__ = [
    "DEFAULT_TEN",
    "FoundingError",
    "build_scenario",
    "choose_cast",
    "folder_name",
    "load_cards",
    "neighborhood_spec",
    "premade",
    "scenario_path",
    "slug",
]
