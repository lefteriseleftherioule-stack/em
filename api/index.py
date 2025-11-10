from flask import Flask, jsonify, request
import os
import traceback
import requests
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



from bs4 import BeautifulSoup

def parse_draw_from_page(html_content):
    # Constrain parsing to the "Latest Result" section to avoid older draws
    lower_html = html_content.lower()
    latest_idx = lower_html.find('latest result')
    section = html_content[latest_idx:] if latest_idx != -1 else html_content

    # Find the date within this section: e.g., "Tuesday, 04 November 2025"
    date_pattern = r'([A-Za-z]+),\s+(\d{2})\s+([A-Za-z]+)\s+(\d{4})'
    date_match = re.search(date_pattern, section)
    if not date_match:
        return None

    day = date_match.group(2)
    month_name = date_match.group(3)
    year = date_match.group(4)

    month_map = {
        'January': '01', 'February': '02', 'March': '03', 'April': '04',
        'May': '05', 'June': '06', 'July': '07', 'August': '08',
        'September': '09', 'October': '10', 'November': '11', 'December': '12'
    }
    month = month_map.get(month_name, '01')
    draw_date = f"{year}-{month}-{day}"

    # Extract numbers only AFTER the date line within the section
    after_date = section[date_match.end(): date_match.end() + 4000]

    numbers = []
    stars = []

    # Scan for 1-2 digit numbers and pick first 5 (1-50) then first 2 stars (1-12)
    tokens = re.findall(r'\b\d{1,2}\b', after_date)
    for tok in tokens:
        try:
            n = int(tok)
        except ValueError:
            continue
        if len(numbers) < 5 and 1 <= n <= 50:
            numbers.append(n)
            continue
        if len(numbers) == 5 and len(stars) < 2 and 1 <= n <= 12:
            stars.append(n)
            if len(stars) == 2:
                break

    # If not found, try a more targeted pattern for stars nearby labels
    if len(numbers) == 5 and len(stars) < 2:
        star_match = re.search(r'(?:Stars?|Lucky\s*Stars?)\D*(\d{1,2})\D+(\d{1,2})', after_date, re.IGNORECASE)
        if star_match:
            s1 = int(star_match.group(1))
            s2 = int(star_match.group(2))
            if 1 <= s1 <= 12 and 1 <= s2 <= 12:
                stars = [s1, s2]

    # Final validation
    if len(numbers) != 5 or len(stars) != 2:
        return None

    if not all(1 <= n <= 50 for n in numbers) or not all(1 <= s <= 12 for s in stars):
        return None

    return {
        "draw_date": draw_date,
        "numbers": numbers,
        "stars": stars,
        "jackpot": None,
        "winners": None
    }

@app.route('/api/sync', methods=['GET', 'POST'])
def sync_latest():
    try:
        from .db import ensure_schema, upsert_draw
        ensure_schema()

        source_url = os.getenv("EURO_SOURCE_URL", "https://www.euro-millions.com/results")
        try:
            headers = {"Accept": "text/html"}
            resp = requests.get(source_url, timeout=15, headers=headers)
            resp.raise_for_status()
            draw = parse_draw_from_page(resp.text)
        except Exception as e:
            return jsonify({"error": f"Failed to fetch from page: {e}"}), 502


        if not draw:
            # Add some debugging information
            debug_info = {
                "error": "Could not parse draw from page",
                "html_preview": resp.text[:500] + "..." if len(resp.text) > 500 else resp.text,
                "html_length": len(resp.text),
                "url": source_url
            }
            return jsonify(debug_info), 422

        ok = upsert_draw(draw)
        if not ok:
            return jsonify({"error": "Failed to persist draw"}), 500

        return jsonify({"status": "ok", "upserted": draw.get("draw_date")})
    except Exception as e:
        return jsonify({"error": "Sync failed", "detail": str(e), "trace": traceback.format_exc()}), 500
