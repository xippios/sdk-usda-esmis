"""Pydantic models mirroring USDA ESMIS payloads.

One model per upstream object, subclassing ``xippios.core.UpstreamModel``, with fields
named as upstream names them in snake_case. Where upstream spells a field differently,
``Field(validation_alias=...)`` accepts that spelling on input; never ``alias=``, which the
adapters would serialise, handing agents the upstream spelling. Within-source hygiene only:
dates become ``datetime.date``, numbers become numbers, upstream enumerations become
``StrEnum``, and an enumeration of integer ids ``IntEnum``. No cross-source normalisation
(ADR-0003): an upstream concept stays an upstream concept.

These read models stay faithful, documented personal identifiers included (``ssn``,
``iban`` and their like). The projections tasks return leave those out, a write task does
not echo one in ``meta.request``, and fixtures never carry their values (ADR-0017). No
ESMIS record carries one; the contact e-mail addresses and telephone numbers of agencies
and publications are upstream's published contacts.

The reference for names is ``docs/upstream/openapi/esmis_public_api.yaml``, whose
schemas are ``Agency``, ``Pager``, ``Publication`` and ``Release`` and whose responses are
``AgencyResults``, ``PublicationResults`` and ``ReleaseResults``. Types follow the wire,
which wins where it differs from the document (README, "Where the live API deviates from
its OpenAPI document"): every ``id`` is a JSON string, several of the document's strings
are arrays, and the list answers carry keys the document does not name. Each model's
docstring names the fixtures its shape comes from, all recorded on 2026-10-27.

Every model keeps ``UpstreamModel``'s ``extra="ignore"``: a key upstream sends that a
model does not name is dropped when parsed, never refused. That is how
``PublicationResults`` and ``ReleaseResults`` take the list wrapper's ``filters``,
``sorters`` and ``system`` keys, which the document does not name.

The four Publication enumerations of the document (``frequency``, ``status``,
``subscribable``, ``resource_type``) stay ``str``: the recorded publications use a few of
their values only, and a value outside the document's list, which the wire has not been
checked against, would fail a whole page.
"""

from pydantic import AwareDatetime
from xippios.core import UpstreamModel

__all__ = [
    "Agency",
    "Pager",
    "Publication",
    "PublicationResults",
    "Release",
    "ReleaseResults",
]


class Agency(UpstreamModel):
    """One agency: the YAML's schema ``Agency``, in the response ``AgencyResults``.

    ``esmis_api_agency_findAll``, ``esmis_api_agency_findByAcronym`` and
    ``esmis_api_agency_findById`` answer a bare JSON array of these, as the document's
    ``AgencyResults`` says. Shape from ``tests/fixtures/agency_find_all/all.json`` (9
    agencies, ids ``"1"`` to ``"9"``, every one with all eight fields as strings),
    ``agency_find_by_acronym/waob.json`` and ``agency_find_by_id/3.json`` (one each).

    Attributes:
        id: ``id``, a JSON string of digits on the wire where the document says
            ``integer``, e.g. ``"3"``; the ``agencyId`` of ``esmis_api_agency_findById``.
        title: ``title``, e.g. ``"World Agricultural Outlook Board"``.
        acronym: ``acronym``, e.g. ``"WAOB"``, ``"AMS-DA"``; the ``agencyAcronym`` of
            ``esmis_api_agency_findByAcronym`` and ``esmis_api_publication_findByAgency``.
        contact_email: ``contact_email``, e.g. ``"oce@oce.usda.gov"``.
        contact_phone: ``contact_phone``, e.g. ``"202-720-5447"``; ``""`` for FAS as
            recorded.
        location_city: ``location_city``, e.g. ``"Washington"``.
        location_state: ``location_state``, e.g. ``"DC"``.
        homepage_url: ``homepage_url``, e.g. ``"http://www.usda.gov/oce/commodity/"``.
    """

    id: str
    title: str
    acronym: str
    contact_email: str
    contact_phone: str
    location_city: str
    location_state: str
    homepage_url: str


