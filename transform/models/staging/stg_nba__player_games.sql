-- One row per player per game, including players who did not play (played = false).
with teams as (
    select
        cast(payload.header.id as varchar) as game_id,
        unnest(payload.boxscore.players)  as tp
    from {{ ref('stg_nba__summary_payloads') }}
),

athletes as (
    select
        game_id,
        cast(tp.team.id as bigint)           as team_id,
        tp.statistics[1].keys                as k,
        unnest(tp.statistics[1].athletes)    as ath
    from teams
),

sides as (
    select game_id, team_id, opponent_team_id, is_home
    from {{ ref('stg_nba__team_games') }}
)

select
    a.game_id,
    a.team_id,
    s.opponent_team_id,
    s.is_home,
    cast(a.ath.athlete.id as bigint)                                         as player_id,
    a.ath.athlete.displayName                                                as player_name,
    split_part(a.ath.athlete.displayName, ' ', 1)                            as first_name,
    nullif(regexp_replace(a.ath.athlete.displayName, '^\S+\s*', ''), '')     as last_name,
    cast(a.ath.athlete.jersey as varchar)                                    as jersey_number,
    nullif(a.ath.athlete.position.abbreviation, '')                          as position,
    coalesce(a.ath.starter, false)                                           as is_starter,
    not coalesce(a.ath.didNotPlay, false)                                    as played,
    coalesce(try_cast({{ espn_stat('a.ath.stats', 'a.k', 'minutes') }} as double), 0) as minutes,
    {{ espn_int('a.ath.stats', 'a.k', 'points') }}                           as points,
    {{ espn_int('a.ath.stats', 'a.k', 'offensiveRebounds') }}                as offensive_rebounds,
    {{ espn_int('a.ath.stats', 'a.k', 'defensiveRebounds') }}                as defensive_rebounds,
    {{ espn_int('a.ath.stats', 'a.k', 'rebounds') }}                         as rebounds,
    {{ espn_int('a.ath.stats', 'a.k', 'assists') }}                          as assists,
    {{ espn_int('a.ath.stats', 'a.k', 'steals') }}                           as steals,
    {{ espn_int('a.ath.stats', 'a.k', 'blocks') }}                           as blocks,
    {{ espn_int('a.ath.stats', 'a.k', 'turnovers') }}                        as turnovers,
    {{ espn_int('a.ath.stats', 'a.k', 'fouls') }}                            as personal_fouls,
    {{ espn_made('a.ath.stats', 'a.k', 'fieldGoalsMade-fieldGoalsAttempted') }}      as fgm,
    {{ espn_attempted('a.ath.stats', 'a.k', 'fieldGoalsMade-fieldGoalsAttempted') }} as fga,
    {{ espn_made('a.ath.stats', 'a.k', 'threePointFieldGoalsMade-threePointFieldGoalsAttempted') }}      as fg3m,
    {{ espn_attempted('a.ath.stats', 'a.k', 'threePointFieldGoalsMade-threePointFieldGoalsAttempted') }} as fg3a,
    {{ espn_made('a.ath.stats', 'a.k', 'freeThrowsMade-freeThrowsAttempted') }}      as ftm,
    {{ espn_attempted('a.ath.stats', 'a.k', 'freeThrowsMade-freeThrowsAttempted') }} as fta,
    cast({{ espn_int('a.ath.stats', 'a.k', 'plusMinus') }} as double)         as plus_minus
from athletes a
join sides s on s.game_id = a.game_id and s.team_id = a.team_id
