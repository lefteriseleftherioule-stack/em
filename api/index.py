from flask import Flask, jsonify, request
import os
import traceback
import re
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "message": "Welcome to Euromillions API",
        "version": "1.0.0",
        "endpoints": {
            "draws": "/api/draws",
            "latest": "/api/latest",
            "sync": "/api/sync",
            "health": "/api/health"
        }
    })

@app.route('/api/health')
def health():
    try:
        import sys
        present_env = [k for k in ("DATABASE_URL",) if os.getenv(k)]
        return jsonify({
            "status": "ok",
            "python_version": sys.version,
            "env_present": present_env,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/api/draws')
def get_draws():
    try:
        from .db import get_draws as db_get_draws
        year_param = request.args.get('year')
        limit_param = request.args.get('limit')
        try:
            year = int(year_param) if year_param else None
        except ValueError:
            year = None
        try:
            limit = int(limit_param) if limit_param else None
        except ValueError:
            limit = None

        draws = db_get_draws(limit=limit, year=year)
        if draws:
            normalized = []
            for d in draws:
                nd = dict(d)
                if isinstance(nd.get('draw_date'), (datetime,)):
                    nd['draw_date'] = nd['draw_date'].strftime('%Y-%m-%d')
                elif nd.get('draw_date') and hasattr(nd.get('draw_date'), 'isoformat'):
                    nd['draw_date'] = nd['draw_date'].isoformat()
                normalized.append(nd)
            return jsonify({"data": normalized, "count": len(normalized)})
        return jsonify({"data": [], "count": 0})
    except Exception as e:
        return jsonify({"error": "Failed to fetch draws", "detail": str(e), "trace": traceback.format_exc()}), 500

@app.route('/api/latest')
def latest_draw():
    try:
        from .db import get_latest_draw
        row = get_latest_draw()
        if row:
            d = dict(row)
            if isinstance(d.get('draw_date'), (datetime,)):
                d['draw_date'] = d['draw_date'].strftime('%Y-%m-%d')
            elif d.get('draw_date') and hasattr(d.get('draw_date'), 'isoformat'):
                d['draw_date'] = d['draw_date'].isoformat()
            return jsonify({"data": d})
        return jsonify({"error": "No draws available"}), 404
    except Exception as e:
        return jsonify({"error": "Failed to get latest draw", "detail": str(e), "trace": traceback.format_exc()}), 500



@app.route('/api/sync', methods=['GET', 'POST'])
def sync_latest():
    try:
        from .db import ensure_schema, upsert_draw
        ensure_schema()

        source_url = "https://euromillions.api.pedromealha.dev/v1/latest"
        try:
            headers = {"Accept": "application/json"}
            resp = requests.get(source_url, timeout=15, headers=headers)
            resp.raise_for_status()
            latest_draw_data = resp.json()
            # The API returns a list of draws, we want the first one
            if isinstance(latest_draw_data.get('draws'), list) and latest_draw_data['draws']:
                draw_data = latest_draw_data['draws'][0]
                # Transform the API response to match our database schema
                draw = {
                    "draw_date": draw_data.get('date'),
                    "numbers": [int(n) for n in draw_data.get('numbers', [])],
                    "stars": [int(s) for s in draw_data.get('stars', [])],
                    "jackpot": None,  # API does not provide this
                    "winners": None   # API does not provide this
                }
            else:
                draw = None
        except Exception as e:
            return jsonify({"error": f"Failed to fetch from API: {e}"}), 502


        if not draw:
            return jsonify({"error": "Could not parse draw from page"}), 422

        ok = upsert_draw(draw)
        if not ok:
            return jsonify({"error": "Failed to persist draw"}), 500

        return jsonify({"status": "ok", "upserted": draw.get("draw_date")})
    except Exception as e:
        return jsonify({"error": "Sync failed", "detail": str(e), "trace": traceback.format_exc()}), 500
