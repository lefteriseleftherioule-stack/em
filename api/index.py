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
from urllib.parse import urlparse, urljoin
import json

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
        balls_container = latest_result_container.find(lambda t: t.name in ['div', 'ul', 'ol'] and (
            (t.get('class') and any(re.search(r'\bballs?\b', c, re.I) for c in t.get('class'))) or
            ('balls' in (t.get('id') or ''))
        ))

    # Main numbers
    if balls_container:
        # Parse from <li> items (common on euro-millions.com)
        ordered_li_digits = []
        for li in balls_container.find_all('li'):
            classes = li.get('class') or []
            is_star = any(re.search(r'(lucky|star)', cls, re.I) for cls in classes)
            text = li.get_text(strip=True)
            m = re.search(r'\b(\d{1,2})\b', text)
            if not m:
                continue
            v = int(m.group(1))
            ordered_li_digits.append(v)
            if is_star:
                if 1 <= v <= 12 and v not in stars:
                    stars.append(v)
            else:
                if 1 <= v <= 50 and v not in numbers:
                    numbers.append(v)
        # If we got mains but no stars, infer stars from the last two li digits within 1-12
        if len(numbers) >= 5 and len(stars) < 2 and len(ordered_li_digits) >= 7:
            candidates_stars = [d for d in ordered_li_digits[-4:] if 1 <= d <= 12]
            if len(candidates_stars) >= 2:
                stars = candidates_stars[-2:]

        # Fallback: spans within balls container
        for ball_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'\bball\b', c, re.I)):
            text = ball_span.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', text):
                try:
                    n = int(text)
                    if 1 <= n <= 50:
                        numbers.append(n)
                except Exception:
                    pass

        # Lucky stars from spans
        for star_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'(lucky\s*star|star)', c, re.I)):
            text = star_span.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', text):
                try:
                    s = int(text)
                    if 1 <= s <= 12:
                        stars.append(s)
                except Exception:
                    pass

    # If we still don't have enough, prefer a clear mains list and take stars from an adjacent stars list
    if len(numbers) < 5 or len(stars) < 2:
        mains_list = None
        stars_list = None
        # Select mains list: class names like balls/main/winning with at least 5 valid numbers
        candidate_mains = []
        for lst in latest_result_container.find_all(['ul', 'ol']):
            lst_classes = " ".join(lst.get('class') or [])
            hint_main = re.search(r'(balls|main|winning)', lst_classes, re.I)
            vals = []
            for node in lst.find_all(['li', 'span']):
                t = node.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', t):
                    v = int(t)
                    if 1 <= v <= 50:
                        vals.append(v)
            if len(vals) >= 5 and (hint_main or len(vals) == 5):
                candidate_mains.append((lst, vals))
        if candidate_mains:
            mains_list, mains_vals = candidate_mains[0]
            if len(numbers) < 5:
                numbers = mains_vals[:5]
        # Prefer a distinct stars list among siblings of mains_list
        if mains_list and len(stars) < 2:
            parent = mains_list.parent
            sibling_lists = parent.find_all(['ul', 'ol'], recursive=False) if parent else []
            for lst in sibling_lists:
                if lst is mains_list:
                    continue
                lst_classes = " ".join(lst.get('class') or [])
                svals = []
                for node in lst.find_all(['li', 'span']):
                    t = node.get_text(strip=True)
                    if re.fullmatch(r'\d{1,2}', t):
                        v = int(t)
                        if 1 <= v <= 12:
                            svals.append(v)
                # Stars list should have exactly two star digits
                if (re.search(r'(lucky|stars)', lst_classes, re.I) and len(svals) >= 2) or len(svals) == 2:
                    stars_list = lst
                    stars = svals[:2]
                    break
        # As a last resort, look for a combined list of 7 digits and take last two <=12
        if len(stars) < 2:
            for lst in latest_result_container.find_all(['ul', 'ol']):
                vals = []
                for node in lst.find_all(['li', 'span']):
                    t = node.get_text(strip=True)
                    if re.fullmatch(r'\d{1,2}', t):
                        vals.append(int(t))
                if len(vals) >= 7:
                    cstars = [d for d in vals[-4:] if 1 <= d <= 12]
                    if len(cstars) >= 2:
                        stars = cstars[-2:]
                        break

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

