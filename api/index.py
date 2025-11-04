from flask import Flask, jsonify, request
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Mock data for demonstration purposes
# In a real implementation, this would connect to a database
# Database connection is configured via DATABASE_URL environment variable
MOCK_DRAWS = [
    {
        "id": 1,
        "draw_date": "2023-01-03",
        "numbers": [3, 12, 15, 25, 43],
        "stars": [10, 11],
        "jackpot": 17000000,
        "winners": {
            "rank1": 0,
            "rank2": 3,
            "rank3": 6,
            "rank4": 37,
            "rank5": 92,
            "rank6": 186,
            "rank7": 398,
            "rank8": 2123,
            "rank9": 2893,
            "rank10": 6198,
            "rank11": 14211,
            "rank12": 33286,
            "rank13": 67269
        }
    },
    {
        "id": 2,
        "draw_date": "2023-01-06",
        "numbers": [5, 13, 18, 39, 45],
        "stars": [8, 12],
        "jackpot": 30000000,
        "winners": {
            "rank1": 1,
            "rank2": 5,
            "rank3": 8,
            "rank4": 45,
            "rank5": 112,
            "rank6": 223,
            "rank7": 456,
            "rank8": 2345,
            "rank9": 3456,
            "rank10": 7890,
            "rank11": 15678,
            "rank12": 35678,
            "rank13": 70123
        }
    }
]

@app.route('/')
def home():
    return jsonify({
        "message": "Welcome to Euromillions API",
        "version": "1.0.0",
        "endpoints": {
            "draws": "/api/draws",
            "draws_by_year": "/api/draws/year/{year}",
            "draw_by_id": "/api/draws/{id}",
            "stats": "/api/stats"
        }
    })

@app.route('/api/draws')
def get_draws():
    return jsonify({
        "data": MOCK_DRAWS,
        "count": len(MOCK_DRAWS)
    })

@app.route('/api/draws/<int:draw_id>')
def get_draw_by_id(draw_id):
    draw = next((d for d in MOCK_DRAWS if d["id"] == draw_id), None)
    if draw:
        return jsonify({"data": draw})
    return jsonify({"error": "Draw not found"}), 404

@app.route('/api/draws/year/<int:year>')
def get_draws_by_year(year):
    draws = [d for d in MOCK_DRAWS if datetime.strptime(d["draw_date"], "%Y-%m-%d").year == year]
    return jsonify({
        "data": draws,
        "count": len(draws)
    })

@app.route('/api/stats')
def get_stats():
    # Mock statistics
    return jsonify({
        "most_frequent_numbers": [5, 15, 27, 37, 44],
        "most_frequent_stars": [2, 8],
        "least_frequent_numbers": [1, 10, 22, 33, 48],
        "least_frequent_stars": [1, 10],
        "total_draws": len(MOCK_DRAWS)
    })

# Vercel requires the app to be exported
app = app
