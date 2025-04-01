import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta
from math import log2

HEADERS = {}

MATCH_ROUTING_MAP = {
    'na1': 'americas', 'br1': 'americas', 'la1': 'americas', 'la2': 'americas', 'oc1': 'americas',
    'euw1': 'europe', 'eun1': 'europe', 'tr1': 'europe', 'ru': 'europe', 'me': 'europe',
    'kr': 'asia', 'jp1': 'asia', 'ph2': 'asia', 'sg2': 'asia', 'th2': 'asia', 'tw2': 'asia', 'vn2': 'asia'
}

def get_puuid(name, tag, region):
    print(f"🔍 Fetching PUUID for {name}#{tag} in region {region}...")
    routing = MATCH_ROUTING_MAP.get(region, 'americas')
    url = f'https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}'
    res = requests.get(url, headers=HEADERS)
    res.raise_for_status()
    return res.json()['puuid']

def get_match_ids(puuid, total_count, region):
    print(f"💾 Fetching up to {total_count} match IDs...")
    routing = MATCH_ROUTING_MAP.get(region, 'americas')
    match_ids = []
    for start in range(0, total_count, 100):
        count = min(100, total_count - start)
        url = f'https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start={start}&count={count}'
        res = requests.get(url, headers=HEADERS)
        res.raise_for_status()
        match_ids.extend(res.json())
    return match_ids

def get_match_data(match_id, region):
    routing = MATCH_ROUTING_MAP.get(region, 'americas')
    url = f'https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}'
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 429:
        print("⚠️ Rate limit hit. Sleeping for 120 seconds...")
        time.sleep(120)
        return get_match_data(match_id, region)
    res.raise_for_status()
    return res.json()

def round_hour(timestamp_ms, tz_offset):
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) + timedelta(hours=tz_offset)
    hour = dt.hour
    minute = dt.minute
    return (hour + 1) % 24 if minute >= 30 else hour

def extract_stats(match, puuid, tz_offset):
    info = match['info']
    game_start = info['gameStartTimestamp']
    game_length = round(info['gameDuration'] / 60)
    player = next(p for p in info['participants'] if p['puuid'] == puuid)
    return {
        'Start Time (Rounded)': f"{round_hour(game_start, tz_offset):02d}:00",
        'Win': 'Win' if player['win'] else 'Lose',
        'Game Length (min)': game_length,
        'Kills': player['kills'],
        'Deaths': player['deaths'],
        'Assists': player['assists'],
        'Start Timestamp': game_start,
        'Game Duration (s)': info['gameDuration'],
        'Match ID': match['metadata']['matchId'],
    }

