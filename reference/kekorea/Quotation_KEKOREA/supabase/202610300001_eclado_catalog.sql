-- Schema only. Contains no commercial price data or credentials.
-- Run once, as the project database owner, before the private seed.
-- Existing table names cause a transaction rollback rather than a silent rewrite.
BEGIN;

CREATE TABLE public.kekorea_catalog_imports (
    id uuid PRIMARY KEY,
    source_label text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    source_files jsonb NOT NULL CHECK (jsonb_typeof(source_files) = 'array'),
    validation_issues jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(validation_issues) = 'array'),
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.kekorea_products (
    id uuid PRIMARY KEY,
    identity_key text NOT NULL UNIQUE CHECK (identity_key ~ '^[a-f0-9]{64}$'),
    brand text NOT NULL CHECK (length(trim(brand)) > 0),
    kind text NOT NULL CHECK (kind IN ('standard', 'sample')),
    source_code text NOT NULL CHECK (length(trim(source_code)) > 0),
    item_name text NOT NULL CHECK (length(trim(item_name)) > 0),
    capacity text,
    group_name text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Product code alone is intentionally NOT unique (source code 73568 is reused).
CREATE INDEX kekorea_products_code_idx ON public.kekorea_products (brand, kind, source_code);

CREATE TABLE public.kekorea_purchase_prices (
    id uuid PRIMARY KEY,
    import_id uuid NOT NULL REFERENCES public.kekorea_catalog_imports(id),
    product_id uuid NOT NULL REFERENCES public.kekorea_products(id),
    supplier_key text NOT NULL CHECK (length(trim(supplier_key)) > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    unit_price numeric(20,6) NOT NULL CHECK (unit_price >= 0 AND unit_price <> 'NaN'::numeric),
    price_basis text NOT NULL DEFAULT 'CATALOG_UNIT' CHECK (price_basis = 'CATALOG_UNIT'),
    effective_from date,
    effective_to date,
    source_sheet text NOT NULL,
    source_row integer NOT NULL CHECK (source_row > 0),
    source_column text NOT NULL CHECK (source_column ~ '^[A-Z]+$'),
    source_reference jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    UNIQUE (import_id, product_id, supplier_key, currency)
);
CREATE INDEX kekorea_purchase_prices_product_idx ON public.kekorea_purchase_prices(product_id);

CREATE TABLE public.kekorea_buyer_prices (
    id uuid PRIMARY KEY,
    import_id uuid NOT NULL REFERENCES public.kekorea_catalog_imports(id),
    product_id uuid NOT NULL REFERENCES public.kekorea_products(id),
    buyer_key text NOT NULL CHECK (length(trim(buyer_key)) > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    unit_price numeric(20,6) NOT NULL CHECK (unit_price >= 0 AND unit_price <> 'NaN'::numeric),
    price_basis text NOT NULL DEFAULT 'CATALOG_UNIT' CHECK (price_basis = 'CATALOG_UNIT'),
    reference_discount_percent numeric(7,4)
        CHECK (reference_discount_percent BETWEEN 0 AND 100),
    reference_discounted_price numeric(20,6),
    effective_from date,
    effective_to date,
    source_sheet text NOT NULL,
    source_row integer NOT NULL CHECK (source_row > 0),
    source_column text NOT NULL CHECK (source_column ~ '^[A-Z]+$'),
    source_reference jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    CHECK ((reference_discount_percent IS NULL AND reference_discounted_price IS NULL)
           OR (reference_discount_percent IS NOT NULL AND reference_discounted_price IS NOT NULL
               AND reference_discounted_price = round(unit_price * (1 - reference_discount_percent / 100), 6))),
    UNIQUE (import_id, product_id, buyer_key, currency)
);
CREATE INDEX kekorea_buyer_prices_product_idx ON public.kekorea_buyer_prices(product_id);

COMMENT ON COLUMN public.kekorea_products.capacity IS
    'Source Capacity, not order quantity. Null for samples whose capacity is not supplied.';
COMMENT ON COLUMN public.kekorea_buyer_prices.reference_discount_percent IS
    'Workbook reference only. An invoice must explicitly select its actual discount; do not apply this twice.';
COMMENT ON COLUMN public.kekorea_buyer_prices.price_basis IS
    'Price per catalog sales unit, including a complete set/pack described by Capacity.';
COMMENT ON COLUMN public.kekorea_purchase_prices.supplier_key IS
    'Internal supplier key, not a verified supplier legal name.';
COMMENT ON COLUMN public.kekorea_catalog_imports.source_label IS
    'Source file label; not an inferred contractual price validity date.';

ALTER TABLE public.kekorea_catalog_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kekorea_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kekorea_purchase_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kekorea_buyer_prices ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies: catalog costs and buyer prices stay private.
REVOKE ALL ON TABLE public.kekorea_catalog_imports, public.kekorea_products,
    public.kekorea_purchase_prices, public.kekorea_buyer_prices FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON TABLE public.kekorea_catalog_imports, public.kekorea_products,
    public.kekorea_purchase_prices, public.kekorea_buyer_prices TO service_role;

COMMIT;
