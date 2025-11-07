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
    
    # Find the date - it's now in a different format like "Tuesday, 04 November 2025"
    # Look for text that matches this pattern
    date_pattern = r'(\w+),\s+(\d{2})\s+(\w+)\s+(\d{4})'
    date_match = re.search(date_pattern, html_content)
    if not date_match:
        return None
    
    day = date_match.group(2)
    month_name = date_match.group(3)
    year = date_match.group(4)
    
    # Convert month name to number
    month_map = {
        'January': '01', 'February': '02', 'March': '03', 'April': '04',
        'May': '05', 'June': '06', 'July': '07', 'August': '08',
        'September': '09', 'October': '10', 'November': '11', 'December': '12'
    }
    month = month_map.get(month_name, '01')
    draw_date = f"{year}-{month}-{day}"

    # Find the numbers - they're now concatenated in text like "6925284514"
    # This should be 5 numbers (6,9,25,28,45) and 2 stars (1,4)
    # Looking at the HTML, the numbers appear to be in the main content area
    
    numbers = None
    stars = None
    
    # First, try to find the concatenated number pattern
    concatenated_pattern = r'(\d{7,12})'
    concat_match = re.search(concatenated_pattern, html_content)
    
    if concat_match:
        concat_str = concat_match.group(1)
        # Try to split this concatenated string intelligently
        # For "6925284514" we want [6,9,25,28,45] and stars [1,4]
        
        def split_concatenated_numbers(s):
            # Try different splitting strategies for EuroMillions numbers
            numbers = []
            stars = []
            
            # Strategy: try to split by looking for valid number ranges
            # EuroMillions main numbers: 1-50, stars: 1-12
            
            # Try splitting at different positions
            possible_splits = []
            
            # Try splitting as single digits first
            if len(s) >= 7:
                single_digit_split = [int(s[i]) for i in range(len(s))]
                # Check if we have exactly 7 numbers (5 main + 2 stars)
                if len(single_digit_split) == 7:
                    main_nums = single_digit_split[:5]
                    star_nums = single_digit_split[5:]
                    if all(1 <= n <= 50 for n in main_nums) and all(1 <= n <= 12 for n in star_nums):
                        return main_nums, star_nums
            
            # Try splitting with some 2-digit numbers
            # This is more complex - let's try a few common patterns
            
            # Look for the pattern in the specific HTML section
            # The numbers might be in a specific div or section
            main_content = re.search(r'Latest Result.*?((?:\d+\s*)+)', html_content, re.DOTALL)
            if main_content:
                numbers_text = main_content.group(1)
                all_nums_in_section = re.findall(r'\d+', numbers_text)
                
                # Filter for valid EuroMillions numbers
                valid_main = []
                valid_stars = []
                
                for num_str in all_nums_in_section:
                    num = int(num_str)
                    if 1 <= num <= 50 and len(valid_main) < 5:
                        valid_main.append(num)
                    elif 1 <= num <= 12 and len(valid_stars) < 2:
                        valid_stars.append(num)
                
                if len(valid_main) == 5 and len(valid_stars) == 2:
                    return valid_main, valid_stars
            
            return None, None
        
        numbers, stars = split_concatenated_numbers(concat_str)
        if numbers and stars:
            return {
                "draw_date": draw_date,
                "numbers": numbers,
                "stars": stars,
                "jackpot": None,
                "winners": None
            }
    
    # Fallback: find all numbers in the HTML content
    all_numbers = re.findall(r'\b\d+\b', html_content)
    
    # Filter for valid EuroMillions numbers
    # Main numbers: 1-50, Stars: 1-12
    valid_main_numbers = []
    valid_stars = []
    
    for num_str in all_numbers:
        num = int(num_str)
        if 1 <= num <= 50:
            valid_main_numbers.append(num)
        elif 1 <= num <= 12:
            valid_stars.append(num)
    
    # We need exactly 5 main numbers and 2 stars
    if len(valid_main_numbers) >= 5 and len(valid_stars) >= 2:
        numbers = valid_main_numbers[:5]
        stars = valid_stars[:2]
    else:
        # If we don't have enough valid numbers, try a more aggressive approach
        # Look for the specific pattern that might contain the draw results
        # Sometimes numbers are embedded in longer strings
        all_digits = re.findall(r'\d', html_content)
        if len(all_digits) >= 7:  # At least 5 numbers + 2 stars
            # Try to extract from the digit sequence
            potential_numbers = [int(d) for d in all_digits]
            # Filter for valid ranges
            main_from_digits = [n for n in potential_numbers if 1 <= n <= 50][:5]
            stars_from_digits = [n for n in potential_numbers if 1 <= n <= 12][:2]
            
            if len(main_from_digits) == 5 and len(stars_from_digits) == 2:
                numbers = main_from_digits
                stars = stars_from_digits
            else:
                # Last resort: return None if we can't get valid numbers
                return None
        else:
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
