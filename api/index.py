from flask import Flask, jsonify, request
import os
import traceback
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
        present_env = [k for k in ("DATABASE_URL", "EURO_SOURCE_URL") if os.getenv(k)]
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

def scrape_latest_draw(soup):
    result = soup.find('div', class_='latest-result')
    if not result:
        return None

    draw_date = None
    date_tag = result.find('h3')
    if date_tag:
        date_text = date_tag.get_text(strip=True)
        try:
            draw_date = datetime.strptime(date_text, '%A, %d %B %Y').strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return None
    else:
        return None

    if not draw_date:
        return None

    balls = result.find_all('div', class_='ball')
    numbers = []
    stars = []
    for b in balls:
        txt = b.get_text(strip=True)
        try:
            num = int(txt)
            if 'star' in b.get('class', []):
                stars.append(num)
            else:
                numbers.append(num)
        except (ValueError, TypeError):
            continue

    if len(numbers) != 5 or len(stars) != 2:
        return None

    jackpot = None
    jackpot_div = result.find('div', class_='jackpot')
    if jackpot_div:
        jackpot_text = jackpot_div.get_text(strip=True).replace(',', '').replace('€', '')
        try:
            jackpot = int(float(jackpot_text))
        except (ValueError, TypeError):
            jackpot = None

    winners = {}
    table = result.find('table')
    if table:
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 2:
                rank = cols[0].get_text(strip=True)
                count_text = cols[1].get_text(strip=True).replace(',', '')
                if rank:
                    try:
                        winners[rank] = int(count_text)
                    except (ValueError, TypeError):
                        pass

    return {
        "draw_date": draw_date,
        "numbers": numbers,
        "stars": stars,
        "jackpot": jackpot,
        "winners": winners
    }

@app.route('/api/sync', methods=['GET', 'POST'])
def sync_latest():
    try:
        from .db import ensure_schema, upsert_draw
        ensure_schema()

        source_url = os.getenv('EURO_SOURCE_URL')
        if not source_url:
            return jsonify({"error": "EURO_SOURCE_URL not configured"}), 500

        import requests
        from bs4 import BeautifulSoup
        try:
            resp = requests.get(source_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            return jsonify({"error": f"Failed to fetch source: {e}"}), 502

        draw = scrape_latest_draw(soup)
        if not draw:
            return jsonify({"error": "Could not parse draw from page"}), 422

        ok = upsert_draw(draw)
        if not ok:
            return jsonify({"error": "Failed to persist draw"}), 500

        return jsonify({"status": "ok", "upserted": draw.get("draw_date")})
    except Exception as e:
        return jsonify({"error": "Sync failed", "detail": str(e), "trace": traceback.format_exc()}), 500
