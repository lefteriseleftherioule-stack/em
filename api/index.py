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

    # Find the numbers - they're now in a different format
    # Let's look for numbers more intelligently by searching for specific patterns
    
    # Look for numbers in the main content area
    # Try to find a section that contains the draw results
    
    # Look for patterns that might contain the numbers
    # EuroMillions has 5 main numbers (1-50) and 2 stars (1-12)
    
    # Try to find numbers in various formats
    numbers = None
    stars = None
    
    # Strategy 1: Look for numbers in the format of actual EuroMillions results
    # Search for patterns like "6, 9, 25, 28, 45" and "1, 4" for stars
    
    # Look for number sequences that could be EuroMillions numbers
    number_patterns = [
        r'(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})',  # 5 numbers
        r'(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})',  # 5 numbers separated by spaces
    ]
    
    star_patterns = [
        r'Stars?\s*:?\s*(\d{1,2})\s*,\s*(\d{1,2})',  # Stars: 1, 4
        r'(\d{1,2})\s*,\s*(\d{1,2})\s*Stars?',  # 1, 4 Stars
        r'(\d{1,2})\s+(\d{1,2})\s*Stars?',  # 1 4 Stars
    ]
    
    # Try to find main numbers
    for pattern in number_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            potential_numbers = [int(match.group(i)) for i in range(1, 6)]
            # Validate EuroMillions rules
            if all(1 <= n <= 50 for n in potential_numbers):
                numbers = potential_numbers
                break
    
    # Try to find stars
    for pattern in star_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            potential_stars = [int(match.group(1)), int(match.group(2))]
            # Validate EuroMillions star rules
            if all(1 <= s <= 12 for s in potential_stars):
                stars = potential_stars
                break
    
    # Strategy 2: If we didn't find structured numbers, look for all numbers in a specific section
    if not numbers or not stars:
        # Look for the main content area that might contain the numbers
        # Try to find a section with "Latest Result" or similar
        
        # Find all numbers in the HTML
        all_numbers = re.findall(r'\b([1-9]|[1-4]\d|50)\b', html_content)  # 1-50
        all_stars = re.findall(r'\b([1-9]|1[0-2])\b', html_content)  # 1-12
        
        # Convert to integers and remove duplicates while preserving order
        seen_numbers = set()
        unique_numbers = []
        for num_str in all_numbers:
            num = int(num_str)
            if num not in seen_numbers:
                seen_numbers.add(num)
                unique_numbers.append(num)
        
        seen_stars = set()
        unique_stars = []
        for star_str in all_stars:
            star = int(star_str)
            if star not in seen_stars:
                seen_stars.add(star)
                unique_stars.append(star)
        
        # Take the first 5 numbers and 2 stars
        if len(unique_numbers) >= 5:
            numbers = unique_numbers[:5]
        if len(unique_stars) >= 2:
            stars = unique_stars[:2]
    
    # Strategy 3: Last resort - look for the concatenated pattern but split it properly
    if not numbers or not stars:
        # Look for long digit sequences that might be concatenated numbers
        long_digit_match = re.search(r'(\d{7,15})', html_content)
        if long_digit_match:
            digit_sequence = long_digit_match.group(1)
            
            # Try to split this intelligently
            # For a sequence like "6925284514", we want to find valid splits
            
            # Try different ways to split into valid EuroMillions numbers
            possible_splits = []
            
            # Try splitting as: single digits, then 2-digit numbers
            for split_point in range(1, len(digit_sequence)):
                try:
                    # Try different combinations
                    numbers_part = digit_sequence[:split_point]
                    stars_part = digit_sequence[split_point:]
                    
                    # Parse the numbers part
                    if len(numbers_part) >= 5:  # Need at least 5 numbers
                        # Try to extract 5 numbers from the sequence
                        main_nums = []
                        remaining = numbers_part
                        
                        # Try to extract 5 valid numbers (1-50)
                        for i in range(5):
                            if not remaining:
                                break
                            
                            # Try 2-digit first, then 1-digit
                            if len(remaining) >= 2:
                                two_digit = int(remaining[:2])
                                if 1 <= two_digit <= 50:
                                    main_nums.append(two_digit)
                                    remaining = remaining[2:]
                                else:
                                    # Try 1-digit
                                    one_digit = int(remaining[0])
                                    if 1 <= one_digit <= 50:
                                        main_nums.append(one_digit)
                                        remaining = remaining[1:]
                                    else:
                                        break
                            else:
                                # Only 1 digit left
                                one_digit = int(remaining[0])
                                if 1 <= one_digit <= 50:
                                    main_nums.append(one_digit)
                                    remaining = remaining[1:]
                                else:
                                    break
                        
                        # Parse stars part
                        star_nums = []
                        remaining_stars = stars_part
                        
                        for i in range(2):
                            if not remaining_stars:
                                break
                            
                            if len(remaining_stars) >= 2:
                                two_digit = int(remaining_stars[:2])
                                if 1 <= two_digit <= 12:
                                    star_nums.append(two_digit)
                                    remaining_stars = remaining_stars[2:]
                                else:
                                    one_digit = int(remaining_stars[0])
                                    if 1 <= one_digit <= 12:
                                        star_nums.append(one_digit)
                                        remaining_stars = remaining_stars[1:]
                                    else:
                                        break
                            else:
                                one_digit = int(remaining_stars[0])
                                if 1 <= one_digit <= 12:
                                    star_nums.append(one_digit)
                                    remaining_stars = remaining_stars[1:]
                                else:
                                    break
                        
                        if len(main_nums) == 5 and len(star_nums) == 2:
                            numbers = main_nums
                            stars = star_nums
                            break
                            
                except (ValueError, IndexError):
                    continue
    
    # Final validation
    if not numbers or not stars or len(numbers) != 5 or len(stars) != 2:
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
