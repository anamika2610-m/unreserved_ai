data_dict = {
"listings": {
"table_name": "listings",
"description": (
"This table stores comprehensive information for all property listings that are created for auctions, "
"reverse auctions, or direct sale processes on the platform. It acts as a central operational structure "
"that holds pricing configurations, auction rules, bid tracking details, lifecycle events, and listing "
"visibility settings. "
"Each record in this table represents a unique instance of a property being offered to buyers, "
"with dynamic fields supporting both fixed-price listings and time-bound auction-based transactions. "
"The table also supports automated auction behaviors, such as scheduled bid increments or price "
"reductions, and captures audit information essential for compliance, platform transparency, and reporting."
),
"columns": [

{
"name": "id",
"description": "System-generated unique identifier assigned to every listing record.",
"usages": "Primary key used across the system to track, reference, and manage listing-level operations.",
"format": "UUID",
"type": "uuid",
"distinct": "Unique"
},

{
"name": "property_id",
"description": "Identifier linking the listing to the corresponding base property.",
"usages": "Enables mapping between property master data and its market-facing listing instances.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "property_attribute_id",
"description": "Identifier representing the specific property variation or configuration (e.g., apartment unit, plot size).",
"usages": "Used for listings where a single property has multiple sellable units or attributes.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "crm_listing_id",
"description": "External CRM identifier used for synchronizing listing details with third-party or internal CRM pipelines.",
"usages": "Ensures data consistency between platform listings and CRM-managed sales/marketing workflows.",
"format": "Alphanumeric",
"type": "varchar(255)",
"distinct": "NA"
},

{
"name": "campaign",
"description": "Specifies the sales or marketing campaign under which this listing is grouped.",
"usages": "Helps categorize listings for campaign reporting, lead attribution, and bulk operational actions.",
"format": "Enum",
"type": "campaign_type",
"distinct": "NA"
},

{
"name": "listing_type",
"description": "Indicates whether the property is being sold through auction, reverse auction, or direct listing.",
"usages": "Drives system workflows such as bidding interface, pricing visibility, and automation logic.",
"format": "Enum",
"type": "listing_type",
"distinct": "Auction, Reverse Auction, Direct"
},

{
"name": "listing_status",
"description": "Represents the overall lifecycle stage of the listing (e.g., draft, live, closed).",
"usages": "Used for filtering listings in dashboards, preventing actions on inactive listings, and workflow management.",
"format": "Enum",
"type": "listing_status",
"distinct": "NA"
},

{
"name": "auction_status",
"description": "Tracks the specific state of an active auction (e.g., upcoming, running, paused, completed).",
"usages": "Determines bidding availability, UI messaging, and backend job scheduling.",
"format": "Enum",
"type": "auction_status",
"distinct": "NA"
},

{
"name": "display_price",
"description": "Controls whether the listing’s price is visible to end users on the platform.",
"usages": "Allows premium or auction-based listings to hide pricing strategically.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "price",
"description": "Base price defined for a direct listing or the starting price for an auction.",
"usages": "Used in pricing displays, financial calculations, and determining bid eligibility.",
"format": "Decimal(12,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "reserve_price",
"description": "Minimum price threshold required for an auction to be considered successful.",
"usages": "Protects sellers by ensuring property isn't sold below a set minimum.",
"format": "Decimal(12,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "bid_increment",
"description": "Minimum allowed difference between consecutive bids.",
"usages": "Ensures orderly and meaningful bidding progression.",
"format": "Decimal(12,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "auction_increase_interval_minutes",
"description": "Time interval after which automated bid increments are applied (for forward auctions).",
"usages": "Used in automated auction mechanisms to adjust pricing dynamically.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "reverse_auction_decrease_amount",
"description": "Fixed value by which the listing price decreases periodically in a reverse auction.",
"usages": "Used to calculate schedule-based automated price drops.",
"format": "Decimal(12,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "reverse_auction_decrease_interval_minutes",
"description": "Frequency at which reverse auction price reduces.",
"usages": "Controls reverse auction timing and automation scripts.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "reverse_auction_next_decrease_at",
"description": "Timestamp indicating when the next automated price reduction will occur.",
"usages": "Used by schedulers to process timed price drops.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "currency",
"description": "Three-letter ISO currency code representing the pricing currency.",
"usages": "Used to format displayed prices and support multi-currency listings.",
"format": "ISO-4217 Code",
"type": "char(3)",
"distinct": "INR, USD, AED"
},

{
"name": "auction_start_date",
"description": "Timestamp when bidding officially opens for the auction.",
"usages": "Drives countdown timers, scheduling, and user notifications.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "auction_end_date",
"description": "Timestamp when bidding closes.",
"usages": "Determines final bid acceptance and triggers winner selection processes.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "highest_bid_price",
"description": "Current highest bid recorded for the listing.",
"usages": "Displayed to users and used to validate new bids.",
"format": "Decimal(12,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "highest_bid_id",
"description": "Reference to the bid entry that currently holds the top position.",
"usages": "Used for winner determination and audit trails.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "winning_bid_id",
"description": "Reference to the bid that ultimately won the auction.",
"usages": "Used for post-auction workflows such as payment and contract generation.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "total_bids",
"description": "Count of all bids placed for this listing.",
"usages": "Provides insights for analytics, engagement measurement, and bid traffic indicators.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "published_at",
"description": "Timestamp when the listing was made publicly visible.",
"usages": "Used to measure listing exposure duration and buyer engagement.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "paused_at",
"description": "Timestamp when the auction was temporarily paused by an admin.",
"usages": "Used to freeze bid activity and support pause/resume workflows.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "resumed_at",
"description": "Timestamp when a previously paused auction was resumed.",
"usages": "Used to calculate adjusted auction duration.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "latest_bid_at",
"description": "Timestamp when the most recent bid was placed.",
"usages": "Used for real-time monitoring, auto-extend logic, and analytics.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "admin_configuration_pending",
"description": "Indicates whether listing requires manual admin intervention before activation.",
"usages": "Prevents accidental activation and adds workflow control for compliance checks.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "is_active",
"description": "Indicates whether the listing is currently active and accessible.",
"usages": "Filters listings for all buyer-facing features; deactivates outdated listings.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "is_deleted",
"description": "Soft delete flag marking whether the listing has been removed from active use.",
"usages": "Supports reversible data deletion while preserving historical records.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "created_at",
"description": "System timestamp when the listing record was created.",
"usages": "Used for audit trails, data lineage, and chronological reporting.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "updated_at",
"description": "Timestamp of the most recent update to the listing.",
"usages": "Used to track modifications for troubleshooting, sync, and version management.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "deleted_at",
"description": "Timestamp indicating when the listing was marked as deleted.",
"usages": "Supports historical cleanup and data compliance retention policies.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "deleted_by",
"description": "Identifier of the user or admin who performed the delete operation.",
"usages": "Supports accountability, auditing, and compliance rules.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "disabled_by",
"description": "Identifier of the user who disabled the listing without deleting it.",
"usages": "Useful for tracking administrative overrides and suspension events.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
}

]
}
}


