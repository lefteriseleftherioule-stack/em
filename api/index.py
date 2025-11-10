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
    soup = BeautifulSoup(html_content, 'html.parser')

    # Strategy 1: Find explicit 'latest' container
    latest_result_container = soup.find('div', class_='latest')
    if not latest_result_container:
        latest_result_container = soup.find(class_=lambda x: isinstance(x, str) and ('latest-result' in x.lower() or 'latest' in x.lower()))

    # Strategy 2: Fall back to first heading mentioning EuroMillions Results
    date_heading = None
    if not latest_result_container:
        headings = soup.find_all(['h1', 'h2', 'h3'], string=re.compile(r'EuroMillions\s+Results', re.I))
        for h in headings:
            candidate_container = h.find_next(lambda t: t.name in ['section', 'article', 'div'] and t.get_text(strip=True))
            if candidate_container:
                latest_result_container = candidate_container
                date_heading = h
                break

    if not latest_result_container:
        # Fallback: use entire document as the container for broader parsing
        latest_result_container = soup

    # Extract date from the heading text (ignore numbers elsewhere)
    if not date_heading:
        date_heading = latest_result_container.find(['h1', 'h2', 'h3'])
        if not date_heading:
            return None

    date_text = date_heading.get_text(strip=True)
    # Try multiple date patterns in heading
    date_match = re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', date_text)
    if not date_match:
        date_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', date_text)
    if not date_match:
        date_match = re.search(r'(\d{2})\/(\d{2})\/(\d{4})', date_text)
    if not date_match:
        # As a last resort, scan the whole document for the first date occurrence
        full_text = soup.get_text(" ", strip=True)
        date_match = re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', full_text)
        if not date_match:
            date_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', full_text)
        if not date_match:
            date_match = re.search(r'(\d{2})\/(\d{2})\/(\d{4})', full_text)
        if not date_match:
            return None

    # Build ISO date
    if '/' in date_match.group(0):
        day = date_match.group(1)
        month = date_match.group(2)
        year = date_match.group(3)
    else:
        day = date_match.group(1).zfill(2)
        month_name = date_match.group(2)
        year = date_match.group(3)
        month_map = {
            'January': '01', 'February': '02', 'March': '03', 'April': '04',
            'May': '05', 'June': '06', 'July': '07', 'August': '08',
            'September': '09', 'October': '10', 'November': '11', 'December': '12'
        }
        month = month_map.get(str(month_name).capitalize(), '01')
    draw_date = f"{year}-{month}-{day}"

    # Extract numbers and stars using multiple strategies inside the container
    numbers = []
    stars = []

    # Prefer explicit balls container
    balls_container = latest_result_container.find('div', class_='balls')
    if not balls_container:
        # broader search: div/ul with class or id containing balls
        balls_container = latest_result_container.find(lambda t: t.name in ['div', 'ul'] and (
            (t.get('class') and any(re.search(r'\bballs?\b', c, re.I) for c in t.get('class'))) or
            ('balls' in (t.get('id') or ''))
        ))

    # Main numbers
    if balls_container:
        for ball_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'\bball\b', c, re.I)):
            text = ball_span.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', text):
                try:
                    n = int(text)
                    if 1 <= n <= 50:
                        numbers.append(n)
                except Exception:
                    pass

        # Lucky stars
        for star_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'(lucky\s*star|star)', c, re.I)):
            text = star_span.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', text):
                try:
                    s = int(text)
                    if 1 <= s <= 12:
                        stars.append(s)
                except Exception:
                    pass

    # Fallback: within latest_result_container, look for generic spans (ignore heading)
    if len(numbers) < 5:
        generic_spans = latest_result_container.find_all('span')
        for sp in generic_spans:
            # Skip spans inside the heading
            if date_heading and date_heading in sp.parents:
                continue
            text = sp.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', text):
                try:
                    val = int(text)
                    if 1 <= val <= 50 and val not in numbers:
                        numbers.append(val)
                except Exception:
                    pass
            if len(numbers) >= 5:
                break

    if len(stars) < 2:
        # Look for a "Lucky Stars" label, then collect following digit spans
        star_label = latest_result_container.find(string=re.compile(r'Lucky\s*Stars?', re.I))
        if star_label:
            parent = star_label.parent if hasattr(star_label, 'parent') else latest_result_container
            following_spans = parent.find_all_next('span', limit=6)
            for sp in following_spans:
                if date_heading and date_heading in sp.parents:
                    continue
                text = sp.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', text):
                    try:
                        val = int(text)
                        if 1 <= val <= 12 and val not in stars:
                            stars.append(val)
                    except Exception:
                        pass
                if len(stars) >= 2:
                    break

    # Final validation, with a robust fallback if primary extraction failed
    if len(numbers) != 5 or len(stars) != 2:
        # Document-level fallback: collect digits after the detected date text
        full_text = soup.get_text(" ", strip=True)
        try:
            start_idx = full_text.index(date_match.group(0)) + len(date_match.group(0))
        except Exception:
            start_idx = 0
        window = full_text[start_idx:start_idx + 6000]
        tokens = [int(t) for t in re.findall(r'\b\d{1,2}\b', window)]

        # sliding selection: first 5 mains (1-50, distinct), then next 2 stars (1-12, distinct)
        selected_numbers = None
        selected_stars = None
        for i in range(0, max(0, len(tokens) - 7)):
            mains = []
            j = i
            while j < len(tokens) and len(mains) < 5:
                v = tokens[j]
                if 1 <= v <= 50 and v not in mains:
                    mains.append(v)
                j += 1
            if len(mains) < 5:
                continue
            stars_c = []
            while j < len(tokens) and len(stars_c) < 2:
                v = tokens[j]
                if 1 <= v <= 12 and v not in stars_c:
                    stars_c.append(v)
                j += 1
            if len(stars_c) == 2:
                selected_numbers = mains
                selected_stars = stars_c
                break

        if selected_numbers and selected_stars:
            numbers = selected_numbers
            stars = selected_stars

    # Validate ranges
    if len(numbers) != 5 or len(stars) != 2:
        return None
    if not all(1 <= n <= 50 for n in numbers) or not all(1 <= s <= 12 for s in stars):
        return None

    return {
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "stars": sorted(stars),
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

        return jsonify({"status": "ok", "upserted": draw.get("draw_date"), "parsed": draw})
    except Exception as e:
        return jsonify({"error": "Sync failed", "detail": str(e), "trace": traceback.format_exc()}), 500