def print_progress_bar(current, total, bar_length=30):
    filled = int(bar_length * current // total)
    bar = '#' * filled + '-' * (bar_length - filled)
    print(f"[{bar}] {current}/{total} games scanned")

def group_sessions(df):
    df = df.sort_values(by='Start Timestamp').reset_index(drop=True)
    sessions = [1]
    session_id = 1
    for i in range(1, len(df)):
        prev_end = df.loc[i - 1, 'Start Timestamp'] + df.loc[i - 1, 'Game Duration (s)']
        curr_start = df.loc[i, 'Start Timestamp']
        if curr_start - prev_end > 2 * 3600 * 1000:
            session_id += 1
        sessions.append(session_id)
    df['Session'] = sessions
    return df

def analyze_gap(df, after_result):
    rows = []
    for i in range(len(df) - 1):
        a, b = df.iloc[i], df.iloc[i + 1]
        if a['Win'] != after_result:
            continue
        gap = (b['Start Timestamp'] - (a['Start Timestamp'] + a['Game Duration (s)'])) / 60000
        if 0 <= gap <= 120:
            win_b = 1 if b['Win'] == 'Win' else 0
            bucket = f"{int(gap // 5) * 5}-{int(gap // 5) * 5 + 5} min"
            rows.append((bucket, win_b))

    df_gap = pd.DataFrame(rows, columns=['Bucket', 'Win'])
    summary = df_gap.groupby('Bucket').agg(Game_Pairs=('Win', 'count'), Wins=('Win', 'sum')).reset_index()
    summary['Winrate (%)'] = round(100 * summary['Wins'] / summary['Game_Pairs'], 1)
    summary['Score'] = summary.apply(lambda r: round(r['Wins'] * log2(r['Winrate (%)'] + 1), 2), axis=1)
    return summary.sort_values(by='Score', ascending=False)

def analyze_sessions(df):
    df['WinBool'] = df['Win'] == 'Win'
    summary = df.groupby('Session').agg(
        Games_Played=('WinBool', 'count'),
        Wins=('WinBool', 'sum'),
        Winrate=('WinBool', lambda x: round(100 * x.mean(), 1))
    ).reset_index()
    summary['Ranking Score'] = summary.apply(
        lambda row: round(row['Winrate'] * log2(row['Wins'] + 1), 2) if row['Wins'] > 0 else 0.0, axis=1
    )
    return summary.sort_values(by='Ranking Score', ascending=False)

def analyze_hourly(df):
    df['Hour'] = df['Start Timestamp'].apply(lambda ts: datetime.fromtimestamp(ts / 1000, tz=timezone.utc).hour)
    hourly = df.groupby('Hour').agg(
        Games_Played=('Win', 'count'),
        Wins=('Win', lambda x: (x == 'Win').sum())
    ).reset_index()
    hourly['Winrate (%)'] = round(100 * hourly['Wins'] / hourly['Games_Played'], 1)
    hourly['Score'] = hourly.apply(lambda row: round(row['Wins'] * log2(row['Winrate (%)'] + 1), 2), axis=1)
    return hourly.sort_values(by='Score', ascending=False)

def analyze_lengths(df):
    rows = []
    for _, g in df.groupby('Session'):
        length = len(g)
        wins = (g['Win'] == 'Win').sum()
        rows.append((length, wins))
    df_len = pd.DataFrame(rows, columns=['Length', 'Wins'])
    summary = df_len.groupby('Length').agg(Sessions=('Wins', 'count'), Total_Wins=('Wins', 'sum')).reset_index()
    summary['Games_Played'] = summary['Length'] * summary['Sessions']
    summary['Winrate (%)'] = round(100 * summary['Total_Wins'] / summary['Games_Played'], 1)
    summary['Score'] = summary.apply(lambda r: round(r['Total_Wins'] * log2(r['Winrate (%)'] + 1), 2), axis=1)
    return summary.sort_values(by='Score', ascending=False)

def analyze_player(name, tag, region, timezone_offset, num_games):
    global HEADERS
    HEADERS = {"X-Riot-Token": 'RGAPI-228ad607-67e5-4576-bb84-f778f21e5f78'}

    puuid = get_puuid(name, tag, region)
    match_ids = get_match_ids(puuid, num_games, region)
    print(f"📊 Fetching data for {len(match_ids)} matches...")

    matches = []
    for i, mid in enumerate(match_ids, 1):
        match = get_match_data(mid, region)
        matches.append(match)
        if i % 5 == 0 or i == len(match_ids):
            print_progress_bar(i, len(match_ids))

    stats = [extract_stats(match, puuid, int(timezone_offset)) for match in matches]
    df = pd.DataFrame(stats)
    df = group_sessions(df)

    print("\n📊 Match Table with Sessions:")
    print(df[['Session', 'Start Time (Rounded)', 'Win', 'Game Length (min)', 'Kills', 'Deaths', 'Assists']])

    print("\n🏆 Session Summary with Ranking:")
    session_summary = analyze_sessions(df)
    print(session_summary[['Session', 'Games_Played', 'Winrate', 'Ranking Score']])

    print("\n🔍 Game Gap Winrate (After a Win):")
    after_win = analyze_gap(df, 'Win')
    print(after_win)

    print("\n🔍 Game Gap Winrate (After a Loss):")
    after_loss = analyze_gap(df, 'Lose')
    print(after_loss)

    print("\n📈 Best Performing Session Lengths:")
    session_lengths = analyze_lengths(df)
    print(session_lengths[['Length', 'Sessions', 'Games_Played', 'Total_Wins', 'Winrate (%)', 'Score']])

    print("\n⏰ Winrate by Hour of Day (UTC):")
    hourly = analyze_hourly(df)
    print(hourly[['Hour', 'Games_Played', 'Wins', 'Winrate (%)', 'Score']])

    return {
        "summoner_name": name,
        "tagline": tag,
        "timezone": f"UTC{int(timezone_offset):+d}",
        "best_hour": f"{int(hourly.iloc[0]['Hour']):02d}:00",
        "best_session_length": int(session_lengths.iloc[0]['Length']),
        "best_gap_after_win": after_win.iloc[0]['Bucket'],
        "best_gap_after_loss": after_loss.iloc[0]['Bucket'],
        "hourly_top": hourly.head(3).to_html(index=False, classes="table table-sm table-bordered", border=0),
        "session_lengths_top": session_lengths.head(3).to_html(index=False, classes="table table-sm table-bordered", border=0),
        "after_win_top": after_win.head(3).to_html(index=False, classes="table table-sm table-bordered", border=0),
        "after_loss_top": after_loss.head(3).to_html(index=False, classes="table table-sm table-bordered", border=0),
        "full_session_summary": session_summary.to_html(index=False, classes="table table-sm table-bordered", border=0)
    }
