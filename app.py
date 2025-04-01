from flask import Flask, render_template, request
from analysis import analyze_player
from datetime import datetime, timezone, timedelta


app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        summoner_name = request.form['summoner_name']
        tagline = request.form['tagline']
        region = request.form['region']
        timezone = int(request.form['timezone_offset']) # Convert string to int
        num_games = int(request.form['num_games'])  # Convert string to int

        result = analyze_player(summoner_name, tagline, region, int(timezone), int(num_games))
        return render_template('results.html', **result)

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
