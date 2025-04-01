from flask import Flask, render_template, request
from analysis import analyze_player
from datetime import datetime, timezone, timedelta
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        summoner_name = request.form['summoner_name']
        tagline = request.form['tagline']
        region = request.form['region']
        timezone_offset = int(request.form['timezone_offset'])
        timezone_label = request.form['timezone_label']
        num_games = int(request.form['num_games'])

        result = analyze_player(
            summoner_name, tagline, region, timezone_offset, num_games
        )
        result["timezone_label"] = timezone_label  # Add this line to pass it to the template

        return render_template('results.html', **result)

    return render_template('index.html')


if __name__ == '__main__':
    from os import environ
    app.run(host='0.0.0.0', port=int(environ.get("PORT", 5000)))

