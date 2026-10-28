"""Pydantic models mirroring upstream's payloads, one ``UpstreamModel`` per object.

Conventions §3 and ``/add-endpoint`` give the rules.

No ESMIS record carries a documented personal identifier (ADR-0017); the contact e-mail
addresses and telephone numbers of agencies and publications are upstream's published
contacts.

The reference for names is ``docs/upstream/openapi/esmis_public_api.yaml``, whose
schemas are ``Agency``, ``Pager``, ``Publication`` and ``Release`` and whose responses are
``AgencyResults``, ``PublicationResults`` and ``ReleaseResults``. Types follow the wire,
which wins where it differs from the document (README, "Where the live API deviates from
its OpenAPI document"): every ``id`` is a JSON string, several of the document's strings
are arrays, and the list answers carry keys the document does not name. Each model's
docstring names the fixtures its shape comes from, recorded on 2026-10-27, and
``release_find_by_id/95621.json`` on 2026-10-28.
``ReleaseFile`` and ``PublicationRow`` are the models the document does not name:
an item of ``Release.files`` with the name and extension its URL prints, for the file
tasks, and a projection of ``Publication`` (``UpstreamModel.project``, conventions §3),
the rows of the packaged publication table that ``list_publications`` answers from.
``ReleaseFile.from_url`` reads one item and ``Release.release_files`` all of a release's,
in upstream order: the reading the file tasks use, which the packages that depend on
this one call rather than copy (ADR-0021).

Every model keeps ``UpstreamModel``'s ``extra="ignore"``: a key upstream sends that a
model does not name is dropped when parsed, never refused. That is how
``PublicationResults`` and ``ReleaseResults`` take the list wrapper's ``filters``,
``sorters`` and ``system`` keys, which the document does not name.

The document declares four enumerations on ``Publication``. A walk of every page of
``esmis_api_publication_findAll`` on 2026-10-27 (pages 0 to 100, 2522 publications)
settled them by evidence: ``status``, ``subscribable`` and ``resource_type`` used only
the document's values and are ``StrEnum`` (``Status``, ``Subscribable``,
``ResourceType``), members named by core's ``enum_member_name`` rule, values as upstream
prints them; ``frequency`` stays ``str``, since publication 1172 printed it as ``""``,
which the document does not list.
"""

from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime
from xippios.core import UpstreamModel

__all__ = [
    "Agency",
    "Pager",
    "Publication",
    "PublicationResults",
    "PublicationRow",
    "Release",
    "ReleaseFile",
    "ReleaseResults",
    "ResourceType",
    "Status",
    "Subscribable",
]


class Status(StrEnum):
    """A publication's ``status``: ``Active`` or ``Inactive``.

    The document's enumeration of ``Publication.status``. The walk of 2026-10-27 counted
    2033 ``Active`` and 489 ``Inactive`` of 2522 publications.
    """

    ACTIVE = "Active"
    INACTIVE = "Inactive"


class Subscribable(StrEnum):
    """Whether a publication is ``subscribable``: the text ``Yes`` or ``No``.

    The document's enumeration of ``Publication.subscribable``, unquoted ``Yes`` and
    ``No`` there, which a YAML 1.1 reader takes for booleans; the wire sends the strings.
    The walk of 2026-10-27 counted 2068 ``Yes`` and 454 ``No`` of 2522 publications.
    """

    YES = "Yes"
    NO = "No"


