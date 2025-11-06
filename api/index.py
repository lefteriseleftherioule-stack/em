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
    """
    Robustly extract latest draw data using multiple selectors and regex fallbacks.
    Returns dict or None if not parseable.
    """
    tried_classes = [
        'latest-result', 'result', 'results', 'euromillions-result', 'draw-result',
        'euromillions', 'content', 'main'
    ]
    container = None
    for cls in tried_classes:
        candidate = soup.find(lambda tag: tag.has_attr('class') and any(cls in c for c in tag.get('class', [])))
        if candidate:
            container = candidate
            break
    if not container:
        container = soup

    # Date detection
    draw_date = None
    candidate_texts = []
    for tagname in ['h1', 'h2', 'h3', 'time', 'p', 'div', 'span']:
        for tag in container.find_all(tagname, limit=50):
            t = tag.get_text(" ", strip=True)
            if t:
                candidate_texts.append(t)
    date_patterns = [
        (r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+\w+\s+\d{4}', '%A, %d %B %Y'),
        (r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+\w+\s+\d{4}', '%A %d %B %Y'),
        (r'\b\d{1,2}/\d{1,2}/\d{4}\b', '%d/%m/%Y'),
        (r'\b\d{4}-\d{2}-\d{2}\b', '%Y-%m-%d'),
    ]
    for text in candidate_texts:
        for regex, fmt in date_patterns:
            m = re.search(regex, text)
            if m:
                raw = m.group(0)
                try:
                    dt = datetime.strptime(raw, fmt)
                    draw_date = dt.strftime('%Y-%m-%d')
                    break
                except Exception:
                    if fmt == '%Y-%m-%d':
                        draw_date = raw
                        break
        if draw_date:
            break

    # Ball extraction
    numbers = []
    stars = []
    ball_like = container.select('[class*="ball"], [class*="number"], .numbers .ball, .result .ball')
    for el in ball_like:
        txt = el.get_text(strip=True)
        try:
            val = int(txt)
        except Exception:
            continue
        classes = el.get('class', [])
        classes_str = ' '.join(classes) if isinstance(classes, list) else str(classes or '')
        if 'star' in classes_str or 'lucky' in classes_str:
            stars.append(val)
        else:
            numbers.append(val)

    # Fallback heuristic
    if len(numbers) < 5 or len(stars) < 2:
        all_ints = [int(x) for x in re.findall(r'\b\d{1,2}\b', container.get_text(' ', strip=True))]
        ns = [x for x in all_ints if 1 <= x <= 50]
        ss = [x for x in all_ints if 1 <= x <= 12]
        if len(numbers) < 5 and len(ns) >= 5:
            numbers = ns[:5]
        if len(stars) < 2 and len(ss) >= 7:
            stars = ss[5:7]

    # Jackpot (optional)
    jackpot = None
    jack_text = ' '.join([str(el) for el in container.find_all(string=re.compile('jackpot', re.IGNORECASE))])
    m = re.search(r'€?\s*([\d,.]+)', jack_text)
    if m:
        try:
            jackpot = int(float(m.group(1).replace(',', '')))
        except Exception:
            jackpot = None

    # Winners (optional)
    winners = {}
    table = None
    for t in container.find_all('table'):
        txt = t.get_text(' ', strip=True).lower()
        if 'winner' in txt or 'prize' in txt:
            table = t
            break
    if table:
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 2:
                rank = cols[0].get_text(strip=True)
                count_text = cols[1].get_text(strip=True).replace(',', '')
                if rank:
                    try:
                        winners[rank] = int(count_text)
                    except Exception:
                        pass

    if not draw_date or len(numbers) != 5 or len(stars) != 2:
        return None

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
            headers = {"User-Agent": "Mozilla/5.0 (compatible; EuromillionsAPI/1.0)"}
            resp = requests.get(source_url, timeout=10, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            return jsonify({"error": f"Failed to fetch source: {e}"}), 502

        draw = scrape_latest_draw(soup)
        if not draw and request.args.get('debug') == '1':
            titles = [h.get_text(' ', strip=True) for h in soup.find_all('h1')[:2] + soup.find_all('h2')[:2] + soup.find_all('h3')[:2]]
            classes = sorted({c for tag in soup.find_all(True) for c in (tag.get('class') or [])})[:20]
            return jsonify({
                "error": "Could not parse draw from page",
                "hints": {"titles": titles, "sample_classes": classes}
            }), 422
        if not draw:
            return jsonify({"error": "Could not parse draw from page"}), 422

        ok = upsert_draw(draw)
        if not ok:
            return jsonify({"error": "Failed to persist draw"}), 500

        return jsonify({"status": "ok", "upserted": draw.get("draw_date")})
    except Exception as e:
        return jsonify({"error": "Sync failed", "detail": str(e), "trace": traceback.format_exc()}), 500