class Pager(UpstreamModel):
    """The paging block of a list answer: the YAML's schema ``Pager``.

    Shape from every recorded ``PublicationResults`` and ``ReleaseResults`` answer: four
    JSON integers. ``page`` is 0-based and a page holds 25 items, a fixed size no
    parameter changes. A page past the last answers empty ``results`` with
    ``current_page`` clamped to the last page: ``tests/fixtures/publication_find_all/
    page500.json`` asked for page 500 and answered ``current_page`` 100 of
    ``total_pages`` 101.

    Attributes:
        current_page: ``current_page``, 0-based, e.g. ``0``.
        items_per_page: ``items_per_page``, ``25`` in every recorded answer.
        total_pages: ``total_pages``, e.g. ``101``; ``0`` when nothing matches.
        total_results: ``total_results``, upstream's count of what matches the request,
            e.g. ``2522`` publications, ``1542025`` releases, ``703`` releases of WASDE.
    """

    current_page: int
    items_per_page: int
    total_pages: int
    total_results: int


class Publication(UpstreamModel):
    """One publication (a report series): the YAML's schema ``Publication``.

    Shape from ``tests/fixtures/publication_find_all/page0.json`` (25 publications),
    ``publication_search/wasde_page0.json`` (7), ``publication_find_by_agency/
    waob_page0.json`` (2), ``publication_find_by_id/1659.json`` and
    ``publication_find_by_identifier/wasde.json`` (WASDE). Where the wire differs from the
    document (README's deviations): ``id`` is a string; ``agency``, ``identifier`` and
    ``agency_acronym`` are arrays of strings, ``agency`` of agency names, not the
    document's acronym; ``agency_acronym`` is absent on some publications, which carry
    ``publication_agency_export_1``, a field the document does not name, instead. As
    recorded, every publication of ``esmis_api_publication_findAll`` carries
    ``agency_acronym`` and no ``publication_agency_export_1``, and every one of the
    other four publication operations the reverse. Both are kept as upstream prints
    them, neither merged into the other.

    Attributes:
        id: ``id``, a string of digits, e.g. ``"1659"``; the ``publicationId`` of
            ``esmis_api_publication_findById`` and ``esmis_api_release_findByPubId``.
        agency: ``agency``, the agency names, e.g. ``["World Agricultural Outlook
            Board"]``, ``["Agricultural Marketing Service", "Dairy Program"]``.
        title: ``title``, e.g. ``"World Agricultural Supply and Demand Estimates"``.
        contact_email: ``contact_email``, e.g. ``"msewadeh@oce.usda.gov"``.
        keywords: ``keywords``, e.g. ``["dairy", "grains", "soybeans"]``.
        frequency: ``frequency``; the document lists ``Daily``, ``Bi-weekly``,
            ``Weekly``, ``Monthly``, ``Annually``, ``Seasonal``, ``Other`` and ``Not
            specified``; recorded: ``"Daily"``, ``"Weekly"``, ``"Monthly"``.
        status: ``status``; the document lists ``Active`` and ``Inactive``; recorded:
            ``"Active"``.
        subscribable: ``subscribable``, the text ``"Yes"`` or ``"No"`` as the document
            lists them, not a boolean.
        resource_type: ``resource_type``; the document lists ``Report``, ``Dataset`` and
            ``Statistical bulletin``; recorded: ``"Report"``.
        subject: ``subject``, e.g. ``["Grains and Oilseeds"]``.
        description: ``description``, text as upstream prints it, HTML entities such as
            ``&nbsp;`` included.
        identifier: ``identifier``, one or more, e.g. ``["wasde"]``,
            ``["Market and Trade Economics Division/FDS", "FDS"]``; the
            ``publicationIdentifier`` of ``esmis_api_publication_findByIdentifier`` and
            ``esmis_api_release_findByIdentifier``. One carrying ``/`` cannot be looked
            up (``tests/fixtures/publication_find_by_identifier/with_slash.json``).
        upcoming_releases: ``upcoming_releases``; ``[]`` in every recorded publication.
            The document types the items as ``date-time`` strings; no answer shows one,
            so they are kept as text (``list[str]``), an assumption until one is seen.
        agency_acronym: ``agency_acronym``, e.g. ``["AMS", "AMS-DA"]``; ``None`` where
            upstream leaves it out.
        publication_agency_export_1: ``publication_agency_export_1``, e.g.
            ``["WAOB"]``; ``None`` where upstream leaves it out.
    """

    id: str
    agency: list[str]
    title: str
    contact_email: str
    keywords: list[str]
    frequency: str
    status: str
    subscribable: str
    resource_type: str
    subject: list[str]
    description: str
    identifier: list[str]
    upcoming_releases: list[str]
    agency_acronym: list[str] | None = None
    publication_agency_export_1: list[str] | None = None