class ResourceType(StrEnum):
    """A publication's ``resource_type``: ``Report``, ``Dataset`` or ``Statistical bulletin``.

    The document's enumeration of ``Publication.resource_type``. The walk of 2026-10-27
    counted 2404 ``Report``, 78 ``Statistical bulletin`` and 40 ``Dataset`` of 2522
    publications.
    """

    REPORT = "Report"
    DATASET = "Dataset"
    STATISTICAL_BULLETIN = "Statistical bulletin"


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
    documented parameter changes. A page past the last answers empty ``results`` with
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
    other four publication operations the reverse; the walk of every
    ``esmis_api_publication_findAll`` page on 2026-10-27 found ``agency_acronym`` on all
    2522 and ``publication_agency_export_1`` on none. Both are kept as upstream prints
    them, neither merged into the other. Every other field was on all 2522 publications
    of the walk, and is required.

    Attributes:
        id: ``id``, a string of digits, e.g. ``"1659"``; the ``publicationId`` of
            ``esmis_api_publication_findById`` and ``esmis_api_release_findByPubId``.
        agency: ``agency``, the agency names, e.g. ``["World Agricultural Outlook
            Board"]``, ``["Agricultural Marketing Service", "Dairy Program"]``.
        title: ``title``, e.g. ``"World Agricultural Supply and Demand Estimates"``.
        contact_email: ``contact_email``, e.g. ``"msewadeh@oce.usda.gov"``.
        keywords: ``keywords``, e.g. ``["dairy", "grains", "soybeans"]``.
        frequency: ``frequency``, text; the document lists ``Daily``, ``Bi-weekly``,
            ``Weekly``, ``Monthly``, ``Annually``, ``Seasonal``, ``Other`` and ``Not
            specified``. The walk of 2026-10-27 counted 842 ``Weekly``, 693 ``Daily``,
            329 ``Not specified``, 212 ``Other``, 180 ``Annually``, 178 ``Monthly``, 84
            ``Seasonal``, 3 ``Bi-weekly`` and one ``""`` (publication 1172, page 33),
            which the document does not list, so it stays ``str``.
        status: ``status``, a ``Status``, e.g. ``Status.ACTIVE`` (``"Active"``).
        subscribable: ``subscribable``, a ``Subscribable``, the text ``"Yes"`` or
            ``"No"``, not a boolean.
        resource_type: ``resource_type``, a ``ResourceType``, e.g.
            ``ResourceType.REPORT`` (``"Report"``).
        subject: ``subject``, e.g. ``["Grains and Oilseeds"]``.
        description: ``description``, text as upstream prints it, HTML entities such as
            ``&nbsp;`` included.
        identifier: ``identifier``, one or more, e.g. ``["wasde"]``,
            ``["Market and Trade Economics Division/FDS", "FDS"]``; the
            ``publicationIdentifier`` of ``esmis_api_publication_findByIdentifier`` and
            ``esmis_api_release_findByIdentifier``. One carrying ``/`` cannot be looked
            up (``tests/fixtures/publication_find_by_identifier/with_slash.json``).
        upcoming_releases: ``upcoming_releases``, the document's ``date-time``
            strings, parsed into aware datetimes with the offset as printed, e.g.
            ``2026-10-28T15:00:00-0400`` and ``2026-11-04T15:00:00-0500`` for Broiler
            Hatchery (``tests/fixtures/publication_find_by_id/1863.json``), an Eastern
            offset where ``Release.release_datetime`` prints ``+0000``. ``[]`` on most:
            the walk of 2026-10-27 found items on 24 of 2522 publications, 67 in all,
            every one ``YYYY-MM-DDTHH:MM:SS-HHMM``.
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
    status: Status
    subscribable: Subscribable
    resource_type: ResourceType
    subject: list[str]
    description: str
    identifier: list[str]
    upcoming_releases: list[AwareDatetime]
    agency_acronym: list[str] | None = None
    publication_agency_export_1: list[str] | None = None


class PublicationRow(UpstreamModel):
    """One publication as the packaged table keeps it: a projection of ``Publication``.

    Eight of ``Publication``'s fields under upstream's names, built with
    ``UpstreamModel.project`` and nothing renamed or computed (conventions §3): the
    records of ``reference/publication.json``, which ``scripts/refresh_reference.py``
    writes from a walk of every page of ``esmis_api_publication_findAll`` and
    ``list_publications`` answers from. ``agency_acronym`` and
    ``publication_agency_export_1`` are kept side by side as upstream prints them, neither
    merged into the other, ``None`` where upstream leaves one out; the packaged file
    writes that ``None`` as JSON ``null``, so both keys are on every record.

    Attributes:
        id: ``id``, a string of digits, e.g. ``"1659"``.
        identifier: ``identifier``, one or more, e.g. ``["wasde"]``; what
            ``get_publication``, ``list_releases`` and ``get_latest_release`` take.
        title: ``title``, e.g. ``"World Agricultural Supply and Demand Estimates"``.
        agency_acronym: ``agency_acronym``, e.g. ``["WAOB"]``, ``["AMS", "AMS-DA"]``;
            ``None`` where upstream leaves it out.
        publication_agency_export_1: ``publication_agency_export_1``, e.g. ``["WAOB"]``;
            ``None`` where upstream leaves it out.
        frequency: ``frequency``, text, e.g. ``"Monthly"``, ``"Weekly"``.
        status: ``status``, a ``Status``, e.g. ``Status.ACTIVE`` (``"Active"``).
        resource_type: ``resource_type``, a ``ResourceType``, e.g.
            ``ResourceType.REPORT`` (``"Report"``).
    """

    id: str
    identifier: list[str]
    title: str
    agency_acronym: list[str] | None
    publication_agency_export_1: list[str] | None
    frequency: str
    status: Status
    resource_type: ResourceType


class Release(UpstreamModel):
    """One release of a publication, with its files: the YAML's schema ``Release``.

    Shape from ``tests/fixtures/release_find_all/page0.json`` (25 releases, NASS and
    WAOB), ``release_find_by_id/796099.json`` (WASDE of 2026-10-09),
    ``release_find_by_id/95621.json`` (WASDE of 2013-08-12, an original and a revised
    file of each format), ``release_find_by_identifier/wasde_page0.json`` and
    ``release_find_by_pub_id/1659_page0.json`` (25 WASDE releases each). Where the wire
    differs from the document (README's deviations): ``id`` is a string and ``files`` are
    absolute URLs on the same host. ``release_files()`` reads ``files`` into
    ``ReleaseFile`` items, in upstream order, without a request.

    Attributes:
        id: ``id``, a string of digits, e.g. ``"796099"``; the ``releaseId`` of
            ``esmis_api_release_findById``.
        files: ``files``, absolute URLs, e.g.
            ``["https://esmis.nal.usda.gov/sites/default/release-files/796099/wasde1026.pdf",
            ...]``; one to six per recorded release.
        title: ``title``, the publication's title, e.g. ``"World Agricultural Supply and
            Demand Estimates"``.
        release_datetime: ``release_datetime``, printed ``YYYY-MM-DDTHH:MM:SS+0000``,
            e.g. ``"2026-10-09T12:00:00+0000"``, parsed into an aware ``datetime`` with
            the offset as printed, ``+00:00``. The offset is upstream's label, and
            upstream's own calendar and file times contradict it (README); the model
            keeps it as printed, and how the tasks report it in ``meta`` is in
            ``tasks.py``'s docstring.
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

    def release_files(self) -> list["ReleaseFile"]:
        """The release's ``files`` in upstream order, each read by ``ReleaseFile.from_url``.

        No request: the name and format come from each URL's text. Release 95621 (WASDE of
        2013-08-12) gives six, ``ORIGwasde-08-12-2013.xml`` before
        ``wasde-08-12-2013.xml`` among them; ``list_release_files`` answers this list.
        """
        return [ReleaseFile.from_url(url) for url in self.files]


class ReleaseFile(UpstreamModel):
    """One file of a release: an item of ``Release.files``, with its name and format.

    Read from the URL's text alone, as upstream prints it, by ``from_url``; nothing is
    fetched, decoded or renamed. The catalog states no size, so none is given: a download
    reports its bytes. Recorded release files are named ``<name>.<extension>`` with the
    extensions ``pdf``, ``txt``, ``xls``, ``xml`` and ``zip``
    (``tests/fixtures/release_find_all/page0.json``,
    ``release_find_by_identifier/wasde_page0.json``); a few WASDE releases name a file
    ``latest.pdf`` or ``wasde0626v2.txt``, and the WASDE of 2013-08-12 lists an original
    and a revised file of one format, ``ORIGwasde-08-12-2013.xml`` and
    ``wasde-08-12-2013.xml`` (``release_find_by_id/95621.json``).

    Attributes:
        url: The item of ``Release.files`` verbatim, e.g.
            ``"https://esmis.nal.usda.gov/sites/default/release-files/796099/wasde1026.txt"``.
        name: The URL path's last segment as printed, e.g. ``"wasde1026.txt"``.
        format: The name's extension after its last dot, lowercased, e.g. ``"txt"``,
            ``"pdf"``, ``"xls"``, ``"xml"``, ``"zip"``; ``""`` for a name without one.
    """

    url: str
    name: str
    format: str

    @classmethod
    def from_url(cls, url: str) -> Self:
        """The file an item of ``Release.files`` links to, read from the URL's text alone.

        The name is the URL path's last segment as printed, the format the name's extension
        after its last dot, lowercased, ``""`` for a name without one; nothing is fetched.

        Args:
            url: An item of ``Release.files`` verbatim, e.g.
                ``"https://esmis.nal.usda.gov/sites/default/release-files/796099/wasde1026.txt"``
                (name ``"wasde1026.txt"``, format ``"txt"``).
        """
        name = urlsplit(url).path.rsplit("/", 1)[-1]
        _, dot, extension = name.rpartition(".")
        return cls(url=url, name=name, format=extension.lower() if dot else "")


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
