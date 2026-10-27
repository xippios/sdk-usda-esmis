# Release Calendar

An excerpt of https://esmis.nal.usda.gov/release-calendar, written by
`scripts/refresh_upstream.py`; `../FETCHED.md` records the fetch, with the full page's
size and sha256. The page changes daily, so this file keeps its structure only. Its main
content is the heading above and an empty calendar container, which the browser fills
from the events in the page's `drupal-settings-json`; the page has no HTML table.
Breadcrumbs, the site's header, navigation and footer are dropped.

## Calendar settings

The page's `drupal-settings-json` holds one calendar under `fullcalendar`, keyed by a
view DOM id (`js-view-dom-id-…`, left out here). Its settings as fetched,
`options.eventSources` left out:

```json
{
  "uses_fields": false,
  "title_field": "",
  "url_field": "",
  "updateConfirm": true,
  "showMessages": true,
  "bundle_type": "",
  "createTarget": "",
  "modalWidth": 600,
  "showNonCurrentDates": "1",
  "dayHeaders": "1",
  "windowResizeDelay": "100",
  "colors": {
    "color_bundle": {
      "api_documentation": [],
      "page": [],
      "publication": [],
      "release": []
    },
    "tax_field": "",
    "vocabularies": "",
    "color_taxonomies": []
  },
  "convert_timezones": true,
  "options": {
    "firstDay": "0",
    "weekends": false,
    "navLinks": true,
    "aspectRatio": "",
    "height": "auto",
    "header": {
      "left": "dayGridMonth,timeGridWeek,timeGridDay",
      "center": "title",
      "right": "today prev,next"
    }
  },
  "view_name": "release_calendar",
  "view_display": "release_calendar",
  "entityType": "node",
  "token": "",
  "timeZone": "America/New_York",
  "locale": "en",
  "convertTzs": true
}
```

## Events

`options.eventSources` holds 1 event source with 3776 events in all, for 109 distinct
`id`s, their `start` from `2018-07-30T15:00:00-04:00` to `2026-12-31T15:00:00-05:00`.
Every event has the same fields, in this order: `id`, `eid`, `startField`, `endField`,
`allDay`, `start`, `end`, `editable`, `type`, `className`, `title`, `url`. The first 10
events as fetched, one JSON object per line:

```json
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-06-20T15:00:00-04:00", "end": "2024-06-20T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-07-17T15:00:00-04:00", "end": "2024-07-17T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-08-21T15:00:00-04:00", "end": "2024-08-21T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-09-18T15:00:00-04:00", "end": "2024-09-18T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-10-23T15:00:00-04:00", "end": "2024-10-23T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-11-20T15:00:00-05:00", "end": "2024-11-20T17:00:00-05:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2024-12-18T15:00:00-05:00", "end": "2024-12-18T17:00:00-05:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2025-01-23T15:00:00-05:00", "end": "2025-01-23T17:00:00-05:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2025-02-20T15:00:00-05:00", "end": "2025-02-20T17:00:00-05:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
{"id": "1861", "eid": 0, "startField": "publication_upcoming_releases", "endField": "publication_upcoming_releases", "allDay": false, "start": "2025-03-19T15:00:00-04:00", "end": "2025-03-19T17:00:00-04:00", "editable": false, "type": "datetime", "className": " fc-event-past", "title": "Announcement of Advanced Prices and  Pricing Factors", "url": "/publication/announcement-advanced-prices-and-pricing-factors"}
```

… 3766 more rows not kept (the page changes daily)
