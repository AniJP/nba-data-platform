-- Per-player season averages (players who appeared in at least one game).
select
    f.season,
    f.player_id,
    d.player_name,
    d.current_team_id,
    count(*)                                         as games,
    count(*) filter (where f.is_starter)             as games_started,
    round(avg(f.minutes), 1)                         as minutes_per_game,
    round(avg(f.points), 1)                          as points_per_game,
    round(avg(f.rebounds), 1)                        as rebounds_per_game,
    round(avg(f.assists), 1)                         as assists_per_game,
    round(avg(f.steals), 1)                          as steals_per_game,
    round(avg(f.blocks), 1)                          as blocks_per_game,
    round(avg(f.turnovers), 1)                       as turnovers_per_game,
    -- Season shooting % from totals (not an average of per-game %s)
    round(sum(f.fgm) / nullif(sum(f.fga), 0), 3)     as fg_pct,
    round(sum(f.fg3m) / nullif(sum(f.fg3a), 0), 3)   as fg3_pct,
    round(sum(f.ftm) / nullif(sum(f.fta), 0), 3)     as ft_pct,
    round(sum(f.points) / nullif(2.0 * (sum(f.fga) + 0.44 * sum(f.fta)), 0), 3) as true_shooting_pct,
    round(avg(f.game_score), 1)                      as avg_game_score,
    count(*) filter (where f.is_double_double)       as double_doubles
from {{ ref('fct_player_games') }} f
join {{ ref('dim_players') }} d using (player_id)
group by f.season, f.player_id, d.player_name, d.current_team_id
