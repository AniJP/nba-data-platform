-- One row per team per game with result and margin.
select
    t.game_id,
    t.team_id,
    t.opponent_team_id,
    g.season,
    g.game_date_et,
    g.game_time_utc,
    t.is_home,
    t.points,
    t.opponent_points,
    t.points - t.opponent_points        as margin,
    t.points > t.opponent_points        as won,
    g.went_to_overtime,
    t.q1_points, t.q2_points, t.q3_points, t.q4_points
from {{ ref('stg_nba__team_games') }} t
join {{ ref('stg_nba__games') }} g using (game_id)
