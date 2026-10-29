-- Daily pipeline health per job: the data behind an on-call dashboard.
select
    run_date,
    job,
    count(*)                                              as runs,
    count(*) filter (where status = 'success')            as successful_runs,
    round(avg((status = 'success')::int), 3)              as success_rate,
    sum(requests)                                         as requests,
    sum(games_written)                                    as games_written,
    sum(games_corrected)                                  as games_corrected,
    sum(quarantined)                                      as payloads_quarantined,
    round(avg(duration_s), 1)                             as avg_duration_s,
    round(max(duration_s), 1)                             as max_duration_s,
    sum(error_count)                                      as errors,
    max(first_error) filter (where status = 'failed')     as sample_error
from {{ ref('stg_ops__pipeline_runs') }}
group by run_date, job
