# Why Amenity Links Were Missing for Some Properties (and How It’s Fixed)

## Exact reason links were missing

Amenity links (Google Maps for nearby schools, hospitals, police stations, etc.) were missing for **some listing IDs even when latitude and longitude existed in the database**, because:

1. **Single schema path for location**  
   `get_listing_location(listing_id)` only tried one way to get coordinates:
   - `listings` → `properties` (via `property_id`) → `locations` (via `location_id`).

   If your schema differed (e.g. listing links to `locations` via `listings.location_id`, or lat/lon live on `listings` or use different column names), the function returned `None`. Generation then had no coordinates and did not create amenity links.

2. **No fallback when augmentation had no location**  
   If the RAG pipeline didn’t put lat/lon into `location_context` (e.g. no location chunk for that listing), generation only used that context. It did not always fetch location from the DB when building amenity links, so some properties never got links even when the DB had coordinates.

---

## How it’s handled now

### 1. Multiple schema paths in `get_listing_location`  
**File:** `app/db/postgres/repositories/listing_repository.py`

Location is resolved in order; the first successful path wins:

| Path | What it does |
|------|-------------------------------|
| **1** | `listings` → `properties` → `locations` (original path). |
| **2** | `listings` → `locations` via `listings.location_id`. |
| **3** | `listings.latitude`, `listings.longitude` (and optional `display_address`, `suburb`) on `listings`. |
| **4** | `listings.lat` / `listings.lng` or `listings.lat` / `listings.lon` (aliased to `latitude` / `longitude`). |

- Each path is tried only if the previous one didn’t return non-null lat/lon.
- Paths 3 and 4 are in `try/except` so missing columns don’t break the flow.
- If all paths fail, a debug log is written:  
  `get_listing_location: no lat/lon for listing_id=... (path1 row=...)`.

### 2. Generation always tries DB when building amenity links  
**File:** `app/services/rag_pipeline/generation.py` (section 5.5)

- If `location_context` has no latitude/longitude but `listing_id` is present, generation **always** calls `get_listing_location(listing_id)` before deciding whether to show amenity links.
- So links are generated whenever the DB can provide coordinates, even when RAG didn’t return any location context.

### 3. Step 4/4 and last-resort behaviour

- In **Step 4/4** (insufficient data): if we have `listing_id`, we fetch location from the DB; when we get coordinates we skip vendor escalation and set context so amenity links can be added.
- In the **final “last resort”**: we again fetch location by `listing_id` when we have no context; if we get coordinates we set context and add amenity links instead of showing the generic fallback.

### 4. Links only for amenity queries

- Amenity links are only set when `is_amenity_query(query)` is true (e.g. schools, hospitals, bars, police stations), so non-amenity questions (e.g. price trends) don’t get links.

---

## How to avoid this error in future

1. **Don’t assume a single location schema**  
   If you add a new way listings get coordinates (new table, new column names), add a **new path** in `get_listing_location` (and keep the existing paths). Document the path in this file and in the docstring of `get_listing_location`.

2. **Don’t rely only on RAG for coordinates**  
   Generation must still call `get_listing_location(listing_id)` when building amenity links if `location_context` has no lat/lon. Don’t remove that fallback.

3. **Use the debug log when links are missing**  
   If a listing has lat/lon in the DB but still doesn’t get links, check logs for:  
   `get_listing_location: no lat/lon for listing_id=...`  
   - If you see it, the DB layer isn’t finding coordinates (schema/column mismatch or missing data).  
   - If you don’t see it, the issue is likely in generation (e.g. query not classified as amenity, or an earlier return).

4. **New schema / columns**  
   If you introduce `listings.some_lat` / `listings.some_lon` (or similar), add a new try/except path in `get_listing_location` that selects those columns and maps them to the same return shape (`latitude`, `longitude`, optional `displayAddress`, `suburb`).

---

## Summary

| Before | After |
|--------|--------|
| One path: `listings` → `properties` → `locations` | Four paths; first successful wins; supports `listings.location_id`, lat/lon on `listings`, and `lat`/`lng`/`lon` names. |
| Links only if RAG provided location | Generation always tries `get_listing_location(listing_id)` when building amenity links if context has no coords. |
| No logging when location not found | Debug log when no path returns lat/lon. |

This way, amenity links appear whenever the database has coordinates for the listing, regardless of which schema path or which part of the pipeline provided them, and the same class of bug can be avoided by following the rules above.
