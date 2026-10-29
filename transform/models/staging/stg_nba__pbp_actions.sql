-- One row per play-by-play event.
with plays as (
    select
        cast(payload.header.id as varchar) as game_id,
        unnest(payload.plays)             as p
    from {{ ref('stg_nba__summary_payloads') }}
),

typed as (
    select
        game_id,
        cast(p.id as varchar)                                     as action_id,
        try_cast(p.sequenceNumber as integer)                     as action_number,
        cast(p.period.number as integer)                          as period,
        round({{ espn_clock_seconds('p.clock.displayValue') }}, 1) as seconds_remaining_in_period,
        try_cast(p.team.id as bigint)                             as team_id,
        try_cast(p.participants[1].athlete.id as bigint)          as player_id,
        p.type.text                                               as action_type,
        coalesce(p.shootingPlay, false)
            and try_cast(p.pointsAttempted as integer) in (2, 3)  as is_field_goal,
        try_cast(p.pointsAttempted as integer) = 3                as is_three,
        coalesce(p.scoringPlay, false)                            as is_scoring_play,
        try_cast(p.scoreValue as integer)                         as points,
        -- ESPN uses -214748340 as "no location"; real court coordinates are feet, hoop near (25, 0)
        case when try_cast(p.coordinate.x as double) between -5 and 55
             then try_cast(p.coordinate.x as double) end          as x,
        case when try_cast(p.coordinate.y as double) between -5 and 100
             then try_cast(p.coordinate.y as double) end          as y,
        try_cast(p.homeScore as integer)                          as score_home,
        try_cast(p.awayScore as integer)                          as score_away,
        p.text                                                    as description,
        {{ espn_timestamp_or_null('p.wallclock') }}               as wallclock_utc
    from plays
)

select
    *,
    case when is_field_goal then case when is_scoring_play then 'Made' else 'Missed' end end as shot_result,
    case when is_field_goal and x is not null and y is not null
         then round(sqrt(power(x - 25, 2) + power(y, 2)), 1) end                          as shot_distance_ft,
    -- seconds left in regulation (0 in overtime), used for win-probability modelling
    case when period <= 4 then (4 - period) * 720 + seconds_remaining_in_period else 0 end as seconds_remaining_in_game
from typed
