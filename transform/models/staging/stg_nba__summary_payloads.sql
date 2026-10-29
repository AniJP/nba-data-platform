-- The only model that reads raw JSON. Lands each game summary once as a table so the staging
-- models below don't each re-scan (and re-decompress) every file.
select
    payload,
    _meta,
    season,
    filename as source_file
from {{ source('bronze', 'summary') }}