class Release(UpstreamModel):
    """One release of a publication, with its files: the YAML's schema ``Release``.

    Shape from ``tests/fixtures/release_find_all/page0.json`` (25 releases, NASS and
    WAOB), ``release_find_by_id/796099.json`` (WASDE of 2026-10-09),
    ``release_find_by_identifier/wasde_page0.json`` and ``release_find_by_pub_id/
    1659_page0.json`` (25 WASDE releases each). Where the wire differs from the document
    (README's deviations): ``id`` is a string and ``files`` are absolute URLs on the same
    host.

    Attributes:
        id: ``id``, a string of digits, e.g. ``"796099"``; the ``releaseId`` of
            ``esmis_api_release_findById``.
        files: ``files``, absolute URLs, e.g.
            ``["https://esmis.nal.usda.gov/sites/default/release-files/796099/wasde1026.pdf",
            ...]``; one to four per recorded release.
        title: ``title``, the publication's title, e.g. ``"World Agricultural Supply and
            Demand Estimates"``.
        release_datetime: ``release_datetime``, printed ``YYYY-MM-DDTHH:MM:SS+0000``,
            e.g. ``"2026-10-09T12:00:00+0000"``, parsed into an aware ``datetime`` with
            the offset as printed, ``+00:00``. The offset is upstream's label, and
            upstream's own calendar and file times contradict it (README); how a task
            reports it in ``meta`` is the tasks' decision, the model keeps it as printed.
        identifier: ``identifier``, the publication's identifiers, e.g. ``["wasde"]``.
        agency_acronym: ``agency_acronym``, one string here, e.g. ``"WAOB"``.
        bibliographic_citation: ``bibliographic_citation``; ``""`` in every recorded
            release.
        description: ``description``, HTML as upstream prints it, often ``""``.
        equipment_software: ``equipment_software``, often ``""``.
        temporal_coverage: ``temporal_coverage``; ``""`` in every recorded release.
    """

    id: str
    files: list[str]
    title: str
    release_datetime: AwareDatetime
    identifier: list[str]
    agency_acronym: str
    bibliographic_citation: str
    description: str
    equipment_software: str
    temporal_coverage: str


class PublicationResults(UpstreamModel):
    """A page of publications: the YAML's response ``PublicationResults``.

    Every publication operation answers this wrapper, the single-record lookups
    included (``findById``, ``findByIdentifier``). The wire's wrapper is ``{filters,
    pager, results, sorters, system}``; ``filters``, ``sorters`` and ``system``
    (``{"page_key": "page"}``) are not in the document and are dropped by
    ``UpstreamModel``'s ``extra="ignore"``.

    ``esmis_api_publication_search`` without a query, or with an empty one, answers
    ``"pager": []``, an empty JSON array, and empty ``results``
    (``tests/fixtures/publication_search/no_query.json`` and ``empty_query.json``).
    ``pager`` takes that as printed: it is a ``Pager`` or the empty tuple ``()``, which
    accepts only an empty array and serialises back to ``[]``; any other array is
    refused.

    Attributes:
        pager: ``pager``, a ``Pager``, or ``()`` where upstream sent ``[]``.
        results: ``results``, the publications of this page, ``[]`` past the last page
            or when nothing matches.
    """

    pager: Pager | tuple[()]
    results: list[Publication]


class ReleaseResults(UpstreamModel):
    """A page of releases: the YAML's response ``ReleaseResults``.

    Every release operation answers this wrapper, ``findById`` included. ``filters``,
    ``sorters`` and ``system`` are dropped as in ``PublicationResults``. ``pager`` is
    typed as there, ``Pager`` or ``()``, although no recorded release answer printed
    ``"pager": []``.

    Attributes:
        pager: ``pager``, a ``Pager``, or ``()`` where upstream sent ``[]``.
        results: ``results``, the releases of this page.
    """

    pager: Pager | tuple[()]
    results: list[Release]
