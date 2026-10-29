"""NBA Data Platform dashboard (Streamlit).

    make dashboard            # local DuckDB warehouse
    NBA_WAREHOUSE_PATH=md:nba streamlit run dashboard/app.py   # MotherDuck

Reads only from the dbt marts (plus play-by-play staging for shot locations), never from raw data.
"""
from __future__ import annotations

import os

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

WAREHOUSE = os.environ.get("NBA_WAREHOUSE_PATH", "warehouse/nba.duckdb")

st.set_page_config(page_title="NBA Data Platform", page_icon="🏀", layout="wide")


@st.cache_resource
def connection() -> duckdb.DuckDBPyConnection:
    if WAREHOUSE.startswith("md:"):
        return duckdb.connect(WAREHOUSE)
    return duckdb.connect(WAREHOUSE, read_only=True)


@st.cache_data(ttl=600)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return connection().execute(sql, list(params)).df()


# --- sidebar ---------------------------------------------------------------
seasons = q("select distinct season from marts.mart_team_standings order by season desc")["season"].tolist()
if not seasons:
    st.warning("The warehouse is empty. Run `make backfill && make dbt-build` (or `make sample`) first.")
    st.stop()
season = st.sidebar.selectbox("Season", seasons)
last_game = q("select max(game_date_et) as d from marts.fct_team_games where season = ?", (season,))["d"][0]
st.sidebar.caption(f"Data through **{last_game}** · warehouse: `{WAREHOUSE}`")

st.title("🏀 NBA Data Platform")
tab_standings, tab_leaders, tab_player, tab_wp, tab_ops = st.tabs(
    ["Standings", "Leaders", "Player explorer", "Win probability", "Pipeline health"]
)

# --- standings ---------------------------------------------------------------
with tab_standings:
    standings = q(
        """
        select league_rank as "#", team_full_name as team, wins as w, losses as l, win_pct as "win %",
               home_record as home, away_record as away, last_10 as "L10", streak,
               points_per_game as ppg, opp_points_per_game as "opp ppg", avg_point_differential as diff
        from marts.mart_team_standings where season = ? order by league_rank
        """,
        (season,),
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Games played", int(q("select count(*)/2 as n from marts.fct_team_games where season = ?",
                                    (season,))["n"][0]))
    c2.metric("Best record", f'{standings.iloc[0]["team"]} ({standings.iloc[0]["w"]}-{standings.iloc[0]["l"]})')
    c3.metric("Best point differential", f'{standings["diff"].max():+.1f}')
    st.dataframe(standings, hide_index=True, use_container_width=True)

    st.subheader("Point differential")
    st.altair_chart(
        alt.Chart(standings).mark_bar().encode(
            x=alt.X("diff:Q", title="Avg point differential"),
            y=alt.Y("team:N", sort="-x", title=None),
            color=alt.condition("datum.diff > 0", alt.value("#2e7d32"), alt.value("#c62828")),
            tooltip=["team", "w", "l", "diff"],
        ),
        use_container_width=True,
    )

# --- leaders -----------------------------------------------------------------
with tab_leaders:
    min_games = st.slider("Minimum games played", 1, 40, 5)
    stat = st.selectbox(
        "Rank by",
        ["points_per_game", "rebounds_per_game", "assists_per_game", "true_shooting_pct", "avg_game_score"],
        format_func=lambda s: s.replace("_", " ").title(),
    )
    leaders = q(
        f"""
        select a.player_name as player, t.team_tricode as team, a.games, a.minutes_per_game as mpg,
               a.points_per_game as ppg, a.rebounds_per_game as rpg, a.assists_per_game as apg,
               a.true_shooting_pct as "ts %", a.avg_game_score as "game score", a.{stat} as value
        from marts.mart_player_season_averages a
        left join marts.dim_teams t on t.team_id = a.current_team_id
        where a.season = ? and a.games >= ?
        order by a.{stat} desc nulls last
        limit 25
        """,
        (season, min_games),
    )
    st.dataframe(leaders.drop(columns="value"), hide_index=True, use_container_width=True)

