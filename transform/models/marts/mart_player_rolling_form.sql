-- Rolling 5- and 10-game form per player and season. Shooting % in a window is computed from
-- windowed totals (not an average of per-game percentages).
select
    player_id,
    season,
    game_id,
    game_date_et,
    points,
    game_score,
    count(*)                         over w5  as games_in_last5,
    round(avg(points)                over w5, 1)  as points_last5,
    round(avg(rebounds)              over w5, 1)  as rebounds_last5,
    round(avg(assists)               over w5, 1)  as assists_last5,
    round(avg(game_score)            over w5, 1)  as game_score_last5,
    round(avg(points)                over w10, 1) as points_last10,
    round(avg(game_score)            over w10, 1) as game_score_last10,
    round(
        sum(points) over w10
        / nullif(2.0 * (sum(fga) over w10 + 0.44 * sum(fta) over w10), 0), 3) as true_shooting_last10,
    -- Positive = playing above their season-to-date average
    round(avg(game_score) over w5 - avg(game_score) over season_to_date, 1)    as form_vs_season
from {{ ref('fct_player_games') }}
window
    w5  as (partition by player_id, season order by game_date_et, game_id rows between 4 preceding and current row),
    w10 as (partition by player_id, season order by game_date_et, game_id rows between 9 preceding and current row),
    season_to_date as (partition by player_id, season order by game_date_et, game_id
                       rows between unbounded preceding and current row)
