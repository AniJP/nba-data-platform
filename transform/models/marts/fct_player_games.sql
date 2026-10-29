{{
    config(
        materialized='incremental',
        unique_key=['game_id', 'player_id'],
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

-- Player box-score facts with advanced metrics. Incremental: each run only processes games
-- ingested since the last build, and late corrections to a game replace its rows (delete+insert).
with games as (
    select * from {{ ref('stg_nba__games') }}
    {% if is_incremental() %}
    where ingested_at > (select coalesce(max(ingested_at), '1900-01-01'::timestamptz) from {{ this }})
    {% endif %}
)

select
    p.game_id,
    p.player_id,
    p.team_id,
    p.opponent_team_id,
    g.season,
    g.game_date_et,
    p.is_home,
    p.is_starter,
    p.minutes,
    p.points,
    p.rebounds,
    p.offensive_rebounds,
    p.defensive_rebounds,
    p.assists,
    p.steals,
    p.blocks,
    p.turnovers,
    p.personal_fouls,
    p.fgm, p.fga, p.fg3m, p.fg3a, p.ftm, p.fta,
    p.plus_minus,
    -- True shooting %: points per shooting possession (FTA weighted 0.44)
    case when p.fga + 0.44 * p.fta > 0
         then round(p.points / (2.0 * (p.fga + 0.44 * p.fta)), 4) end          as true_shooting_pct,
    -- Effective FG %: credits threes for their extra point
    case when p.fga > 0 then round((p.fgm + 0.5 * p.fg3m) / p.fga, 4) end       as effective_fg_pct,
    -- John Hollinger's Game Score
    round(
        p.points + 0.4 * p.fgm - 0.7 * p.fga - 0.4 * (p.fta - p.ftm)
        + 0.7 * p.offensive_rebounds + 0.3 * p.defensive_rebounds
        + p.steals + 0.7 * p.assists + 0.7 * p.blocks
        - 0.4 * p.personal_fouls - p.turnovers, 1)                             as game_score,
    (p.points >= 10)::int + (p.rebounds >= 10)::int + (p.assists >= 10)::int
        + (p.steals >= 10)::int + (p.blocks >= 10)::int >= 2                   as is_double_double,
    g.ingested_at
from {{ ref('stg_nba__player_games') }} p
join games g using (game_id)
where p.played