def parse_draw_for_date(html_content, target_date_str):
    """
    Parse a specific EuroMillions draw for the given ISO date (YYYY-MM-DD)
    from a results page that contains multiple draws.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    try:
        dt = datetime.strptime(target_date_str, '%Y-%m-%d')
    except Exception:
        return None

    # Try extracting structured data from JSON scripts for the specific date
    def _extract_structured_for_date(soup, target_date_str):
        def walk(obj):
            results = []
            if isinstance(obj, dict):
                d = None
                for dk in ['date', 'drawDate', 'draw_date']:
                    val = obj.get(dk)
                    if isinstance(val, str):
                        try:
                            d = datetime.strptime(val[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
                        except Exception:
                            pass
                nums = None
                sts = None
                for nk in ['numbers', 'mainNumbers', 'main_numbers']:
                    if nk in obj and isinstance(obj[nk], list):
                        vals = []
                        for x in obj[nk]:
                            sx = str(x)
                            if re.fullmatch(r'\d{1,2}', sx):
                                iv = int(sx)
                                if 1 <= iv <= 50:
                                    vals.append(iv)
                        if len(vals) >= 5:
                            nums = vals[:5]
                for sk in ['luckyStars', 'stars', 'lucky_numbers', 'luckyStars']:
                    if sk in obj and isinstance(obj[sk], list):
                        vals = []
                        for x in obj[sk]:
                            sx = str(x)
                            if re.fullmatch(r'\d{1,2}', sx):
                                iv = int(sx)
                                if 1 <= iv <= 12:
                                    vals.append(iv)
                        if len(vals) >= 2:
                            sts = vals[:2]
                if nums and sts:
                    results.append({'date': d, 'numbers': nums, 'stars': sts})
                for v in obj.values():
                    results.extend(walk(v))
            elif isinstance(obj, list):
                for it in obj:
                    results.extend(walk(it))
            return results

        for script in soup.find_all('script'):
            ttype = (script.get('type') or '').lower()
            if 'json' in ttype or ttype == '':
                text = script.string or script.get_text() or ''
                if not text.strip():
                    continue
                try:
                    obj = json.loads(text)
                    matches = walk(obj)
                    for m in matches:
                        if m.get('date') == target_date_str:
                            return sorted(m['numbers']), sorted(m['stars'])
                except Exception:
                    # Regex fallback inside JSON-like text
                    pattern = re.compile(rf'"(?:date|drawDate|draw_date)"\s*:\s*"{re.escape(target_date_str)}".*?"(?:numbers|mainNumbers|main_numbers)"\s*:\s*\[(.*?)\].*?"(?:luckyStars|stars|lucky_numbers|luckyStars)"\s*:\s*\[(.*?)\]', re.S)
                    m = pattern.search(text)
                    if m:
                        nums = [int(x) for x in re.findall(r'\d{1,2}', m.group(1)) if 1 <= int(x) <= 50]
                        sts = [int(x) for x in re.findall(r'\d{1,2}', m.group(2)) if 1 <= int(x) <= 12]
                        if len(nums) >= 5 and len(sts) >= 2:
                            return sorted(nums[:5]), sorted(sts[:2])
        return None, None

    jnums, jstars = _extract_structured_for_date(soup, target_date_str)
    # initialize defaults early; structured values will short-circuit later branches
    numbers = []
    stars = []
    if jnums and jstars:
        numbers = jnums
        stars = jstars

    weekday = dt.strftime('%A')  # e.g., Tuesday
    day_no = dt.day               # e.g., 4
    day_no_z = f"{day_no:02d}"   # e.g., 04
    month_name = dt.strftime('%B')  # e.g., November
    year = dt.strftime('%Y')

    # Build regexes to find the date heading/content (English + Spanish + dd/mm/yyyy)
    es_days = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
        'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
    }
    es_months = {
        'January': 'enero', 'February': 'febrero', 'March': 'marzo', 'April': 'abril',
        'May': 'mayo', 'June': 'junio', 'July': 'julio', 'August': 'agosto',
        'September': 'septiembre', 'October': 'octubre', 'November': 'noviembre', 'December': 'diciembre'
    }
    weekday_es = es_days.get(weekday, weekday)
    month_es = es_months.get(month_name, month_name)
    patterns = [
        # English with weekday, with/without comma
        rf"{weekday},\s+{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{weekday}\s+{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{weekday},\s+{day_no_z}\s+{month_name}\s+{year}",
        rf"{weekday}\s+{day_no_z}\s+{month_name}\s+{year}",
        # English without weekday
        rf"{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{day_no_z}\s+{month_name}\s+{year}",
        rf"{day_no}\s+{month_name}\s+{year}",
        # Spanish variants
        rf"{weekday_es}\s+{day_no}(?:\s+de)?\s+{month_es}\s+de\s+{year}",
        rf"{day_no}(?:\s+de)?\s+{month_es}\s+de\s+{year}",
        # Numeric day/month/year (2 or 4-digit year)
        rf"{day_no_z}\/{dt.strftime('%m')}\/{year}",
        rf"{dt.strftime('%d')}\/{dt.strftime('%m')}\/{dt.strftime('%y')}",
        rf"{day_no}\/{dt.strftime('%m')}\/{year}",
    ]

    # First, look for a <time datetime="YYYY-MM-DD"> element which often denotes the draw
    time_tag = soup.find('time', attrs={'datetime': target_date_str})
    # Search headings next
    date_heading = None
    for h in soup.find_all(['h1', 'h2', 'h3']):
        text = h.get_text(strip=True)
        if any(re.search(p, text, re.I) for p in patterns):
            date_heading = h
            break

    # If heading not found, search any text node containing the date
    matched_node = None
    if not date_heading:
        for text_node in soup.find_all(string=True):
            txt = (text_node or '').strip()
            if not txt:
                continue
            if any(re.search(p, txt, re.I) for p in patterns):
                matched_node = text_node
                break

    # Select a container near the heading; otherwise use whole document after the match
    latest_result_container = None
    if time_tag:
        latest_result_container = time_tag.find_parent(lambda t: t.name in ['article', 'section', 'div']) or time_tag.parent
    if date_heading and not latest_result_container:
        latest_result_container = date_heading.find_next(lambda t: t.name in ['section', 'article', 'div'] and t.get_text(strip=True))
        if not latest_result_container:
            latest_result_container = date_heading.parent
    elif matched_node:
        # Use the matched text node's parent as the container
        try:
            latest_result_container = matched_node.parent
        except Exception:
            latest_result_container = None

    # If we still don't have a container, we'll work with text windows after the first match
    draw_date = dt.strftime('%Y-%m-%d')

    def extract_from_container(container):
        local_numbers = []
        local_stars = []
        if not container:
            return local_numbers, local_stars
        # Prefer explicit balls/lucky stars markup
        balls_container = container.find(lambda t: t.name in ['div', 'ul', 'ol'] and (
            (t.get('class') and any(re.search(r'\bballs?\b', c, re.I) for c in t.get('class'))) or
            ('balls' in (t.get('id') or ''))
        ))
        if balls_container:
            # Read from <li> items first
            ordered_li_digits = []
            for li in balls_container.find_all('li'):
                classes = li.get('class') or []
                is_star = any(re.search(r'(lucky|star)', cls, re.I) for cls in classes)
                t = li.get_text(strip=True)
                m = re.search(r'\b(\d{1,2})\b', t)
                if not m:
                    continue
                v = int(m.group(1))
                ordered_li_digits.append(v)
                if is_star:
                    if 1 <= v <= 12 and v not in local_stars:
                        local_stars.append(v)
                else:
                    if 1 <= v <= 50 and v not in local_numbers:
                        local_numbers.append(v)
            # If we have enough mains but no stars, infer stars from last two li digits (<=12)
            if len(local_numbers) >= 5 and len(local_stars) < 2 and len(ordered_li_digits) >= 7:
                cstars = [d for d in ordered_li_digits[-4:] if 1 <= d <= 12]
                if len(cstars) >= 2:
                    local_stars = cstars[-2:]
            # Fallback to spans
            for ball_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'\bball\b', c, re.I)):
                text = ball_span.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', text):
                    n = int(text)
                    if 1 <= n <= 50 and n not in local_numbers:
                        local_numbers.append(n)
            for star_span in balls_container.find_all('span', class_=lambda c: isinstance(c, str) and re.search(r'(lucky\s*star|star)', c, re.I)):
                text = star_span.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', text):
                    s = int(text)
                    if 1 <= s <= 12 and s not in local_stars:
                        local_stars.append(s)
        # Prefer a clear mains list and adjacent stars list
        if (len(local_numbers) < 5 or len(local_stars) < 2) and container:
            mains_list = None
            stars_list = None
            candidate_mains = []
            for lst in container.find_all(['ul', 'ol']):
                lst_classes = " ".join(lst.get('class') or [])
                hint_main = re.search(r'(balls|main|winning)', lst_classes, re.I)
                vals = []
                for node in lst.find_all(['li', 'span']):
                    t = node.get_text(strip=True)
                    if re.fullmatch(r'\d{1,2}', t):
                        v = int(t)
                        if 1 <= v <= 50:
                            vals.append(v)
                if len(vals) >= 5 and (hint_main or len(vals) == 5):
                    candidate_mains.append((lst, vals))
            if candidate_mains:
                mains_list, mains_vals = candidate_mains[0]
                if len(local_numbers) < 5:
                    local_numbers = mains_vals[:5]
            # Prefer stars list among siblings of mains_list
            if mains_list and len(local_stars) < 2:
                parent = mains_list.parent
                sibling_lists = parent.find_all(['ul', 'ol'], recursive=False) if parent else []
                for lst in sibling_lists:
                    if lst is mains_list:
                        continue
                    lst_classes = " ".join(lst.get('class') or [])
                    svals = []
                    for node in lst.find_all(['li', 'span']):
                        t = node.get_text(strip=True)
                        if re.fullmatch(r'\d{1,2}', t):
                            v = int(t)
                            if 1 <= v <= 12:
                                svals.append(v)
                    if (re.search(r'(lucky|stars)', lst_classes, re.I) and len(svals) >= 2) or len(svals) == 2:
                        stars_list = lst
                        local_stars = svals[:2]
                        break
            # Combined-list fallback
            if len(local_stars) < 2:
                for lst in container.find_all(['ul', 'ol']):
                    vals = []
                    for node in lst.find_all(['li', 'span']):
                        t = node.get_text(strip=True)
                        if re.fullmatch(r'\d{1,2}', t):
                            vals.append(int(t))
                    if len(vals) >= 7:
                        cstars = [d for d in vals[-4:] if 1 <= d <= 12]
                        if len(cstars) >= 2:
                            local_stars = cstars[-2:]
                            break
        # If not enough, scan generic spans and list items within container
        if len(local_numbers) < 5:
            # scan common inline digit carriers
            for sp in container.find_all(['span', 'li', 'div']):
                t = sp.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', t):
                    v = int(t)
                    if 1 <= v <= 50 and v not in local_numbers:
                        local_numbers.append(v)
                if len(local_numbers) >= 5:
                    break
        if len(local_numbers) < 5:
            # scan nearby lists for numbers (ul/ol appearing close to the date container)
            for lst in container.find_all(['ul', 'ol'], limit=3):
                for li in lst.find_all('li'):
                    t = li.get_text(strip=True)
                    if re.fullmatch(r'\d{1,2}', t):
                        v = int(t)
                        if 1 <= v <= 50 and v not in local_numbers:
                            local_numbers.append(v)
                        if len(local_numbers) >= 5:
                            break
                if len(local_numbers) >= 5:
                    break
        if len(local_stars) < 2:
            star_label = container.find(string=re.compile(r'(Lucky\s*Stars?|Estrellas?)', re.I))
            if star_label:
                parent = star_label.parent if hasattr(star_label, 'parent') else container
                for sp in parent.find_all_next('span', limit=6):
                    t = sp.get_text(strip=True)
                    if re.fullmatch(r'\d{1,2}', t):
                        v = int(t)
                        if 1 <= v <= 12 and v not in local_stars:
                            local_stars.append(v)
                    if len(local_stars) >= 2:
                        break
        return local_numbers, local_stars

    n1, s1 = extract_from_container(latest_result_container)
    numbers.extend(n1)
    stars.extend(s1)

    # If container strategy failed, use text window after the matched date text
    if len(numbers) != 5 or len(stars) != 2:
        full_text = soup.get_text(" ", strip=True)
        match_idx = None
        for p in patterns:
            m = re.search(p, full_text, re.I)
            if m:
                match_idx = m.end()
                break
        if match_idx is None:
            return None
        # Limit the token window to before the next date occurrence to avoid mixing draws
        any_date_re = re.compile(
            r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo)[^\d]{0,12}\d{1,2}[^\n\r]{0,20}(?:January|February|March|April|May|June|July|August|September|October|November|December|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)[^\n\r]{0,15}\d{4}|\b\d{1,2}\/\d{2}\/\d{4}\b)",
            re.I
        )
        tail_text = full_text[match_idx:]
        next_m = any_date_re.search(tail_text)
        end_idx = match_idx + (next_m.start() if next_m else len(full_text))
        window = full_text[match_idx:end_idx]
        tokens = [int(t) for t in re.findall(r'\b\d{1,2}\b', window)]
        # sliding selection: first 5 mains then next 2 stars
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
                numbers = mains
                stars = stars_c
                break

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

def parse_draw_detail_page(html_content, target_date_str):
    """
    Parse a single-draw detail page where only one EuroMillions draw is present.
    Tries explicit markup first, then falls back to text token scanning.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    numbers = []
    stars = []

    # Try extracting structured data from JSON scripts first
    def _extract_structured_result_from_scripts(soup, target_date_str=None):
        def walk(obj):
            found = []
            if isinstance(obj, dict):
                d = None
                for dk in ['date', 'drawDate', 'draw_date']:
                    val = obj.get(dk)
                    if isinstance(val, str):
                        try:
                            d = datetime.strptime(val[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
                        except Exception:
                            pass
                nums = None
                sts = None
                for nk in ['numbers', 'mainNumbers', 'main_numbers']:
                    if nk in obj and isinstance(obj[nk], list):
                        vals = []
                        for x in obj[nk]:
                            sx = str(x)
                            if re.fullmatch(r'\d{1,2}', sx):
                                iv = int(sx)
                                if 1 <= iv <= 50:
                                    vals.append(iv)
                        if len(vals) >= 5:
                            nums = vals[:5]
                for sk in ['luckyStars', 'stars', 'lucky_numbers', 'luckyStars']:
                    if sk in obj and isinstance(obj[sk], list):
                        vals = []
                        for x in obj[sk]:
                            sx = str(x)
                            if re.fullmatch(r'\d{1,2}', sx):
                                iv = int(sx)
                                if 1 <= iv <= 12:
                                    vals.append(iv)
                        if len(vals) >= 2:
                            sts = vals[:2]
                if nums and sts:
                    found.append({'date': d, 'numbers': nums, 'stars': sts})
                for v in obj.values():
                    found.extend(walk(v))
            elif isinstance(obj, list):
                for it in obj:
                    found.extend(walk(it))
            return found

        for script in soup.find_all('script'):
            ttype = (script.get('type') or '').lower()
            if 'json' in ttype or ttype == '':
                text = script.string or script.get_text() or ''
                if not text.strip():
                    continue
                try:
                    obj = json.loads(text)
                    matches = walk(obj)
                    if target_date_str:
                        for m in matches:
                            if m.get('date') == target_date_str:
                                return sorted(m['numbers']), sorted(m['stars'])
                    if matches:
                        m = matches[0]
                        return sorted(m['numbers']), sorted(m['stars'])
                except Exception:
                    # Regex fallback inside JSON-like text
                    m_nums = re.search(r'"(?:numbers|mainNumbers|main_numbers)"\s*:\s*\[(.*?)\]', text, re.S)
                    m_stars = re.search(r'"(?:luckyStars|stars|lucky_numbers|luckyStars)"\s*:\s*\[(.*?)\]', text, re.S)
                    if m_nums and m_stars:
                        nums = [int(x) for x in re.findall(r'\d{1,2}', m_nums.group(1)) if 1 <= int(x) <= 50]
                        sts = [int(x) for x in re.findall(r'\d{1,2}', m_stars.group(1)) if 1 <= int(x) <= 12]
                        if len(nums) >= 5 and len(sts) >= 2:
                            return sorted(nums[:5]), sorted(sts[:2])
        return None, None

    jnums, jstars = _extract_structured_result_from_scripts(soup, target_date_str)
    if jnums and jstars:
        numbers = jnums
        stars = jstars

    # Prefer explicit containers commonly used on detail pages
    container = None
    # Anchor around the date if available
    time_tag = soup.find('time', attrs={'datetime': target_date_str})
    if time_tag:
        container = time_tag.find_parent(lambda t: t.name in ['article', 'section', 'div']) or time_tag.parent
    if not container:
        date_h = soup.find(['h1','h2'], string=re.compile(r'EuroMillions\s+Results', re.I))
        if date_h:
            container = date_h.find_parent(lambda t: t.name in ['article','section','div']) or date_h.parent
    candidates = [
        {'name': 'div', 'class': re.compile(r'(balls|winning|numbers|result|draw-results|primary|secondary)', re.I)},
        {'name': 'section', 'class': re.compile(r'(result|numbers|euromillions)', re.I)},
        {'name': 'article', 'class': re.compile(r'(result|euromillions)', re.I)},
    ]
    for c in candidates:
        found = soup.find(c['name'], class_=c['class'])
        if found:
            container = found
            break
    if not container:
        container = soup

    # Try explicit spans first: main balls vs lucky star spans
    # This closely matches euro-millions.com detail pages
    mains_spans = container.find_all('span', class_=lambda c: isinstance(c, str) and ('ball' in c.lower()) and ('star' not in c.lower()) and ('lucky' not in c.lower())) if container else []
    for sp in mains_spans:
        t = sp.get_text(strip=True)
        if re.fullmatch(r'\d{1,2}', t):
            v = int(t)
            if 1 <= v <= 50 and v not in numbers:
                numbers.append(v)
        if len(numbers) >= 5:
            break
    if len(numbers) < 5:
        stars_spans = container.find_all('span', class_=lambda c: isinstance(c, str) and (('lucky' in c.lower()) or ('star' in c.lower()))) if container else []
        for sp in stars_spans:
            t = sp.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', t):
                v = int(t)
                if 1 <= v <= 12 and v not in stars:
                    stars.append(v)
            if len(stars) >= 2:
                break

    # Direct list extraction (ul/ol) specifically targeting balls vs stars lists
    if len(numbers) < 5 or len(stars) < 2:
        # Prefer a distinct mains list
        mains_list = None
        stars_list = None
        mains_list = container.find(['ul','ol'], class_=re.compile(r'(balls|main|winning)', re.I)) if container else None
        # Lucky stars lists often have classes containing 'lucky' or 'stars'
        stars_list = container.find(['ul','ol'], class_=re.compile(r'(lucky|stars)', re.I)) if container else None
        if mains_list and len(numbers) < 5:
            vals = []
            for li in mains_list.find_all('li'):
                t = li.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', t):
                    v = int(t)
                    if 1 <= v <= 50:
                        vals.append(v)
            if len(vals) >= 5:
                numbers = vals[:5]
        if stars_list and len(stars) < 2:
            svals = []
            for li in stars_list.find_all('li'):
                t = li.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', t):
                    v = int(t)
                    if 1 <= v <= 12:
                        svals.append(v)
            if len(svals) >= 2:
                stars = svals[:2]

    # Extract using clusters to avoid picking prize table numbers
    def extract_cluster(parent):
        mains = []
        lucky = []
        if not parent:
            return mains, lucky
        # Prefer lists of balls
        lists = []
        lists += parent.find_all('ul', class_=re.compile(r'(balls|numbers|main|winning)', re.I))
        lists += parent.find_all('ol', class_=re.compile(r'(balls|numbers|main|winning)', re.I))
        for lst in lists:
            vals = []
            for li in lst.find_all('li'):
                t = li.get_text(strip=True)
                if re.fullmatch(r'\d{1,2}', t):
                    vals.append(int(t))
            if len(vals) >= 5 and all(1 <= v <= 50 for v in vals[:5]):
                mains = vals[:5]
                # attempt to find lucky stars adjacent
                next_sibling = lst.find_next(string=re.compile(r'(Lucky\s*Stars?|Estrellas?)', re.I))
                if next_sibling:
                    stars_parent = next_sibling.parent if hasattr(next_sibling, 'parent') else parent
                    stars_vals = []
                    for sp in stars_parent.find_all_next(['li','span'], limit=6):
                        tt = sp.get_text(strip=True)
                        if re.fullmatch(r'\d{1,2}', tt):
                            vv = int(tt)
                            if 1 <= vv <= 12:
                                stars_vals.append(vv)
                            if len(stars_vals) >= 2:
                                break
                    if len(stars_vals) >= 2:
                        lucky = stars_vals[:2]
                if len(mains) == 5 and len(lucky) == 2:
                    return mains, lucky
        # Fallback: find any cluster of 5 numbers in same parent container
        by_parent = {}
        for el in parent.find_all(['span','li','div']):
            t = el.get_text(strip=True)
            if re.fullmatch(r'\d{1,2}', t):
                v = int(t)
                par = el.parent
                by_parent.setdefault(par, []).append(v)
        for par, vals in by_parent.items():
            mains_c = [v for v in vals if 1 <= v <= 50]
            stars_c = [v for v in vals if 1 <= v <= 12]
            if len(mains_c) >= 5:
                mains = mains_c[:5]
                if len(stars_c) >= 2:
                    lucky = stars_c[:2]
                if len(mains) == 5 and len(lucky) == 2:
                    return mains, lucky
        return mains, lucky

    if len(numbers) < 5 or len(stars) < 2:
        m1, s1 = extract_cluster(container)
        if len(numbers) < 5:
            numbers = m1
        if len(stars) < 2:
            stars = s1

    # Fallback: whole-document token scan with sliding window
    if len(numbers) < 5 or len(stars) < 2:
        tokens = [int(t) for t in re.findall(r'\b\d{1,2}\b', soup.get_text(" ", strip=True))]
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
                numbers = mains
                stars = stars_c
                break

    if len(numbers) != 5 or len(stars) != 2:
        return None

    # Date: trust the requested date; validate if a <time> exists
    draw_date = target_date_str
    time_tag = soup.find('time', attrs={'datetime': target_date_str})
    if time_tag is None:
        # try to confirm via text patterns, but don't block if not found
        pass

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

@app.route('/api/sync_date')
def sync_date():
    """Sync a specific draw date using the multi-draw results page."""
    try:
        from .db import ensure_schema, upsert_draw
        ensure_schema()

        target_date = request.args.get('date')
        if not target_date:
            return jsonify({"error": "Missing required query param 'date' (YYYY-MM-DD)"}), 400
        # Validate date format
        try:
            datetime.strptime(target_date, '%Y-%m-%d')
        except Exception:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        source_url = os.getenv("EURO_SOURCE_URL", "https://www.euro-millions.com/results")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
        }
        primary_fetch_error = None
        resp = None
        draw = None
        try:
            resp = requests.get(source_url, timeout=(5, 20), headers=headers)
            resp.raise_for_status()
            draw = parse_draw_for_date(resp.text, target_date)
        except Exception as e:
            # Don't fail hard here; proceed to fallbacks
            primary_fetch_error = str(e)

        if not draw:
            # Attempt per-draw detail page fallbacks based on the source host
            p = urlparse(source_url)
            base = f"{p.scheme}://{p.netloc}"
            date_dash = datetime.strptime(target_date, '%Y-%m-%d').strftime('%d-%m-%Y')
            year = datetime.strptime(target_date, '%Y-%m-%d').strftime('%Y')

            # Build fallbacks, always prioritizing euro-millions.com first
            bases = []
            euro_millions = f"{p.scheme}://www.euro-millions.com"
            euromillones = f"{p.scheme}://www.euromillones.com"
            # Preferred order
            bases.append(euro_millions)
            bases.append(euromillones)
            # Include the original base to cover other variants
            if base not in bases:
                bases.insert(0, base)
            # Deduplicate while preserving order
            seen = set()
            bases = [b for b in bases if not (b in seen or seen.add(b))]

            candidates = []
            for b in bases:
                # Detail pages
                candidates.append(urljoin(b, f"/en/results/euromillions/{target_date}"))
                candidates.append(urljoin(b, f"/en/results/euromillions/{date_dash}"))
                candidates.append(urljoin(b, f"/results/euromillions/{target_date}"))
                candidates.append(urljoin(b, f"/results/euromillions/{date_dash}"))
                # euro-millions.com uses /results/<dd-mm-yyyy>
                candidates.append(urljoin(b, f"/results/{target_date}"))
                candidates.append(urljoin(b, f"/results/{date_dash}"))
                # amp pages (simpler markup)
                candidates.append(urljoin(b, f"/amp/results/{target_date}"))
                candidates.append(urljoin(b, f"/amp/results/{date_dash}"))
                # Year archive page on euro-millions.com
                candidates.append(urljoin(b, f"/results-history-{year}"))

            tried = []
            archive_text = None
            for url in candidates:
                try:
                    r2 = requests.get(url, timeout=(5, 20), headers=headers)
                    tried.append({"url": url, "status": r2.status_code, "length": len(r2.text)})
                    if r2.status_code == 200:
                        if f"/results-history-{year}" in url:
                            # Multi-draw archive page: try date-scoped parser
                            archive_text = r2.text
                            d2 = parse_draw_for_date(r2.text, target_date)
                        else:
                            d2 = parse_draw_detail_page(r2.text, target_date)
                        if d2:
                            draw = d2
                            break
                except Exception as e:
                    tried.append({"url": url, "status": "error", "error": str(e)})

            if not draw:
                # Enhanced debugging information
                time_tags = re.findall(r'<time[^>]*datetime="(.*?)"', resp.text[:50000], flags=re.I)
                return jsonify({
                    "error": "Could not parse target draw from page",
                    "date": target_date,
                    "url": source_url,
                    "html_preview": resp.text[:800] + "..." if len(resp.text) > 800 else resp.text,
                    "html_length": len(resp.text),
                    "time_tags_found": time_tags[:10],
                    "fallback_attempts": tried,
                    "archive_hint": True,
                    "primary_fetch_error": primary_fetch_error
                }), 422

        ok = upsert_draw(draw)
        if not ok:
            return jsonify({"error": "Failed to persist draw"}), 500

        return jsonify({"status": "ok", "upserted": draw.get("draw_date"), "parsed": draw})
    except Exception as e:
        return jsonify({"error": "Sync date failed", "detail": str(e), "trace": traceback.format_exc()}), 500
