-- One row per team per game.
with sides as (
    select
        cast(payload.header.id as varchar)              as game_id,
        unnest(payload.header.competitions[1].competitors) as t
    from {{ ref('stg_nba__summary_payloads') }}
),

teams as (
    select
        s.game_id,
        cast(s.t.id as bigint)                                    as team_id,
        coalesce(m.nba_tricode, s.t.team.abbreviation)            as team_tricode,
        s.t.team.abbreviation                                     as espn_abbreviation,
        s.t.team.location                                         as team_city,
        s.t.team.name                                             as team_name,
        s.t.homeAway = 'home'                                     as is_home,
        cast(s.t.score as integer)                                as points,
        try_cast(s.t.linescores[1].displayValue as integer)       as q1_points,
        try_cast(s.t.linescores[2].displayValue as integer)       as q2_points,
        try_cast(s.t.linescores[3].displayValue as integer)       as q3_points,
        try_cast(s.t.linescores[4].displayValue as integer)       as q4_points
    from sides s
    left join {{ ref('espn_team_abbreviations') }} m
        on m.espn_abbreviation = s.t.team.abbreviation
)

select
    t.game_id,
    t.team_id,
    t.team_tricode,
    t.espn_abbreviation,
    t.team_city,
    t.team_name,
    o.team_id        as opponent_team_id,
    o.team_tricode   as opponent_tricode,
    t.is_home,
    t.points,
    o.points         as opponent_points,
    t.q1_points, t.q2_points, t.q3_points, t.q4_points
from teams t
join teams o on o.game_id = t.game_id and o.team_id <> t.team_id