data_dict = {
"properties": {
"table_name": "properties",
"description": (
"This table serves as the master repository of all properties stored within the platform. "
"It contains core descriptive, structural, and categorization attributes required to uniquely "
"identify a property and present it to potential buyers, internal teams, and integrated systems. "
"The table stores marketing-friendly details (title, description), backend operational attributes "
"(category, type, location), and system state indicators (active, deleted). "
"Every row represents a distinct property entity that can later be listed for auction or direct sale. "
"This table acts as a foundational reference point for listings, attributes, pricing, and all downstream "
"marketplace activities. It also supports compliance, governance, and historical auditing through timestamp fields."
),
"columns": [

{
"name": "id",
"description": "System-generated unique identifier representing each property. "
               "This ID allows the platform to maintain a stable reference to the property across listings, CRM sync, "
               "user actions, and backend workflows.",
"usages": "Used as the primary key for joins, reference mapping, activity logging, and property-level operations.",
"format": "UUID",
"type": "uuid",
"distinct": "Unique"
},

{
"name": "crm_property_id",
"description": "Identifier used to map this property to corresponding entries inside an external CRM system. "
               "Ensures consistent synchronization of property data between platform and CRM workflows.",
"usages": "Supports CRM-to-platform integration, reconciliation, and external reporting consistency.",
"format": "Alphanumeric",
"type": "varchar(255)",
"distinct": "NA"
},

{
"name": "slug",
"description": "SEO-friendly string that uniquely identifies the property in URLs. "
               "Typically derived from title and location to improve search engine indexing.",
"usages": "Used to render clean URLs, improve SEO ranking, and enable easy sharing of property pages.",
"format": "Lowercase text with hyphens",
"type": "varchar(355)",
"distinct": "Unique"
},

{
"name": "title",
"description": "Short and human-friendly name for the property, used as the primary label on frontend interfaces.",
"usages": "Displayed in search results, property cards, listing pages, and marketing content.",
"format": "Free text",
"type": "text",
"distinct": "NA"
},

{
"name": "description",
"description": "Detailed textual description providing full context about features, specifications, and highlights. "
               "Intended for buyers to understand the property's unique selling points.",
"usages": "Displayed on property detail pages; used for search relevance scoring and NLP-driven recommendation systems.",
"format": "Long free text",
"type": "text",
"distinct": "NA"
},

{
"name": "hide_property",
"description": "Boolean flag indicating whether the property should be visible to end users. "
               "Allows internal teams to keep certain properties hidden while they are being verified or curated.",
"usages": "Used to implement admin-level visibility control and safeguard incomplete property data from going live.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "property_category",
"description": "Represents a high-level grouping or classification of the property, such as 'Residential', 'Commercial', "
               "or 'Land'. Used for macroscopic classification and portal-wide filtering.",
"usages": "Used for navigation filters, reporting segments, and homepage category buckets.",
"format": "Enum",
"type": "property_category",
"distinct": "NA"
},

{
"name": "property_type_id",
"description": "Foreign key reference indicating the detailed property type (e.g., Apartment, Villa, Plot). "
               "Allows granular classification beyond broad categories.",
"usages": "Used for type-specific filters, validations, analytics, and characteristic-specific templates.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "location_id",
"description": "Identifier linking the property to a geographical location hierarchy (city, locality, region).",
"usages": "Used for map rendering, geo-search, recommendation models, and location-based insights.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "is_active",
"description": "Indicates whether the property is active and eligible for listing or backend usage. "
               "Non-active properties may be archived, under review, or incomplete.",
"usages": "Filters out inactive properties from search, listing creation, and automated workflows.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "is_deleted",
"description": "Soft delete indicator marking whether the property has been logically removed. "
               "Allows the system to retain historical records without showing them publicly.",
"usages": "Used to maintain data integrity, preserve audit history, and support reversible deletion.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "deleted_at",
"description": "Timestamp capturing when a property was flagged as deleted. Useful for audit logs and cleanup routines.",
"usages": "Supports automated archival, audit verification, and historical reporting.",
"format": "Timestamp with Timezone",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "deleted_by",
"description": "Identifier of the admin or system actor who deleted the property. Provides traceability and accountability.",
"usages": "Used for governance logs, audit trails, and permission-based investigation.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "created_at",
"description": "System-generated timestamp capturing when the property record was first inserted.",
"usages": "Used in time-based reporting, lifecycle tracking, and debugging changes over time.",
"format": "Timestamp with Timezone",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "updated_at",
"description": "Timestamp representing the most recent modification to the property record.",
"usages": "Used for synchronization between services, change detection, and cache invalidation.",
"format": "Timestamp with Timezone",
"type": "timestamptz",
"distinct": "NA"
}

]
}
}


