-- One row per ingestion run. The log is append-only, so keep the latest record per run_id.
with src as (
    select
        *,
        row_number() over (partition by run_id order by finished_at desc nulls last) as rn
    from {{ source('ops', 'run_log') }}
)

select
    run_id,
    job,
    season,
    cast(started_at as timestamptz)               as started_at,
    cast(finished_at as timestamptz)              as finished_at,
    cast(started_at as timestamptz)::date         as run_date,
    cast(duration_s as double)                    as duration_s,
    cast(requests as integer)                     as requests,
    cast(games_written as integer)                as games_written,
    cast(coalesce(games_corrected, 0) as integer) as games_corrected,
    cast(quarantined as integer)                  as quarantined,
    cast(not_available as integer)                as ids_not_available,
    coalesce(len(errors), 0)                      as error_count,
    errors[1]                                     as first_error,
    status
from src
where rn = 1
