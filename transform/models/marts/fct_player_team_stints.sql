-- Player team stints (trade/signing history) derived from game rosters with a gaps-and-islands
-- pattern: a new stint starts whenever a player's team differs from their previous game's team.
-- Unlike a snapshot, this rebuilds full history from a one-time backfill.
with appearances as (
    select p.player_id, p.team_id, g.season, g.game_date_et, g.game_time_utc
    from {{ ref('stg_nba__player_games') }} p   -- includes DNPs: being on the roster counts
    join {{ ref('stg_nba__games') }} g using (game_id)
),

flagged as (
    select
        *,
        case
            when lag(team_id) over (partition by player_id order by game_time_utc) is distinct from team_id
            then 1 else 0
        end as is_new_stint
    from appearances
),

numbered as (
    select
        *,
        sum(is_new_stint) over (
            partition by player_id order by game_time_utc
            rows between unbounded preceding and current row
        ) as stint_number
    from flagged
)

select
    player_id,
    stint_number,
    team_id,
    min(season)                                                          as first_season,
    min(game_date_et)                                                    as start_date,
    max(game_date_et)                                                    as end_date,
    count(*)                                                             as games_on_roster,
    stint_number = max(stint_number) over (partition by player_id)       as is_current
from numbered
group by player_id, stint_number, team_id
