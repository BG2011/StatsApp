from datetime import datetime
from flask import Flask, render_template, request, jsonify
from nba_api.stats.static import players
from nba_api.stats.endpoints import PlayerGameLog
import time

import requests

app = Flask(__name__)

# Funkcja pomocnicza do pobrania ID zawodnika na podstawie imienia i nazwiska
def get_player_id(first_name, last_name):
    player_dict = players.get_active_players()  # Pobieramy tylko aktywnych zawodników
    for player in player_dict:
        if player['first_name'].lower() == first_name.lower() and player['last_name'].lower() == last_name.lower():
            return player['id']
    return None

# Funkcja do pobrania logów z meczów danego zawodnika w sezonie
def get_player_stats(player_id, season, retries=3, timeout=60):
    for attempt in range(retries):
        try:
            game_log = PlayerGameLog(player_id=player_id, season=season, timeout=timeout)
            stats_df = game_log.get_data_frames()[0]  # Zwraca dane w formie pandas DataFrame
            
            # Dodajemy kolumny Double Double (DD) i Triple Double (TD)
            stats_df['DD'] = stats_df.apply(lambda row: 'YES' if count_double_double(row) >= 2 else 'NO', axis=1)
            stats_df['TD'] = stats_df.apply(lambda row: 'YES' if count_double_double(row) >= 3 else 'NO', axis=1)
            
            return stats_df
        except requests.exceptions.ReadTimeout:
            print(f"Timeout occurred, retrying... ({attempt + 1}/{retries})")
            time.sleep(2)
    raise Exception("Failed to fetch data after multiple retries")

# Funkcja do liczenia Double Double i Triple Double
def count_double_double(row):
    stats = [row['PTS'], row['REB'], row['AST'], row['STL'], row['BLK']]
    double_count = sum(1 for stat in stats if stat >= 10)
    return double_count

# Funkcja do obliczania średnich statystyk zawodnika
def calculate_averages(stats_df):
    avg_pts = stats_df['PTS'].mean()
    avg_ast = stats_df['AST'].mean()
    avg_reb = stats_df['REB'].mean()
    avg_stl = stats_df['STL'].mean()
    avg_blk = stats_df['BLK'].mean()
    avg_tov = stats_df['TOV'].mean()
    avg_3pts = stats_df['FG3M'].mean()  # FG3M to trafione trójki
    avg_pf = stats_df['PF'].mean()
    
    return {
        'avg_pts': round(avg_pts, 2),
        'avg_ast': round(avg_ast, 2),
        'avg_reb': round(avg_reb, 2),
        'avg_stl': round(avg_stl, 2),
        'avg_blk': round(avg_blk, 2),
        'avg_tov': round(avg_tov, 2),
        'avg_3pts': round(avg_3pts, 2),
        'avg_pf': round(avg_pf, 2)
    }


# Endpoint do obsługi autouzupełniania
@app.route('/autocomplete', methods=['GET'])
def autocomplete():
    query = request.args.get('query').lower()

    # Pobieramy tylko aktywnych zawodników
    active_players = players.get_active_players()

    # Wyszukujemy zawodników, którzy pasują do wpisanego zapytania (imię lub nazwisko)
    suggestions = list(set([f"{player['first_name']} {player['last_name']}" for player in active_players if query in (player['first_name'].lower() + ' ' + player['last_name'].lower())]))

    return jsonify(suggestions)

# Funkcja do generowania 5 ostatnich sezonów
def generate_seasons():
    current_year = datetime.now().year
    current_season_start = current_year if datetime.now().month >= 10 else current_year - 1
    seasons = []
    for i in range(5):
        season_start = current_season_start - i
        season_end = season_start + 1
        seasons.append(f"{season_start}-{str(season_end)[-2:]}")
    return seasons

# Endpoint for checking the line
@app.route('/check_line', methods=['POST'])
def check_line():
    player_name = request.form['player_name']
    stat_type = request.form['stat_type']
    stat_value = float(request.form['stat_value'])
    over_under = request.form['over_under']
    season = request.form['season']

    # Get player ID
    first_name, last_name = player_name.split(' ', 1)
    player_id = get_player_id(first_name, last_name)

    if not player_id:
        return jsonify({"message": f"Player {player_name} not found."})

    # Get player stats
    stats_df = get_player_stats(player_id, season)

    # Count how many times the stat exceeded or did not exceed the value
    if over_under == 'over':
        line_hits = stats_df[stats_df[stat_type] > stat_value].shape[0]
    else:
        line_hits = stats_df[stats_df[stat_type] < stat_value].shape[0]

    # Total number of games
    total_games = stats_df.shape[0]

    # Message to display
    message = f"Line {'over' if over_under == 'over' else 'under'} {stat_value} {stat_type} was hit {line_hits}/{total_games} times in the selected season."

    return jsonify({"message": message})


@app.route('/')
def index():
    seasons = generate_seasons()
    return render_template('player_stats.html', seasons=seasons, player_name='', selected_season='', stats=None)

# Obsługuje dane z formularza
@app.route('/search_player', methods=['POST'])
def search_player():
    player_name = request.form['player_name']
    season = request.form['season']

    # Rozbijamy imię i nazwisko (zakładamy, że są oddzielone spacją)
    try:
        first_name, last_name = player_name.split(' ', 1)
    except ValueError:
        return "Please enter both first and last name."

    # Pobieramy ID zawodnika
    player_id = get_player_id(first_name, last_name)
    if player_id is None:
        return f"Player {first_name} {last_name} not found."

    # Pobieramy statystyki zawodnika
    stats_df = get_player_stats(player_id, season)
    averages = calculate_averages(stats_df)

    # Przekazujemy dane do template'a HTML
    seasons = generate_seasons()
    return render_template('player_stats.html', 
                           seasons=seasons, 
                           player_name=player_name, 
                           selected_season=season, 
                           stats=stats_df.to_dict(orient='records'), 
                           avg_pts=averages['avg_pts'], 
                           avg_ast=averages['avg_ast'], 
                           avg_reb=averages['avg_reb'], 
                           avg_stl=averages['avg_stl'], 
                           avg_blk=averages['avg_blk'], 
                           avg_tov=averages['avg_tov'], 
                           avg_3pts=averages['avg_3pts'], 
                           avg_pf=averages['avg_pf'])

if __name__ == '__main__':
    app.run(debug=True)