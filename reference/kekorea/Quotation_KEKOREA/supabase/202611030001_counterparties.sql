BEGIN;

CREATE TABLE IF NOT EXISTS public.kekorea_counterparties (
    company_key text PRIMARY KEY CHECK (length(trim(company_key)) > 0),
    legal_name text NOT NULL CHECK (length(trim(legal_name)) > 0),
    aliases text[] NOT NULL DEFAULT '{}',
    address text,
    contact text,
    phone text,
    email text,
    registration_details text,
    default_ship_to text,
    ship_to_phone text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.kekorea_counterparties ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.kekorea_counterparties FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.kekorea_counterparties TO service_role;

COMMENT ON TABLE public.kekorea_counterparties IS
    'Private verified company directory. Runtime fills missing document fields only.';
COMMENT ON COLUMN public.kekorea_counterparties.default_ship_to IS
    'Explicitly registered default delivery address, never inferred from the company address.';

NOTIFY pgrst, 'reload schema';
COMMIT;