data_dict = {
"property_attributes": {
"table_name": "property_attributes",
"description": (
"This table stores detailed structural, physical, dimensional, and characteristic information about each property. "
"It acts as the extended attribute layer that supplements the base property table by capturing measurable aspects "
"such as areas, frontage, zoning details, interior counts, outdoor features, and build-related metadata. "
"Each row represents a complete attribute profile for a specific property, enabling granular filtering, "
"advanced search capabilities, valuation modeling, and rich property presentation on the platform. "
"This table is heavily used for buyer decision-making, listing eligibility checks, NLP-based recommendation engines, "
"and internal reporting related to property specifications."
),
"columns": [

{
"name": "id",
"description": "Primary key for the attribute record. System-generated UUID that represents this distinct attribute set.",
"usages": "Used as the canonical identifier when referencing detailed attributes in services, audits, and sync jobs. Example: when storing a snapshot of attributes for historical comparison or versioning.",
"format": "UUID",
"type": "uuid",
"distinct": "Unique"
},

{
"name": "property_id",
"description": "UUID that links this attribute set to the main `properties` record. Indicates which property these attributes describe.",
"usages": "Frequently used to fetch full property profile (join with `properties`) for UI display or to evaluate listing eligibility. Example: load attributes when a user opens a property detail page.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "zoning",
"description": "Text description or code representing municipal zoning classification (e.g., 'R1', 'Commercial', 'Mixed-Use'). May include local zoning notes.",
"usages": "Used in compliance checks, automated eligibility (e.g., can this property be converted to commercial use?), and to filter search results by permitted use. Analysts can map zoning to allowed floor-area-ratios for valuation scripts.",
"format": "Text",
"type": "varchar(255)",
"distinct": "NA"
},

{
"name": "bedrooms",
"description": "Integer count of bedrooms in the property. Represents primary sleeping rooms and should follow listing rules (e.g., exclude studio living areas).",
"usages": "Used as a primary filter for residential searches and to compute price-per-bedroom or suitability (family vs studio). Also used by recommendation models to match buyer preferences.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "bathrooms",
"description": "Integer count of full and half bathrooms. Clarify whether half-baths are included (store standard convention).",
"usages": "Displayed in listings, used in search facets, and contributes to valuation/amenity scores. Example: show '2.5 baths' if system supports halves.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "toilets",
"description": "Number of standalone toilet rooms (may overlap with bathrooms count depending on data model). Helpful in markets where toilets are counted separately.",
"usages": "Used to improve accuracy of amenity filters and to show complete sanitary fixtures count. Useful in regions where 'toilets' is a common buyer criterion.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "garages",
"description": "Number of enclosed garage spaces attached or dedicated to the property (not open parking).",
"usages": "Used to filter for covered parking and affects valuation—garages typically add premium to price-per-unit calculations.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "ensuites",
"description": "Count of bedrooms that have an attached private bathroom (ensuite).",
"usages": "Used to highlight premium features in the UI and as a factor in quality scoring and pricing models.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "is_land_house_package",
"description": "Boolean indicating the listing represents a bundled land + built-home package (true) or standalone land/building (false).",
"usages": "Used to adjust front-end messaging, to route to correct valuation models (land valuation vs house + land package), and to control required fields during listing creation.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "land_area",
"description": "Numeric measure of the total land parcel associated with the property. Store raw numeric value; interpret units from `land_area_unit`.",
"usages": "Used in land valuations, calculate price-per-area, and for mapping into geospatial area-based filters. Example: compute price-per-sqm for market comparisons.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "land_area_unit",
"description": "Unit of measure used for `land_area` (e.g., 'sqm', 'sqft', 'acres').",
"usages": "Important for normalized computations; transform to canonical unit for analytics (store mapping rules). Example: convert sqft to sqm for uniform reporting.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "floor_area",
"description": "Total internal built (floor) area used for living/working spaces. Excludes external land area.",
"usages": "Used for price-per-floor-area metrics, search filters (e.g., 'min 1000 sqft'), and to feed valuation models and tax/fee calculations.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "floor_area_unit",
"description": "Unit for `floor_area` (e.g., 'sqm', 'sqft').",
"usages": "Used to normalize area metrics across listings and ensure UI displays correct unit labels.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "frontage",
"description": "Linear measure of the front boundary of the property (useful for lots and commercial plots).",
"usages": "Used by developers and buyers to assess street access, exposure, and planning compliance. Transformers may compute frontage-to-area ratios for development feasibility analysis.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "frontage_unit",
"description": "Unit used for frontage (e.g., 'm', 'ft').",
"usages": "Ensure correct rendering and conversions when comparing across listings or performing engineering calculations.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "property_age",
"description": "Discrete category or numeric age representing how old the building is (could be 'new', '0-5', '6-20', or exact years depending on implementation).",
"usages": "Used in depreciation models, renovation recommendations, and UI badges (e.g., 'Newly Built'). Analysts use this to segment listings by maintenance risk.",
"format": "Enum",
"type": "property_age",
"distinct": "NA"
},

{
"name": "retail_area",
"description": "Built area dedicated to retail use for mixed-use or commercial properties.",
"usages": "Feeds into rent-yield calculations, commercial valuations, and lease recommendations. Useful when splitting total area into functional zones.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "retail_area_unit",
"description": "Unit for retail area measurement.",
"usages": "Used to align commercial metrics and convert to canonical units for reporting.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "warehouse_area",
"description": "Area designated for warehousing or storage purposes, relevant for industrial/commercial assets.",
"usages": "Used in logistics suitability checks, industrial valuations, and for matching with tenant requirements.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "warehouse_area_unit",
"description": "Unit for warehouse area measurement.",
"usages": "Used to standardize industrial area calculations across markets.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "office_area",
"description": "Area allocated to office use within the property footprint.",
"usages": "Used for corporate leasing, workspace planning, and commercial valuation. Enables per-area rent and occupancy modelling.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "office_area_unit",
"description": "Unit of measurement for the office area.",
"usages": "Used when aggregating mixed-use area types into total usable area for analytics.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "mezzanine_area",
"description": "Area of mezzanine or intermediate floors, often present in retail or industrial units.",
"usages": "Important for capacity planning (shelving, storage), influences valuation, and may affect building code compliance.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "mezzanine_area_unit",
"description": "Unit used for mezzanine area.",
"usages": "Used to convert and sum multi-level spaces to obtain total usable area.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "other_area",
"description": "Catch-all numeric area field for ancillary areas that don't map to defined categories (e.g., balconies, patios).",
"usages": "Keep for edge cases; ensure UI/ETL documents how this is used. Analysts should inspect this field before aggregating into total area.",
"format": "Decimal(7,2)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "other_area_unit",
"description": "Unit used by `other_area`.",
"usages": "Used to standardize miscellaneous areas when computing total usable area.",
"format": "Enum",
"type": "area_unit",
"distinct": "NA"
},

{
"name": "highlights",
"description": "Array of short textual highlights or feature tags (e.g., ['Ocean View','Pool','Near Metro']).",
"usages": "Rendered on listing cards for quick scanning, used as input to search-relevance weighting and NLP classifiers. Data quality note: normalize tag vocabulary to avoid duplicates.",
"format": "Text Array",
"type": "text[]",
"distinct": "NA"
},

{
"name": "car_ports",
"description": "Integer count of covered car-port parking spaces (distinct from garages).",
"usages": "Used to surface parking availability and as a factor in buyer decisions in dense urban markets.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "open_parking_spaces",
"description": "Integer count of uncovered or open parking slots associated with the property.",
"usages": "Displayed in listing specs and used for filtering when buyers require parking (open vs covered).",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "year_built",
"description": "Four-digit year when the building was originally constructed. If unknown, store null or use derived `property_age` buckets.",
"usages": "Used to compute exact property age, for restoration/maintenance planning, and to support legal/compliance checks.",
"format": "Integer",
"type": "integer",
"distinct": "NA"
},

{
"name": "energy_rating",
"description": "Numeric or decimal energy efficiency score assigned to the property (region-specific scale).",
"usages": "Used for sustainability badges, green-search filters, and to estimate energy-cost savings. Data-quality note: record source of rating and scale.",
"format": "Decimal(3,1)",
"type": "decimal",
"distinct": "NA"
},

{
"name": "valid_from",
"description": "Timestamp when this attribute record becomes effective (start of validity), enabling temporal versioning.",
"usages": "Useful for temporal queries (e.g., show attributes as-of a historic date) and for staging changes until they go live.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "valid_until",
"description": "Timestamp when this attribute record is no longer valid. Null typically means current.",
"usages": "Supports attribute lifecycle management, snapshot history, and rollback of attribute changes.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "created_at",
"description": "System timestamp when this attributes row was inserted into the database.",
"usages": "Used for audit trails, ETL incremental loads (change data capture), and debugging creation events.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "updated_at",
"description": "System timestamp of the most recent modification to this attribute record.",
"usages": "Used to detect changes for synchronization, to invalidate caches, and to drive notification triggers when attributes change.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
}

]
}
}