# --- player explorer ---------------------------------------------------------
with tab_player:
    players = q(
        """
        select player_id, player_name from marts.mart_player_season_averages
        where season = ? order by points_per_game desc
        """,
        (season,),
    )
    if players.empty:
        st.info("No players yet this season.")
    else:
        name = st.selectbox("Player", players["player_name"])
        pid = int(players.loc[players["player_name"] == name, "player_id"].iloc[0])
        avg = q("select * from marts.mart_player_season_averages where season = ? and player_id = ?",
                (season, pid)).iloc[0]
        cols = st.columns(5)
        for col, (label, key) in zip(cols, [("PPG", "points_per_game"), ("RPG", "rebounds_per_game"),
                                            ("APG", "assists_per_game"), ("TS%", "true_shooting_pct"),
                                            ("Game Score", "avg_game_score")]):
            col.metric(label, avg[key])

        form = q(
            """
            select game_date_et as date, points, points_last5, game_score, game_score_last5, form_vs_season
            from marts.mart_player_rolling_form where season = ? and player_id = ? order by date
            """,
            (season, pid),
        )
        st.subheader("Form: points per game and 5-game rolling average")
        st.line_chart(form.set_index("date")[["points", "points_last5"]])

        left, right = st.columns(2)
        with left:
            st.subheader("Shot profile")
            profile = q(
                """
                select zone, attempts, fg_pct, share_of_attempts
                from marts.mart_player_shot_profile where season = ? and player_id = ?
                order by attempts desc
                """,
                (season, pid),
            )
            st.altair_chart(
                alt.Chart(profile).mark_bar().encode(
                    x=alt.X("share_of_attempts:Q", axis=alt.Axis(format="%"), title="Share of attempts"),
                    y=alt.Y("zone:N", sort="-x", title=None),
                    tooltip=["zone", "attempts", alt.Tooltip("fg_pct:Q", format=".1%")],
                ),
                use_container_width=True,
            )
        with right:
            st.subheader("Shot locations")
            shots = q(
                """
                select a.x, a.y, a.shot_result as result, a.shot_distance_ft as distance
                from staging.stg_nba__pbp_actions a
                join staging.stg_nba__games g using (game_id)
                where g.season = ? and a.player_id = ? and a.is_field_goal and a.x is not null
                """,
                (season, pid),
            )
            st.altair_chart(
                alt.Chart(shots).mark_circle(size=40, opacity=0.7).encode(
                    x=alt.X("x:Q", title=None, axis=None),
                    y=alt.Y("y:Q", title=None, axis=None),
                    color=alt.Color("result:N", scale=alt.Scale(domain=["Made", "Missed"],
                                                                 range=["#2e7d32", "#c62828"])),
                    tooltip=["result", "distance"],
                ),
                use_container_width=True,
            )

        st.subheader("Team history")
        st.dataframe(
            q(
                """
                select s.stint_number as stint, t.team_full_name as team, s.start_date, s.end_date,
                       s.games_on_roster as games, s.is_current as current
                from marts.fct_player_team_stints s join marts.dim_teams t using (team_id)
                where s.player_id = ? order by s.stint_number
                """,
                (pid,),
            ),
            hide_index=True,
        )

# --- win probability calibration ---------------------------------------------
with tab_wp:
    cal = q("select * from marts.mart_win_probability_calibration order by model, prob_bucket")
    if cal.empty:
        st.info("No play-by-play win probabilities yet.")
    else:
        st.caption("When a model says the home team has a 70% chance, does it win about 70% of the time? "
                   "Points on the diagonal mean perfect calibration.")
        briers = cal.groupby("model")["model_brier_score"].first()
        cols = st.columns(len(briers))
        for col, (model, score) in zip(cols, briers.items()):
            col.metric(f"Brier score: {model}", f"{score:.4f}",
                       help="Mean squared error of the predictions; lower is better")
        diagonal = (alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]}))
                    .mark_line(strokeDash=[4, 4], color="gray").encode(x="x:Q", y="y:Q"))
        points = alt.Chart(cal).mark_line(point=True).encode(
            x=alt.X("avg_predicted:Q", title="Predicted home-win probability", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("actual_home_win_rate:Q", title="Actual home-win rate", scale=alt.Scale(domain=[0, 1])),
            color="model:N",
            tooltip=["model", "prob_bucket", "plays", "games", "avg_predicted", "actual_home_win_rate"],
        )
        st.altair_chart(diagonal + points, use_container_width=True)

# --- pipeline health ---------------------------------------------------------
with tab_ops:
    health = q("select * from ops.mart_pipeline_health order by run_date desc, job")
    if health.empty:
        st.info("No pipeline runs recorded yet.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Success rate (all runs)", f'{health["successful_runs"].sum() / health["runs"].sum():.0%}')
        c2.metric("Games loaded", int(health["games_written"].sum()))
        c3.metric("Stat corrections", int(health["games_corrected"].sum()))
        c4.metric("Payloads quarantined", int(health["payloads_quarantined"].sum()))
        st.subheader("Daily runs")
        st.dataframe(health, hide_index=True, use_container_width=True)
        st.subheader("Runtime by job (seconds)")
        st.line_chart(health.pivot_table(index="run_date", columns="job", values="avg_duration_s"))
