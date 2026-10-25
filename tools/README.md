# tools/

## `howdy-section-importer.user.js`

Gets class **meeting times** into MaroonWay, which is the one thing no data
source we have provides.

A&M closed its public course API in 2023, and the replacement sits behind NetID
plus Duo two-factor. Nothing server-side can read class times — and nothing
should ask a student for their NetID password. But the student is already
logged in, so this runs in *their* browser, reads the class-search results
already on screen, and posts them to the backend. No credential is read, stored
or transmitted.

### Setup

1. Install [Tampermonkey](https://www.tampermonkey.net/) (or Violentmonkey) and
   add this script.
2. Edit two constants at the top:
   - `TOKEN` — your backend's `IMPORT_TOKEN` (or `ADMIN_TOKEN`).
   - `ENDPOINT` — leave as-is if the backend is on `localhost:8000`.
3. Open Howdy's class search, run a search.
4. Click **MaroonWay: import sections**, bottom right.

It previews first — a `dry_run` that writes nothing — and shows how many
sections and meetings it found and what it skipped. Confirm to import.

### If it finds nothing

Expected on the first run, and not a bug worth guessing around: the page is
behind a login, so the selectors could not be written against it in advance.
The script tries the page's own JSON, then a generic table parse driven by the
column headers, then logs every table it saw and its headers to the console.

Open the console, read that output, and either adjust the `columns` map in
`fromTable()` or send the header list along and it can be finished in one pass.

### What the backend does with it

`POST /sections/import` normalises whatever shape arrives through the same
`persist()` the CSV loader uses, so an imported section and an exported one are
indistinguishable afterwards. A section with no usable meeting time is stored
without meetings and **counted**, never given an invented time, and the
response names the courses and instructors it could not resolve.

Imported sections are schedulable immediately — `POST /schedule` picks them up
on the next request.