data_dict = {
"users": {
"table_name": "users",
"description": (
"This table stores core user account information for all platform participants, including buyers, sellers, "
"agents, and administrative users. It contains identity attributes, authentication details, profile metadata, "
"verification status, and account lifecycle indicators. "
"Each row represents a single user profile that can interact with the platform for bidding, listing management, "
"property enquiries, notifications, and account-based activities. "
"The table plays a critical role in access control, onboarding workflows, identity verification, "
"user engagement features, and maintaining compliance and audit trails through timestamps and status flags."
),
"columns": [

{
"name": "id",
"description": "System-generated unique identifier representing each user account.",
"usages": "Primary key for authentication, authorization, user activity tracking, and linking users to bids, listings, or actions.",
"format": "UUID",
"type": "uuid",
"distinct": "Unique"
},

{
"name": "auth_provider_id",
"description": "External or internal authentication provider reference ID. Represents the identity from OAuth or custom auth systems.",
"usages": "Used for mapping users authenticated via social login, SSO, or internal auth providers. Supports login reconciliation and identity resolution.",
"format": "Alphanumeric",
"type": "varchar(255)",
"distinct": "NA"
},

{
"name": "country_code",
"description": "International dialing country code associated with user's phone number.",
"usages": "Used for formatting phone numbers, enabling country-specific communication rules, and fraud/geo checks.",
"format": "Short Text",
"type": "varchar(4)",
"distinct": "NA"
},

{
"name": "phone_number",
"description": "Registered contact number of the user used for login, verification, and notifications.",
"usages": "Used for OTP-based authentication, SMS alerts, account recovery, and communication preferences.",
"format": "Text",
"type": "varchar(20)",
"distinct": "NA"
},

{
"name": "email",
"description": "Primary email address associated with the user’s account. Can be used for login, alerts, and notifications.",
"usages": "Used for email verification, login credentials, marketing communication, transactional emails, and identifying duplicate accounts.",
"format": "Text",
"type": "varchar(500)",
"distinct": "NA"
},

{
"name": "full_name",
"description": "User’s full legal name or preferred display name.",
"usages": "Displayed in dashboards, communication messages, bid history, and used for generating contracts or invoices.",
"format": "Text",
"type": "varchar(255)",
"distinct": "NA"
},

{
"name": "username",
"description": "Unique username chosen by the user for identification within the platform interface.",
"usages": "Used for display in public-facing areas such as reviews, bidding history, and messaging features.",
"format": "Text",
"type": "varchar(255)",
"distinct": "Unique (typically)"
},

{
"name": "bio",
"description": "Optional short biography or description provided by the user.",
"usages": "Used in agent profiles, seller introduction pages, or community sections. Enhances personalization.",
"format": "Text",
"type": "varchar(500)",
"distinct": "NA"
},

{
"name": "gender",
"description": "Gender selection as maintained in the system using a predefined enum. May include values like male, female, or unspecified.",
"usages": "Used for personalization, demographic analytics, and enabling inclusive onboarding experiences.",
"format": "Enum",
"type": "gender",
"distinct": "NA"
},

{
"name": "date_of_birth",
"description": "User’s date of birth as a full timestamp.",
"usages": "Used for age verification, eligibility checks (e.g., minimum age for bidding), personalized recommendations.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "is_verified",
"description": "Boolean indicator stating whether the user has completed verification (email, phone, or KYC).",
"usages": "Used to control access to restricted actions such as bidding, listing creation, or payments. Also used for trust and safety scoring.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "avatar",
"description": "UUID reference to the user's profile picture or avatar stored in a media table.",
"usages": "Used to render profile images in UI interfaces such as messaging, bidding leaderboards, and account settings.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "is_deleted",
"description": "Soft-delete flag indicating that the user account has been logically removed from active use.",
"usages": "Used to exclude users from login, analytics, and operational workflows while preserving historical data for compliance.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "deleted_at",
"description": "Timestamp showing when the account was soft-deleted.",
"usages": "Used for audit trails, retention management, and GDPR-like compliance reporting.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "deleted_by",
"description": "Identifier of the admin or system process that performed the delete action.",
"usages": "Ensures accountability in administrative actions and supports audit log reviews.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "is_disabled",
"description": "Flag indicating whether the user account is disabled (but not deleted).",
"usages": "Used to temporarily block user access in case of fraud suspicion, non-compliance, or manual intervention.",
"format": "Boolean",
"type": "boolean",
"distinct": "True, False"
},

{
"name": "disabled_at",
"description": "Timestamp marking when the user account was disabled.",
"usages": "Used for tracking account suspension periods and reinstatement controls.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "disabled_by",
"description": "Identifier of the person or system that disabled the user.",
"usages": "Used for auditing admin actions and maintaining transparent governance.",
"format": "UUID",
"type": "uuid",
"distinct": "NA"
},

{
"name": "created_at",
"description": "Timestamp when the user account was first created.",
"usages": "Used for cohort analysis, growth reporting, user journey mapping, and debugging account lifecycle.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
},

{
"name": "updated_at",
"description": "Timestamp representing the most recent update to the user account data.",
"usages": "Useful for tracking profile updates, syncing user data across services, and cache invalidation.",
"format": "Timestamptz",
"type": "timestamptz",
"distinct": "NA"
}

]
}
}
