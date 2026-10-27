"""Packaged value lists for USDA ESMIS (conventions §3): none.

The scaffold's machinery for value lists, ``reference/<name>.json`` as
``{"param", "fetched", "values"}``, read by ``packaged_values``. ESMIS packages no value
list: its two packaged files, ``reference/publication.json`` and
``reference/agency.json``, are tables in core's ``PackagedList`` shape (records, not
values), which ``tasks.py`` reads directly with ``PackagedList.load``, the reader that
builds an answer's ``meta`` (ADR-0022); ``packaged_values`` could not read them, so
``PACKAGED_LISTS`` stays empty. Template v0.3.0, unreleased, renders ``PackagedList`` in
place of this machinery; ``scripts/refresh_reference.py`` writes the files and
``reference/README.md`` carries their provenance.
"""

from datetime import date

from xippios.core import UpstreamModel, load_json

__all__ = ["PACKAGED_LISTS", "PackagedValues", "packaged_values"]

PACKAGE = "xippios.usda.esmis"

PACKAGED_LISTS: tuple[str, ...] = ()
"""Names of the value lists that ship inside the package: none; the two packaged tables
are ``PackagedList`` files, read in ``tasks.py``."""


class PackagedValues(UpstreamModel):
    """One packaged value list: ``reference/<name>.json``.

    Attributes:
        param: The upstream list the values belong to.
        fetched: Day the list was fetched.
        values: The values, as upstream lists them.
    """

    param: str
    fetched: date
    values: list[str]


def packaged_values(name: str) -> PackagedValues | None:
    """The packaged list ``name``, or ``None`` when it is not packaged."""
    if name not in PACKAGED_LISTS:
        return None
    return PackagedValues.model_validate(load_json(PACKAGE, f"{name}.json"))
