-- One row per final game.
with src as (
    select
        payload.header                    as h,
        payload.header.competitions[1]    as c,
        payload.gameInfo                  as gi,
        _meta,
        season
    from {{ ref('stg_nba__summary_payloads') }}
),

sides as (
    select cast(h.id as varchar) as game_id, unnest(c.competitors) as t
    from src
),

pivoted as (
    select
        game_id,
        max(cast(t.id as bigint))       filter (where t.homeAway = 'home') as home_team_id,
        max(cast(t.id as bigint))       filter (where t.homeAway = 'away') as away_team_id,
        max(cast(t.score as integer))   filter (where t.homeAway = 'home') as home_score,
        max(cast(t.score as integer))   filter (where t.homeAway = 'away') as away_score,
        max(len(t.linescores))                                             as periods_played
    from sides
    group by game_id
)

select
    cast(src.h.id as varchar)                                             as game_id,
    src.season,
    case cast(src.h.season.type as integer)
        when 2 then 'regular' when 3 then 'postseason' when 5 then 'play-in'
    end                                                                   as season_type,
    {{ espn_timestamp('src.c.date') }}                                    as game_time_utc,
    cast(timezone('America/New_York', {{ espn_timestamp('src.c.date') }}) as date) as game_date_et,
    case when src.c.status.type.completed then 3 else 2 end               as game_status,
    src.c.status.type.name                                                as game_status_text,
    p.periods_played,
    p.periods_played > 4                                                  as went_to_overtime,
    src.gi.venue.fullName                                                 as arena_name,
    try_cast(src.gi.attendance as integer)                                as attendance,
    p.home_team_id,
    p.away_team_id,
    p.home_score,
    p.away_score,
    cast(src._meta.ingested_at as timestamptz)                            as ingested_at,
    src._meta.run_id                                                      as ingest_run_id
from src
join pivoted p on p.game_id = cast(src.h.id as varchar)
