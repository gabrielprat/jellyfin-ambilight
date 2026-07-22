# Release Notes - v2.4.0

## Mixed Library Support

The Extraction Manager now correctly lists items from "mixed movies and shows" libraries. Previously, the config page filtered libraries to only `movies` and `tvshows` collection types, excluding mixed libraries entirely. The backend already supported all library types — only the UI filter was too restrictive. The filter has been removed since the API query already specifies `IncludeItemTypes: Movie,Episode`, so non-video libraries naturally return zero results.

## Documentation

- Added centered plugin thumbnail to the README.
- Updated the plugin settings screenshot.
