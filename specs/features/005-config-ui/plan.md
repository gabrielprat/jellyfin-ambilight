# Plan: Configuration UI

## Architecture decisions

### Why vanilla JS (not React/Vue/etc)

- Plugin config page is served as an embedded resource — no build step possible
- No npm, no webpack, no bundler — the HTML file IS the entire UI
- Jellyfin's own config pages use vanilla JS — we follow the same pattern
- Single-file deployment: edit HTML → rebuild → done

### Why tabs (not separate pages)

- Plugin system serves one page per plugin via `IHasWebPages`
- Tabs keep all functionality in one page — no routing needed
- Settings and extraction manager are related contexts

## UI structure

```
configPage.html
├── <head> — styles (inline CSS)
├── <body>
│   ├── #tabSelector — select to switch tabs
│   ├── #settingsTab
│   │   ├── Extraction section
│   │   ├── AMB3 Format Settings section
│   │   ├── LED Configuration section
│   │   ├── WLED Device Mappings section
│   │   ├── Lightning Tuning section
│   │   └── Debug section
│   └── #managerTab
│       ├── Filter bar (type, status, search)
│       ├── Video list (tree view)
│       ├── Extract All Pending button
│       └── Statistics display
└── <script> — all JS logic
```

## API interactions

### Load config

```
GET /Ambilight/Configuration → populate all form fields
```

### Save config

```
Collect form data → POST /Ambilight/Configuration
```

### Load video list

```
GET /Users/{userId}/Items?Recursive=true&IncludeItemTypes=Movie,Episode
  → build tree view
POST /Ambilight/Status/Batch { itemIds: [...] }
  → annotate each item with extraction status
```

### Trigger extraction

```
POST /Ambilight/Extract/{itemId} → show progress indicator
```

### Poll progress

```
Every 5s: POST /Ambilight/Status/Batch → update progress bars
Stop polling when no items have status "extracting" or "queued"
```

### Folder browser

```
GET /Environment/Drives → list drives
GET /Environment/DirectoryContents?path={path} → list folders
GET /Environment/ParentPath?path={path} → go up
```

### Device list

```
GET /Devices → populate device select dropdowns
```

## State management

- Config loaded once on page load, saved on form submit
- Video list loaded on tab switch to Manager
- Progress polling starts when extraction triggered, stops when complete
- No reactive framework — direct DOM manipulation
