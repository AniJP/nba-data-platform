-- Standings per season: record, home/away splits, point differential, last-10 and current streak.
with games as (
    select
        *,
        row_number() over (partition by season, team_id order by game_time_utc desc) as games_ago
    from {{ ref('fct_team_games') }}
),

with_latest as (
    select
        season, team_id, won, games_ago,
        first_value(won) over (partition by season, team_id order by games_ago) as latest_won
    from games
),

-- A streak is the run of most-recent games whose result matches the latest game.
-- "breaks" counts result changes walking back in time; the streak is where breaks = 0.
streaks as (
    select
        *,
        sum(case when won <> latest_won then 1 else 0 end) over (
            partition by season, team_id order by games_ago
            rows between unbounded preceding and current row
        ) as breaks
    from with_latest
),

current_streak as (
    select
        season,
        team_id,
        concat(case when bool_or(won) then 'W' else 'L' end, count(*)) as streak
    from streaks
    where breaks = 0
    group by season, team_id
)

select
    g.season,
    g.team_id,
    d.team_tricode,
    d.team_full_name,
    count(*)                                                     as games_played,
    count(*) filter (where g.won)                                as wins,
    count(*) filter (where not g.won)                            as losses,
    round(avg(g.won::int), 3)                                    as win_pct,
    concat(count(*) filter (where g.won and g.is_home), '-',
           count(*) filter (where not g.won and g.is_home))      as home_record,
    concat(count(*) filter (where g.won and not g.is_home), '-',
           count(*) filter (where not g.won and not g.is_home))  as away_record,
    round(avg(g.points), 1)                                      as points_per_game,
    round(avg(g.opponent_points), 1)                             as opp_points_per_game,
    round(avg(g.margin), 1)                                      as avg_point_differential,
    concat(count(*) filter (where g.won and g.games_ago <= 10), '-',
           count(*) filter (where not g.won and g.games_ago <= 10)) as last_10,
    s.streak,
    rank() over (partition by g.season order by avg(g.won::int) desc, avg(g.margin) desc) as league_rank
from games g
join {{ ref('dim_teams') }} d using (team_id)
join current_streak s using (season, team_id)
group by g.season, g.team_id, d.team_tricode, d.team_full_name, s.streak
