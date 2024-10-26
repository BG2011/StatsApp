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
            
            # Sprawdź czy DataFrame nie jest pusty
            if stats_df.empty:
                return None
            
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
    query = request.args.get('query', '').lower().strip()
    if not query:
        return jsonify([])

    active_players = players.get_active_players()
    suggestions = []
    
    for player in active_players:
        full_name = f"{player['first_name']} {player['last_name']}".lower()
        first_name = player['first_name'].lower()
        last_name = player['last_name'].lower()
        
        if (query in full_name or 
            query in first_name or 
            query in last_name or 
            first_name.startswith(query) or 
            last_name.startswith(query)):
            suggestions.append(f"{player['first_name']} {player['last_name']}")

    suggestions = sorted(list(set(suggestions)))
    return jsonify(suggestions[:10])

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
    try:
        player_name = request.form['player_name']
        stat_type = request.form['stat_type']
        stat_value = float(request.form['stat_value'])
        over_under = request.form['over_under']
        season = request.form['season']

        # Get player ID and data
        first_name, last_name = player_name.split(' ', 1)
        player_data = next((p for p in players.get_active_players() 
                          if p['first_name'].lower() == first_name.lower() 
                          and p['last_name'].lower() == last_name.lower()), None)
        
        if not player_data:
            return jsonify({"error": f"Player {player_name} not found.", "success": False})
            
        player_id = player_data['id']

        # Get player stats
        stats_df = get_player_stats(player_id, season)

        # Handle combined stats
        if stat_type == 'PTS_AST':
            stats_df['COMBINED'] = stats_df['PTS'] + stats_df['AST']
            stat_column = 'COMBINED'
            stat_display = 'Points + Assists'
        elif stat_type == 'PTS_REB':
            stats_df['COMBINED'] = stats_df['PTS'] + stats_df['REB']
            stat_column = 'COMBINED'
            stat_display = 'Points + Rebounds'
        elif stat_type == 'PTS_AST_REB':
            stats_df['COMBINED'] = stats_df['PTS'] + stats_df['AST'] + stats_df['REB']
            stat_column = 'COMBINED'
            stat_display = 'Points + Assists + Rebounds'
        else:
            stat_column = stat_type
            stat_display = {
                'PTS': 'Points',
                'AST': 'Assists',
                'REB': 'Rebounds',
                'STL': 'Steals',
                'BLK': 'Blocks',
                'TOV': 'Turnovers',
                'FG3M': '3 Points',
                'DD': 'Double-double',
                'TD': 'Triple-double'
            }.get(stat_type, stat_type)

        total_games = len(stats_df)
        
        if total_games == 0:
            return jsonify({
                "error": "No games found for this player in the selected season.",
                "success": False
            })

        # Mark covered games
        if stat_type in ['DD', 'TD']:
            stats_df['covered'] = (stats_df[stat_type] == 'YES') if over_under == 'over' else (stats_df[stat_type] == 'NO')
        else:
            stats_df['covered'] = (stats_df[stat_column] > stat_value) if over_under == 'over' else (stats_df[stat_column] < stat_value)

        line_hits = int(stats_df['covered'].sum())  # Konwersja na int
        hit_percentage = (line_hits / total_games) * 100 if total_games > 0 else 0

        message = f"Line {over_under} {stat_value} {stat_display} hit {line_hits}/{total_games} times ({hit_percentage:.1f}%)"
        
        # Konwertuj DataFrame na słownik, przekształcając wszystkie wartości na natywne typy Pythona
        stats_dict = stats_df.to_dict(orient='records')
        for game in stats_dict:
            # Konwertuj wszystkie wartości numpy na natywne typy Pythona
            for key, value in game.items():
                if hasattr(value, 'item'):  # Sprawdź czy to typ numpy
                    game[key] = value.item()
        
        return jsonify({
            "message": message, 
            "success": True,
            "hits": line_hits,
            "total": total_games,
            "percentage": f"{hit_percentage:.1f}",
            "stat_display": stat_display,
            "stats": stats_dict,
            "current_stat_type": stat_type,
            "current_stat_value": stat_value,
            "current_over_under": over_under
        })

    except Exception as e:
        print(f"Error in check_line: {str(e)}")
        return jsonify({"error": str(e), "success": False})


@app.route('/')
def index():
    seasons = generate_seasons()
    return render_template('player_stats.html', seasons=seasons, player_name='', selected_season='', stats=None)

# Obsługuje dane z formularza
@app.route('/search_player', methods=['POST'])
def search_player():
    player_name = request.form['player_name']
    season = request.form['season']
    
    try:
        first_name, last_name = player_name.split(' ', 1)
    except ValueError:
        return render_template('player_stats.html', 
                             seasons=generate_seasons(),
                             error_message="Please enter both first and last name.")

    # Pobierz ID gracza i jego dane
    player_dict = players.get_active_players()
    player_data = next((p for p in player_dict if p['first_name'].lower() == first_name.lower() 
                       and p['last_name'].lower() == last_name.lower()), None)
    
    if not player_data:
        return render_template('player_stats.html', 
                             seasons=generate_seasons(),
                             error_message=f"Player {first_name} {last_name} not found.")
    
    player_id = player_data['id']

    # Pobierz statystyki
    stats_df = get_player_stats(player_id, season)
    
    # Sprawdź czy mamy dane dla tego sezonu
    if stats_df is None or stats_df.empty:
        return render_template('player_stats.html', 
                             seasons=generate_seasons(),
                             error_message=f"No games found for {player_name} in season {season}")
    
    # Pobierz zespół z ostatniego meczu (MATCHUP format: "ORL vs. MIL" lub "ORL @ MIL")
    last_matchup = stats_df.iloc[0]['MATCHUP']
    player_team = last_matchup.split(' ')[0]  # Bierzemy pierwszy element (np. "ORL")

    # Przygotuj pełne nazwy zespołów
    team_names = {
        'ORL': 'Orlando Magic',
        'MIL': 'Milwaukee Bucks',
        'BOS': 'Boston Celtics',
        'BKN': 'Brooklyn Nets',
        'NYK': 'New York Knicks',
        'PHI': 'Philadelphia 76ers',
        'TOR': 'Toronto Raptors',
        'CHI': 'Chicago Bulls',
        'CLE': 'Cleveland Cavaliers',
        'DET': 'Detroit Pistons',
        'IND': 'Indiana Pacers',
        'ATL': 'Atlanta Hawks',
        'CHA': 'Charlotte Hornets',
        'MIA': 'Miami Heat',
        'WAS': 'Washington Wizards',
        'DEN': 'Denver Nuggets',
        'MIN': 'Minnesota Timberwolves',
        'OKC': 'Oklahoma City Thunder',
        'POR': 'Portland Trail Blazers',
        'UTA': 'Utah Jazz',
        'GSW': 'Golden State Warriors',
        'LAC': 'LA Clippers',
        'LAL': 'Los Angeles Lakers',
        'PHX': 'Phoenix Suns',
        'SAC': 'Sacramento Kings',
        'DAL': 'Dallas Mavericks',
        'HOU': 'Houston Rockets',
        'MEM': 'Memphis Grizzlies',
        'NOP': 'New Orleans Pelicans',
        'SAS': 'San Antonio Spurs'
    }

    full_team_name = team_names.get(player_team, 'N/A')
    averages = calculate_averages(stats_df)
    seasons = generate_seasons()

    return render_template('player_stats.html', 
                         seasons=seasons, 
                         player_name=player_data['full_name'],
                         player_id=player_id,
                         player_team=full_team_name,
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
