from flask import Flask, jsonify, request
import os
import traceback
import requests
import re
from datetime import datetime

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import json

app = Flask(__name__)


# ============================================================
# CORS
# ============================================================

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ============================================================
# HOME
# ============================================================

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


# ============================================================
# HEALTH
# ============================================================

@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health():
    if request.method == 'OPTIONS':
        return ('', 200)

    try:
        import sys
        from .db import get_last_db_debug

        present_env = [
            k for k in ("DATABASE_URL",)
            if os.getenv(k)
        ]

        payload = {
            "status": "ok",
            "python_version": sys.version,
            "env_present": present_env,
        }
        if str(request.args.get('debug') or '').lower() in ('1', 'true', 'yes', 'on'):
            payload["db_debug"] = get_last_db_debug()
        return jsonify(payload)

    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================
# GET DRAWS
# ============================================================

@app.route('/api/draws', methods=['GET', 'OPTIONS'])
def get_draws():
    if request.method == 'OPTIONS':
        return ('', 200)

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

        draws = db_get_draws(
            limit=limit,
            year=year
        )

        if draws:
            normalized = []

            for d in draws:
                nd = dict(d)

                if isinstance(nd.get('draw_date'), datetime):
                    nd['draw_date'] = nd['draw_date'].strftime('%Y-%m-%d')

                elif (
                    nd.get('draw_date')
                    and hasattr(nd.get('draw_date'), 'isoformat')
                ):
                    nd['draw_date'] = nd['draw_date'].isoformat()

                normalized.append(nd)

            return jsonify({
                "data": normalized,
                "count": len(normalized)
            })

        return jsonify({
            "data": [],
            "count": 0
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to fetch draws",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# LATEST DRAW
# ============================================================

@app.route('/api/latest', methods=['GET', 'OPTIONS'])
def latest_draw():
    if request.method == 'OPTIONS':
        return ('', 200)

    try:
        from .db import get_latest_draw, get_last_db_debug

        row = get_latest_draw()

        if row:
            d = dict(row)

            if isinstance(d.get('draw_date'), datetime):
                d['draw_date'] = d['draw_date'].strftime('%Y-%m-%d')

            elif (
                d.get('draw_date')
                and hasattr(d.get('draw_date'), 'isoformat')
            ):
                d['draw_date'] = d['draw_date'].isoformat()

            return jsonify({
                "data": d
            })

        return jsonify({
            "error": "No draws available",
            "db_debug": get_last_db_debug()
        }), 404

    except Exception as e:
        return jsonify({
            "error": "Failed to get latest draw",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# PARSE LATEST DRAW
# SOURCE:
# https://www.euromillones.com/en/results/euromillions
# ============================================================

def parse_draw_from_page(html_content):

    soup = BeautifulSoup(
        html_content,
        'html.parser'
    )

    # --------------------------------------------------------
    # Strategy 1: Find explicit latest container
    # --------------------------------------------------------

    latest_result_container = soup.find(
        'div',
        class_='latest'
    )

    if not latest_result_container:
        latest_result_container = soup.find(
            class_=lambda x:
                isinstance(x, str)
                and (
                    'latest-result' in x.lower()
                    or 'latest' in x.lower()
                )
        )

    # --------------------------------------------------------
    # Strategy 2: Find EuroMillions Results heading
    # --------------------------------------------------------

    date_heading = None

    if not latest_result_container:

        headings = soup.find_all(
            ['h1', 'h2', 'h3'],
            string=re.compile(
                r'EuroMillions\s+Results',
                re.I
            )
        )

        for h in headings:

            candidate_container = h.find_next(
                lambda t:
                    t.name in [
                        'section',
                        'article',
                        'div'
                    ]
                    and t.get_text(strip=True)
            )

            if candidate_container:
                latest_result_container = candidate_container
                date_heading = h
                break

    # --------------------------------------------------------
    # Whole document fallback
    # --------------------------------------------------------

    if not latest_result_container:
        latest_result_container = soup

    # --------------------------------------------------------
    # Extract date
    # --------------------------------------------------------

    if not date_heading:

        date_heading = latest_result_container.find(
            ['h1', 'h2', 'h3']
        )

        if not date_heading:
            return None

    date_text = date_heading.get_text(
        strip=True
    )

    date_match = re.search(
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
        r'(\d{1,2})(?:st|nd|rd|th)?\s+'
        r'([A-Za-z]+)\s+'
        r'(\d{4})',
        date_text
    )

    if not date_match:

        date_match = re.search(
            r'(\d{1,2})(?:st|nd|rd|th)?\s+'
            r'([A-Za-z]+)\s+'
            r'(\d{4})',
            date_text
        )

    if not date_match:

        date_match = re.search(
            r'(\d{2})\/(\d{2})\/(\d{4})',
            date_text
        )

    if not date_match:

        full_text = soup.get_text(
            " ",
            strip=True
        )

        date_match = re.search(
            r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
            r'(\d{1,2})(?:st|nd|rd|th)?\s+'
            r'([A-Za-z]+)\s+'
            r'(\d{4})',
            full_text
        )

        if not date_match:

            date_match = re.search(
                r'(\d{1,2})(?:st|nd|rd|th)?\s+'
                r'([A-Za-z]+)\s+'
                r'(\d{4})',
                full_text
            )

        if not date_match:

            date_match = re.search(
                r'(\d{2})\/(\d{2})\/(\d{4})',
                full_text
            )

        if not date_match:
            return None

    # --------------------------------------------------------
    # Build ISO date
    # --------------------------------------------------------

    if '/' in date_match.group(0):

        day = date_match.group(1)
        month = date_match.group(2)
        year = date_match.group(3)

    else:

        day = date_match.group(1).zfill(2)
        month_name = date_match.group(2)
        year = date_match.group(3)

        month_map = {
            'January': '01',
            'February': '02',
            'March': '03',
            'April': '04',
            'May': '05',
            'June': '06',
            'July': '07',
            'August': '08',
            'September': '09',
            'October': '10',
            'November': '11',
            'December': '12'
        }

        month = month_map.get(
            str(month_name).capitalize(),
            '01'
        )

    draw_date = f"{year}-{month}-{day}"

    # --------------------------------------------------------
    # Extract numbers
    # --------------------------------------------------------

    numbers = []
    stars = []

    balls_container = latest_result_container.find(
        'div',
        class_='balls'
    )

    if not balls_container:

        balls_container = latest_result_container.find(
            lambda t:
                t.name in ['div', 'ul', 'ol']
                and (
                    (
                        t.get('class')
                        and any(
                            re.search(
                                r'\bballs?\b',
                                c,
                                re.I
                            )
                            for c in t.get('class')
                        )
                    )
                    or
                    (
                        'balls'
                        in (t.get('id') or '')
                    )
                )
        )

    if balls_container:

        ordered_li_digits = []

        for li in balls_container.find_all('li'):

            classes = li.get('class') or []

            is_star = any(
                re.search(
                    r'(lucky|star)',
                    cls,
                    re.I
                )
                for cls in classes
            )

            text = li.get_text(strip=True)

            m = re.search(
                r'\b(\d{1,2})\b',
                text
            )

            if not m:
                continue

            v = int(m.group(1))

            ordered_li_digits.append(v)

            if is_star:

                if (
                    1 <= v <= 12
                    and v not in stars
                ):
                    stars.append(v)

            else:

                if (
                    1 <= v <= 50
                    and v not in numbers
                ):
                    numbers.append(v)

        # Ball spans

        for ball_span in balls_container.find_all(
            'span',
            class_=lambda c:
                isinstance(c, str)
                and re.search(
                    r'\bball\b',
                    c,
                    re.I
                )
        ):

            text = ball_span.get_text(
                strip=True
            )

            if re.fullmatch(
                r'\d{1,2}',
                text
            ):

                try:
                    n = int(text)

                    if (
                        1 <= n <= 50
                        and n not in numbers
                    ):
                        numbers.append(n)

                except Exception:
                    pass

        # Lucky star spans

        for star_span in balls_container.find_all(
            'span',
            class_=lambda c:
                isinstance(c, str)
                and re.search(
                    r'(lucky\s*star|star)',
                    c,
                    re.I
                )
        ):

            text = star_span.get_text(
                strip=True
            )

            if re.fullmatch(
                r'\d{1,2}',
                text
            ):

                try:
                    s = int(text)

                    if (
                        1 <= s <= 12
                        and s not in stars
                    ):
                        stars.append(s)

                except Exception:
                    pass

    # --------------------------------------------------------
    # Mains/stars list fallback
    # --------------------------------------------------------

    if (
        len(numbers) < 5
        or len(stars) < 2
    ):

        mains_list = None

        candidate_mains = []

        for lst in latest_result_container.find_all(
            ['ul', 'ol']
        ):

            lst_classes = " ".join(
                lst.get('class') or []
            )

            hint_main = re.search(
                r'(balls|main|winning)',
                lst_classes,
                re.I
            )

            vals = []

            for node in lst.find_all(
                ['li', 'span']
            ):

                t = node.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    t
                ):

                    v = int(t)

                    if 1 <= v <= 50:
                        vals.append(v)

            if (
                len(vals) >= 5
                and (
                    hint_main
                    or len(vals) == 5
                )
            ):
                candidate_mains.append(
                    (lst, vals)
                )

        if candidate_mains:

            mains_list, mains_vals = (
                candidate_mains[0]
            )

            if len(numbers) < 5:
                numbers = mains_vals[:5]

        if (
            mains_list
            and len(stars) < 2
        ):

            parent = mains_list.parent

            sibling_lists = (
                parent.find_all(
                    ['ul', 'ol'],
                    recursive=False
                )
                if parent
                else []
            )

            for lst in sibling_lists:

                if lst is mains_list:
                    continue

                lst_classes = " ".join(
                    lst.get('class') or []
                )

                svals = []

                for node in lst.find_all(
                    ['li', 'span']
                ):

                    t = node.get_text(
                        strip=True
                    )

                    if re.fullmatch(
                        r'\d{1,2}',
                        t
                    ):

                        v = int(t)

                        if 1 <= v <= 12:
                            svals.append(v)

                if (
                    re.search(
                        r'(lucky|stars)',
                        lst_classes,
                        re.I
                    )
                    and len(svals) >= 2
                ):

                    stars = svals[:2]
                    break

    # --------------------------------------------------------
    # Generic span fallback
    # --------------------------------------------------------

    if len(numbers) < 5:

        generic_spans = (
            latest_result_container.find_all(
                'span'
            )
        )

        for sp in generic_spans:

            if (
                date_heading
                and date_heading in sp.parents
            ):
                continue

            text = sp.get_text(
                strip=True
            )

            if re.fullmatch(
                r'\d{1,2}',
                text
            ):

                try:

                    val = int(text)

                    if (
                        1 <= val <= 50
                        and val not in numbers
                    ):
                        numbers.append(val)

                except Exception:
                    pass

            if len(numbers) >= 5:
                break

    # --------------------------------------------------------
    # Lucky Stars label fallback
    # --------------------------------------------------------

    if len(stars) < 2:

        star_label = latest_result_container.find(
            string=re.compile(
                r'Lucky\s*Stars?',
                re.I
            )
        )

        if star_label:

            parent = (
                star_label.parent
                if hasattr(
                    star_label,
                    'parent'
                )
                else latest_result_container
            )

            following_spans = (
                parent.find_all_next(
                    'span',
                    limit=6
                )
            )

            for sp in following_spans:

                if (
                    date_heading
                    and date_heading in sp.parents
                ):
                    continue

                text = sp.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    text
                ):

                    try:

                        val = int(text)

                        if (
                            1 <= val <= 12
                            and val not in stars
                        ):
                            stars.append(val)

                    except Exception:
                        pass

                if len(stars) >= 2:
                    break

    # ========================================================
    # IMPORTANT TEXT FALLBACK FOR EUROMILLONES.COM
    #
    # The current page structure is:
    #
    # Tuesday, 08 September 2026
    # 13 17 33 35 39 7 12
    # Category Winners Prize
    # ========================================================

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):

        try:

            full_text = soup.get_text(
                " ",
                strip=True
            )

            date_text_value = (
                date_match.group(0)
            )

            date_pos = full_text.find(
                date_text_value
            )

            if date_pos >= 0:

                after_date = (
                    full_text[
                        date_pos
                        + len(date_text_value):
                    ]
                )

                stop_match = re.search(
                    r'\bCategory\s+Winners\s+Prize\b',
                    after_date,
                    re.I
                )

                if stop_match:

                    result_window = (
                        after_date[
                            :stop_match.start()
                        ]
                    )

                else:

                    result_window = (
                        after_date[:500]
                    )

                tokens = [
                    int(x)
                    for x in re.findall(
                        r'\b\d{1,2}\b',
                        result_window
                    )
                ]

                if len(tokens) >= 7:

                    candidate_numbers = (
                        tokens[:5]
                    )

                    candidate_stars = (
                        tokens[5:7]
                    )

                    if (
                        len(candidate_numbers) == 5
                        and len(candidate_stars) == 2
                        and all(
                            1 <= n <= 50
                            for n in candidate_numbers
                        )
                        and all(
                            1 <= s <= 12
                            for s in candidate_stars
                        )
                    ):

                        numbers = candidate_numbers
                        stars = candidate_stars

        except Exception:
            pass

    # --------------------------------------------------------
    # Final validation fallback
    # --------------------------------------------------------

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):

        full_text = soup.get_text(
            " ",
            strip=True
        )

        try:

            start_idx = (
                full_text.index(
                    date_match.group(0)
                )
                + len(date_match.group(0))
            )

        except Exception:

            start_idx = 0

        window = full_text[
            start_idx:start_idx + 6000
        ]

        star_label_m = re.search(
            r'(Lucky\s*Stars?|Estrellas?)',
            window,
            re.I
        )

        if star_label_m:

            before = window[
                :star_label_m.start()
            ]

            after = window[
                star_label_m.end():
            ]

            mains_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    before
                )
            ]

            stars_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    after
                )
            ]

            mains = []

            for v in mains_tokens:

                if (
                    1 <= v <= 50
                    and v not in mains
                ):
                    mains.append(v)

                if len(mains) == 5:
                    break

            stars_c = []

            for v in stars_tokens:

                if (
                    1 <= v <= 12
                    and v not in stars_c
                ):
                    stars_c.append(v)

                if len(stars_c) == 2:
                    break

            if (
                len(mains) == 5
                and len(stars_c) == 2
            ):

                numbers = mains
                stars = stars_c

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):
        return None

    if not all(
        1 <= n <= 50
        for n in numbers
    ):
        return None

    if not all(
        1 <= s <= 12
        for s in stars
    ):
        return None

    return {
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "stars": sorted(stars),
        "jackpot": None,
        "winners": None
    }


# ============================================================
# PARSE DRAW FOR SPECIFIC DATE
# ============================================================

def parse_draw_for_date(
    html_content,
    target_date_str,
    collect_debug: bool = False
):

    soup = BeautifulSoup(
        html_content,
        'html.parser'
    )

    try:

        dt = datetime.strptime(
            target_date_str,
            '%Y-%m-%d'
        )

    except Exception:

        return None

    # --------------------------------------------------------
    # Structured JSON extraction
    # --------------------------------------------------------

    def _extract_structured_for_date(
        soup,
        target_date_str
    ):

        def walk(obj):

            results = []

            if isinstance(obj, dict):

                d = None

                for dk in [
                    'date',
                    'drawDate',
                    'draw_date'
                ]:

                    val = obj.get(dk)

                    if isinstance(
                        val,
                        str
                    ):

                        try:

                            d = datetime.strptime(
                                val[:10],
                                '%Y-%m-%d'
                            ).strftime(
                                '%Y-%m-%d'
                            )

                        except Exception:
                            pass

                nums = None
                sts = None

                for nk in [
                    'numbers',
                    'mainNumbers',
                    'main_numbers'
                ]:

                    if (
                        nk in obj
                        and isinstance(
                            obj[nk],
                            list
                        )
                    ):

                        vals = []

                        for x in obj[nk]:

                            sx = str(x)

                            if re.fullmatch(
                                r'\d{1,2}',
                                sx
                            ):

                                iv = int(sx)

                                if (
                                    1 <= iv <= 50
                                ):
                                    vals.append(iv)

                        if len(vals) >= 5:
                            nums = vals[:5]

                for sk in [
                    'luckyStars',
                    'stars',
                    'lucky_numbers'
                ]:

                    if (
                        sk in obj
                        and isinstance(
                            obj[sk],
                            list
                        )
                    ):

                        vals = []

                        for x in obj[sk]:

                            sx = str(x)

                            if re.fullmatch(
                                r'\d{1,2}',
                                sx
                            ):

                                iv = int(sx)

                                if (
                                    1 <= iv <= 12
                                ):
                                    vals.append(iv)

                        if len(vals) >= 2:
                            sts = vals[:2]

                if nums and sts:

                    results.append({
                        'date': d,
                        'numbers': nums,
                        'stars': sts
                    })

                for v in obj.values():
                    results.extend(
                        walk(v)
                    )

            elif isinstance(obj, list):

                for it in obj:
                    results.extend(
                        walk(it)
                    )

            return results

        for script in soup.find_all('script'):

            ttype = (
                script.get('type')
                or ''
            ).lower()

            if (
                'json' not in ttype
                and ttype != ''
            ):
                continue

            text = (
                script.string
                or script.get_text()
                or ''
            )

            if not text.strip():
                continue

            try:

                obj = json.loads(text)

                matches = walk(obj)

                for m in matches:

                    if (
                        m.get('date')
                        == target_date_str
                    ):

                        return (
                            sorted(m['numbers']),
                            sorted(m['stars'])
                        )

            except Exception:

                pattern = re.compile(
                    rf'"(?:date|drawDate|draw_date)"\s*:\s*'
                    rf'"{re.escape(target_date_str)}".*?'
                    rf'"(?:numbers|mainNumbers|main_numbers)"\s*:\s*'
                    rf'\[(.*?)\].*?'
                    rf'"(?:luckyStars|stars|lucky_numbers)"\s*:\s*'
                    rf'\[(.*?)\]',
                    re.S
                )

                m = pattern.search(text)

                if m:

                    nums = [
                        int(x)
                        for x in re.findall(
                            r'\d{1,2}',
                            m.group(1)
                        )
                        if 1 <= int(x) <= 50
                    ]

                    sts = [
                        int(x)
                        for x in re.findall(
                            r'\d{1,2}',
                            m.group(2)
                        )
                        if 1 <= int(x) <= 12
                    ]

                    if (
                        len(nums) >= 5
                        and len(sts) >= 2
                    ):

                        return (
                            sorted(nums[:5]),
                            sorted(sts[:2])
                        )

        return None, None

    jnums, jstars = (
        _extract_structured_for_date(
            soup,
            target_date_str
        )
    )

    numbers = []
    stars = []

    provenance = {
        "source": None,
        "notes": []
    }

    if jnums and jstars:

        numbers = jnums
        stars = jstars

        provenance["source"] = (
            "json_script"
        )

        provenance["notes"].append(
            "Extracted numbers/stars from embedded JSON script for target date"
        )

    weekday = dt.strftime('%A')
    day_no = dt.day
    day_no_z = f"{day_no:02d}"
    month_name = dt.strftime('%B')
    year = dt.strftime('%Y')

    es_days = {
        'Monday': 'Lunes',
        'Tuesday': 'Martes',
        'Wednesday': 'Miércoles',
        'Thursday': 'Jueves',
        'Friday': 'Viernes',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo'
    }

    es_months = {
        'January': 'enero',
        'February': 'febrero',
        'March': 'marzo',
        'April': 'abril',
        'May': 'mayo',
        'June': 'junio',
        'July': 'julio',
        'August': 'agosto',
        'September': 'septiembre',
        'October': 'octubre',
        'November': 'noviembre',
        'December': 'diciembre'
    }

    weekday_es = es_days.get(
        weekday,
        weekday
    )

    month_es = es_months.get(
        month_name,
        month_name
    )

    patterns = [
        rf"{weekday},\s+{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{weekday}\s+{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{weekday},\s+{day_no_z}\s+{month_name}\s+{year}",
        rf"{weekday}\s+{day_no_z}\s+{month_name}\s+{year}",
        rf"{day_no}(?:st|nd|rd|th)?\s+{month_name}\s+{year}",
        rf"{day_no_z}\s+{month_name}\s+{year}",
        rf"{day_no}\s+{month_name}\s+{year}",
        rf"{weekday_es}\s+{day_no}(?:\s+de)?\s+{month_es}\s+de\s+{year}",
        rf"{day_no}(?:\s+de)?\s+{month_es}\s+de\s+{year}",
        rf"{day_no_z}\/{dt.strftime('%m')}\/{year}",
        rf"{dt.strftime('%d')}\/{dt.strftime('%m')}\/{dt.strftime('%y')}",
        rf"{day_no}\/{dt.strftime('%m')}\/{year}",
    ]

    time_tag = soup.find(
        'time',
        attrs={
            'datetime': target_date_str
        }
    )

    date_heading = None

    for h in soup.find_all(
        ['h1', 'h2', 'h3']
    ):

        text = h.get_text(
            strip=True
        )

        if any(
            re.search(
                p,
                text,
                re.I
            )
            for p in patterns
        ):

            date_heading = h
            break

    matched_node = None

    if not date_heading:

        for text_node in soup.find_all(
            string=True
        ):

            txt = (
                text_node or ''
            ).strip()

            if not txt:
                continue

            if any(
                re.search(
                    p,
                    txt,
                    re.I
                )
                for p in patterns
            ):

                matched_node = text_node
                break

    latest_result_container = None

    if time_tag:

        latest_result_container = (
            time_tag.find_parent(
                lambda t:
                    t.name in [
                        'article',
                        'section',
                        'div'
                    ]
            )
            or time_tag.parent
        )

    if (
        date_heading
        and not latest_result_container
    ):

        latest_result_container = (
            date_heading.find_next(
                lambda t:
                    t.name in [
                        'section',
                        'article',
                        'div'
                    ]
                    and t.get_text(strip=True)
            )
        )

        if not latest_result_container:
            latest_result_container = (
                date_heading.parent
            )

    elif matched_node:

        try:
            latest_result_container = (
                matched_node.parent
            )
        except Exception:
            latest_result_container = None

    draw_date = dt.strftime(
        '%Y-%m-%d'
    )

    # --------------------------------------------------------
    # Container extraction
    # --------------------------------------------------------

    def extract_from_container(
        container
    ):

        local_numbers = []
        local_stars = []

        if not container:
            return (
                local_numbers,
                local_stars
            )

        balls_container = container.find(
            lambda t:
                t.name in [
                    'div',
                    'ul',
                    'ol'
                ]
                and (
                    (
                        t.get('class')
                        and any(
                            re.search(
                                r'\bballs?\b',
                                c,
                                re.I
                            )
                            for c in t.get('class')
                        )
                    )
                    or
                    (
                        'balls'
                        in (t.get('id') or '')
                    )
                )
        )

        if balls_container:

            for li in balls_container.find_all(
                'li'
            ):

                classes = li.get(
                    'class'
                ) or []

                is_star = any(
                    re.search(
                        r'(lucky|star)',
                        cls,
                        re.I
                    )
                    for cls in classes
                )

                t = li.get_text(
                    strip=True
                )

                m = re.search(
                    r'\b(\d{1,2})\b',
                    t
                )

                if not m:
                    continue

                v = int(m.group(1))

                if is_star:

                    if (
                        1 <= v <= 12
                        and v not in local_stars
                    ):
                        local_stars.append(v)

                else:

                    if (
                        1 <= v <= 50
                        and v not in local_numbers
                    ):
                        local_numbers.append(v)

            for ball_span in balls_container.find_all(
                'span',
                class_=lambda c:
                    isinstance(c, str)
                    and re.search(
                        r'\bball\b',
                        c,
                        re.I
                    )
            ):

                text = ball_span.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    text
                ):

                    n = int(text)

                    if (
                        1 <= n <= 50
                        and n not in local_numbers
                    ):
                        local_numbers.append(n)

            for star_span in balls_container.find_all(
                'span',
                class_=lambda c:
                    isinstance(c, str)
                    and re.search(
                        r'(lucky\s*star|star)',
                        c,
                        re.I
                    )
            ):

                text = star_span.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    text
                ):

                    s = int(text)

                    if (
                        1 <= s <= 12
                        and s not in local_stars
                    ):
                        local_stars.append(s)

        # Mains and stars lists

        if (
            len(local_numbers) < 5
            or len(local_stars) < 2
        ):

            mains_list = None
            candidate_mains = []

            for lst in container.find_all(
                ['ul', 'ol']
            ):

                lst_classes = " ".join(
                    lst.get('class') or []
                )

                hint_main = re.search(
                    r'(balls|main|winning)',
                    lst_classes,
                    re.I
                )

                vals = []

                for node in lst.find_all(
                    ['li', 'span']
                ):

                    t = node.get_text(
                        strip=True
                    )

                    if re.fullmatch(
                        r'\d{1,2}',
                        t
                    ):

                        v = int(t)

                        if 1 <= v <= 50:
                            vals.append(v)

                if (
                    len(vals) >= 5
                    and (
                        hint_main
                        or len(vals) == 5
                    )
                ):

                    candidate_mains.append(
                        (lst, vals)
                    )

            if candidate_mains:

                mains_list, mains_vals = (
                    candidate_mains[0]
                )

                if len(local_numbers) < 5:
                    local_numbers = mains_vals[:5]

            if (
                mains_list
                and len(local_stars) < 2
            ):

                parent = mains_list.parent

                sibling_lists = (
                    parent.find_all(
                        ['ul', 'ol'],
                        recursive=False
                    )
                    if parent
                    else []
                )

                for lst in sibling_lists:

                    if lst is mains_list:
                        continue

                    lst_classes = " ".join(
                        lst.get('class') or []
                    )

                    svals = []

                    for node in lst.find_all(
                        ['li', 'span']
                    ):

                        t = node.get_text(
                            strip=True
                        )

                        if re.fullmatch(
                            r'\d{1,2}',
                            t
                        ):

                            v = int(t)

                            if 1 <= v <= 12:
                                svals.append(v)

                    if (
                        re.search(
                            r'(lucky|stars)',
                            lst_classes,
                            re.I
                        )
                        and len(svals) >= 2
                    ):

                        local_stars = svals[:2]
                        break

        # Generic scan

        if len(local_numbers) < 5:

            for sp in container.find_all(
                ['span', 'li', 'div']
            ):

                t = sp.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    t
                ):

                    v = int(t)

                    if (
                        1 <= v <= 50
                        and v not in local_numbers
                    ):

                        local_numbers.append(v)

                if len(local_numbers) >= 5:
                    break

        if len(local_numbers) < 5:

            for lst in container.find_all(
                ['ul', 'ol'],
                limit=3
            ):

                for li in lst.find_all(
                    'li'
                ):

                    t = li.get_text(
                        strip=True
                    )

                    if re.fullmatch(
                        r'\d{1,2}',
                        t
                    ):

                        v = int(t)

                        if (
                            1 <= v <= 50
                            and v not in local_numbers
                        ):

                            local_numbers.append(v)

                        if len(local_numbers) >= 5:
                            break

                if len(local_numbers) >= 5:
                    break

        # Lucky stars label

        if len(local_stars) < 2:

            star_label = container.find(
                string=re.compile(
                    r'(Lucky\s*Stars?|Estrellas?)',
                    re.I
                )
            )

            if star_label:

                parent = (
                    star_label.parent
                    if hasattr(
                        star_label,
                        'parent'
                    )
                    else container
                )

                for sp in parent.find_all_next(
                    'span',
                    limit=6
                ):

                    t = sp.get_text(
                        strip=True
                    )

                    if re.fullmatch(
                        r'\d{1,2}',
                        t
                    ):

                        v = int(t)

                        if (
                            1 <= v <= 12
                            and v not in local_stars
                        ):
                            local_stars.append(v)

                    if len(local_stars) >= 2:
                        break

        return (
            local_numbers,
            local_stars
        )

    n1, s1 = extract_from_container(
        latest_result_container
    )

    numbers.extend(n1)
    stars.extend(s1)

    if (
        len(numbers) == 5
        and len(stars) == 2
        and provenance["source"] is None
    ):

        provenance["source"] = (
            "container_extraction"
        )

        provenance["notes"].append(
            "Extracted from container near date heading"
        )

    # --------------------------------------------------------
    # Text window fallback
    # --------------------------------------------------------

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):

        full_text = soup.get_text(
            " ",
            strip=True
        )

        match_idx = None

        for p in patterns:

            m = re.search(
                p,
                full_text,
                re.I
            )

            if m:
                match_idx = m.end()
                break

        if match_idx is None:
            return None

        any_date_re = re.compile(
            r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
            r"Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo)"
            r"[^\d]{0,12}\d{1,2}[^\n\r]{0,20}"
            r"(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December|enero|febrero|marzo|"
            r"abril|mayo|junio|julio|agosto|septiembre|octubre|"
            r"noviembre|diciembre)[^\n\r]{0,15}\d{4}"
            r"|\b\d{1,2}\/\d{2}\/\d{4}\b)",
            re.I
        )

        tail_text = full_text[
            match_idx:
        ]

        next_m = any_date_re.search(
            tail_text
        )

        end_idx = (
            match_idx
            + (
                next_m.start()
                if next_m
                else len(full_text)
            )
        )

        window = full_text[
            match_idx:end_idx
        ]

        star_label_m = re.search(
            r'(Lucky\s*Stars?|Estrellas?)',
            window,
            re.I
        )

        if star_label_m:

            before = window[
                :star_label_m.start()
            ]

            after = window[
                star_label_m.end():
            ]

            mains_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    before
                )
            ]

            stars_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    after
                )
            ]

            mains = []

            for v in mains_tokens:

                if (
                    1 <= v <= 50
                    and v not in mains
                ):
                    mains.append(v)

                if len(mains) == 5:
                    break

            stars_c = []

            for v in stars_tokens:

                if (
                    1 <= v <= 12
                    and v not in stars_c
                ):
                    stars_c.append(v)

                if len(stars_c) == 2:
                    break

            if (
                len(mains) == 5
                and len(stars_c) == 2
            ):

                numbers = mains
                stars = stars_c

                if provenance["source"] is None:

                    provenance["source"] = (
                        "token_scan"
                    )

                    provenance["notes"].append(
                        "Used Lucky Stars token scan"
                    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):
        return None

    if not all(
        1 <= n <= 50
        for n in numbers
    ):
        return None

    if not all(
        1 <= s <= 12
        for s in stars
    ):
        return None

    result = {
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "stars": sorted(stars),
        "jackpot": None,
        "winners": None
    }

    if collect_debug:
        result["debug"] = provenance

    return result


# ============================================================
# PARSE DETAIL PAGE
# ============================================================

def parse_draw_detail_page(
    html_content,
    target_date_str,
    collect_debug: bool = False
):

    soup = BeautifulSoup(
        html_content,
        'html.parser'
    )

    numbers = []
    stars = []

    provenance = {
        "source": None,
        "notes": []
    }

    # --------------------------------------------------------
    # Structured data
    # --------------------------------------------------------

    def _extract_structured_result_from_scripts(
        soup,
        target_date_str=None
    ):

        def walk(obj):

            found = []

            if isinstance(obj, dict):

                d = None

                for dk in [
                    'date',
                    'drawDate',
                    'draw_date'
                ]:

                    val = obj.get(dk)

                    if isinstance(
                        val,
                        str
                    ):

                        try:

                            d = datetime.strptime(
                                val[:10],
                                '%Y-%m-%d'
                            ).strftime(
                                '%Y-%m-%d'
                            )

                        except Exception:
                            pass

                nums = None
                sts = None

                for nk in [
                    'numbers',
                    'mainNumbers',
                    'main_numbers'
                ]:

                    if (
                        nk in obj
                        and isinstance(
                            obj[nk],
                            list
                        )
                    ):

                        vals = []

                        for x in obj[nk]:

                            sx = str(x)

                            if re.fullmatch(
                                r'\d{1,2}',
                                sx
                            ):

                                iv = int(sx)

                                if (
                                    1 <= iv <= 50
                                ):
                                    vals.append(iv)

                        if len(vals) >= 5:
                            nums = vals[:5]

                for sk in [
                    'luckyStars',
                    'stars',
                    'lucky_numbers'
                ]:

                    if (
                        sk in obj
                        and isinstance(
                            obj[sk],
                            list
                        )
                    ):

                        vals = []

                        for x in obj[sk]:

                            sx = str(x)

                            if re.fullmatch(
                                r'\d{1,2}',
                                sx
                            ):

                                iv = int(sx)

                                if (
                                    1 <= iv <= 12
                                ):
                                    vals.append(iv)

                        if len(vals) >= 2:
                            sts = vals[:2]

                if nums and sts:

                    found.append({
                        'date': d,
                        'numbers': nums,
                        'stars': sts
                    })

                for v in obj.values():
                    found.extend(
                        walk(v)
                    )

            elif isinstance(obj, list):

                for it in obj:
                    found.extend(
                        walk(it)
                    )

            return found

        for script in soup.find_all('script'):

            ttype = (
                script.get('type')
                or ''
            ).lower()

            if (
                'json' not in ttype
                and ttype != ''
            ):
                continue

            text = (
                script.string
                or script.get_text()
                or ''
            )

            if not text.strip():
                continue

            try:

                obj = json.loads(text)

                matches = walk(obj)

                if target_date_str:

                    for m in matches:

                        if (
                            m.get('date')
                            == target_date_str
                        ):

                            return (
                                sorted(m['numbers']),
                                sorted(m['stars'])
                            )

                if matches:

                    m = matches[0]

                    return (
                        sorted(m['numbers']),
                        sorted(m['stars'])
                    )

            except Exception:

                m_nums = re.search(
                    r'"(?:numbers|mainNumbers|main_numbers)"'
                    r'\s*:\s*\[(.*?)\]',
                    text,
                    re.S
                )

                m_stars = re.search(
                    r'"(?:luckyStars|stars|lucky_numbers)"'
                    r'\s*:\s*\[(.*?)\]',
                    text,
                    re.S
                )

                if m_nums and m_stars:

                    nums = [
                        int(x)
                        for x in re.findall(
                            r'\d{1,2}',
                            m_nums.group(1)
                        )
                        if 1 <= int(x) <= 50
                    ]

                    sts = [
                        int(x)
                        for x in re.findall(
                            r'\d{1,2}',
                            m_stars.group(1)
                        )
                        if 1 <= int(x) <= 12
                    ]

                    if (
                        len(nums) >= 5
                        and len(sts) >= 2
                    ):

                        return (
                            sorted(nums[:5]),
                            sorted(sts[:2])
                        )

        return None, None

    jnums, jstars = (
        _extract_structured_result_from_scripts(
            soup,
            target_date_str
        )
    )

    if jnums and jstars:

        numbers = jnums
        stars = jstars

        provenance["source"] = (
            "json_script"
        )

        provenance["notes"].append(
            "Extracted numbers/stars from embedded JSON script"
        )

    # --------------------------------------------------------
    # Container
    # --------------------------------------------------------

    container = None

    time_tag = soup.find(
        'time',
        attrs={
            'datetime': target_date_str
        }
    )

    if time_tag:

        container = (
            time_tag.find_parent(
                lambda t:
                    t.name in [
                        'article',
                        'section',
                        'div'
                    ]
            )
            or time_tag.parent
        )

    if not container:

        date_h = soup.find(
            ['h1', 'h2'],
            string=re.compile(
                r'EuroMillions\s+Results',
                re.I
            )
        )

        if date_h:

            container = (
                date_h.find_parent(
                    lambda t:
                        t.name in [
                            'article',
                            'section',
                            'div'
                        ]
                )
                or date_h.parent
            )

    candidates = [
        {
            'name': 'div',
            'class': re.compile(
                r'(balls|winning|numbers|result|'
                r'draw-results|primary|secondary)',
                re.I
            )
        },
        {
            'name': 'section',
            'class': re.compile(
                r'(result|numbers|euromillions)',
                re.I
            )
        },
        {
            'name': 'article',
            'class': re.compile(
                r'(result|euromillions)',
                re.I
            )
        },
    ]

    for c in candidates:

        found = soup.find(
            c['name'],
            class_=c['class']
        )

        if found:

            container = found
            break

    if not container:
        container = soup

    # --------------------------------------------------------
    # Explicit ball spans
    # --------------------------------------------------------

    mains_spans = container.find_all(
        'span',
        class_=lambda c:
            isinstance(c, str)
            and (
                'ball' in c.lower()
            )
            and (
                'star' not in c.lower()
            )
            and (
                'lucky' not in c.lower()
            )
    )

    for sp in mains_spans:

        t = sp.get_text(
            strip=True
        )

        if re.fullmatch(
            r'\d{1,2}',
            t
        ):

            v = int(t)

            if (
                1 <= v <= 50
                and v not in numbers
            ):
                numbers.append(v)

        if len(numbers) >= 5:
            break

    if len(numbers) < 5:

        stars_spans = container.find_all(
            'span',
            class_=lambda c:
                isinstance(c, str)
                and (
                    'lucky' in c.lower()
                    or 'star' in c.lower()
                )
        )

        for sp in stars_spans:

            t = sp.get_text(
                strip=True
            )

            if re.fullmatch(
                r'\d{1,2}',
                t
            ):

                v = int(t)

                if (
                    1 <= v <= 12
                    and v not in stars
                ):
                    stars.append(v)

            if len(stars) >= 2:
                break

    # --------------------------------------------------------
    # Explicit lists
    # --------------------------------------------------------

    if (
        len(numbers) < 5
        or len(stars) < 2
    ):

        mains_list = container.find(
            ['ul', 'ol'],
            class_=re.compile(
                r'(balls|main|winning)',
                re.I
            )
        )

        stars_list = container.find(
            ['ul', 'ol'],
            class_=re.compile(
                r'(lucky|stars)',
                re.I
            )
        )

        if (
            mains_list
            and len(numbers) < 5
        ):

            vals = []

            for li in mains_list.find_all(
                'li'
            ):

                t = li.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    t
                ):

                    v = int(t)

                    if 1 <= v <= 50:
                        vals.append(v)

            if len(vals) >= 5:
                numbers = vals[:5]

        if (
            stars_list
            and len(stars) < 2
        ):

            svals = []

            for li in stars_list.find_all(
                'li'
            ):

                t = li.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    t
                ):

                    v = int(t)

                    if 1 <= v <= 12:
                        svals.append(v)

            if len(svals) >= 2:
                stars = svals[:2]

    # --------------------------------------------------------
    # Cluster extraction
    # --------------------------------------------------------

    def extract_cluster(parent):

        mains = []
        lucky = []

        if not parent:
            return mains, lucky

        lists = []

        lists += parent.find_all(
            'ul',
            class_=re.compile(
                r'(balls|numbers|main|winning)',
                re.I
            )
        )

        lists += parent.find_all(
            'ol',
            class_=re.compile(
                r'(balls|numbers|main|winning)',
                re.I
            )
        )

        for lst in lists:

            vals = []

            for li in lst.find_all(
                'li'
            ):

                t = li.get_text(
                    strip=True
                )

                if re.fullmatch(
                    r'\d{1,2}',
                    t
                ):
                    vals.append(
                        int(t)
                    )

            if (
                len(vals) >= 5
                and all(
                    1 <= v <= 50
                    for v in vals[:5]
                )
            ):

                mains = vals[:5]

                next_sibling = (
                    lst.find_next(
                        string=re.compile(
                            r'(Lucky\s*Stars?|Estrellas?)',
                            re.I
                        )
                    )
                )

                if next_sibling:

                    stars_parent = (
                        next_sibling.parent
                        if hasattr(
                            next_sibling,
                            'parent'
                        )
                        else parent
                    )

                    stars_vals = []

                    for sp in stars_parent.find_all_next(
                        ['li', 'span'],
                        limit=6
                    ):

                        tt = sp.get_text(
                            strip=True
                        )

                        if re.fullmatch(
                            r'\d{1,2}',
                            tt
                        ):

                            vv = int(tt)

                            if 1 <= vv <= 12:
                                stars_vals.append(
                                    vv
                                )

                        if len(stars_vals) >= 2:
                            break

                    if len(stars_vals) >= 2:
                        lucky = stars_vals[:2]

                if (
                    len(mains) == 5
                    and len(lucky) == 2
                ):
                    return mains, lucky

        return mains, lucky

    if (
        len(numbers) < 5
        or len(stars) < 2
    ):

        m1, s1 = extract_cluster(
            container
        )

        if len(numbers) < 5:
            numbers = m1

        if len(stars) < 2:
            stars = s1

    # --------------------------------------------------------
    # Lucky Stars text scan
    # --------------------------------------------------------

    if (
        len(numbers) < 5
        or len(stars) < 2
    ):

        full_text = soup.get_text(
            " ",
            strip=True
        )

        label_m = re.search(
            r'(Lucky\s*Stars?|Estrellas?)',
            full_text,
            re.I
        )

        if label_m:

            before = full_text[
                :label_m.start()
            ]

            after = full_text[
                label_m.end():
            ]

            mains_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    before
                )
            ]

            stars_tokens = [
                int(t)
                for t in re.findall(
                    r'\b\d{1,2}\b',
                    after
                )
            ]

            mains = []

            for v in mains_tokens:

                if (
                    1 <= v <= 50
                    and v not in mains
                ):
                    mains.append(v)

                if len(mains) == 5:
                    break

            stars_c = []

            for v in stars_tokens:

                if (
                    1 <= v <= 12
                    and v not in stars_c
                ):
                    stars_c.append(v)

                if len(stars_c) == 2:
                    break

            if (
                len(mains) == 5
                and len(stars_c) == 2
            ):

                numbers = mains
                stars = stars_c

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if (
        len(numbers) != 5
        or len(stars) != 2
    ):
        return None

    draw_date = target_date_str

    result = {
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "stars": sorted(stars),
        "jackpot": None,
        "winners": None
    }

    if collect_debug:
        result["debug"] = provenance

    return result


# ============================================================
# SYNC LATEST DRAW
# ============================================================

@app.route('/api/sync', methods=['GET', 'POST'])
def sync_latest():

    try:

        from .db import (
            ensure_schema,
            upsert_draw,
            get_last_db_debug
        )

        if not ensure_schema():
            return jsonify({
                "error": "Database schema check failed",
                "db_debug": get_last_db_debug()
            }), 500

        # YOUR CHOSEN SOURCE
        source_url = os.getenv(
            "EURO_SOURCE_URL",
            "https://www.euromillones.com/en/results/euromillions"
        )

        # ----------------------------------------------------
        # FETCH SOURCE PAGE
        # ----------------------------------------------------

        try:

            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.8",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/127.0 Safari/537.36"
                )
            }

            resp = requests.get(
                source_url,
                timeout=(5, 20),
                headers=headers
            )

            resp.raise_for_status()

            draw = parse_draw_from_page(
                resp.text
            )

        except Exception as e:

            traceback.print_exc()

            return jsonify({
                "error": "Failed to fetch source page",
                "details": str(e),
                "url": source_url
            }), 502

        # ----------------------------------------------------
        # FALLBACK IF PRIMARY PARSER FAILED
        # ----------------------------------------------------

        if not draw:

            soup = BeautifulSoup(
                resp.text,
                'html.parser'
            )

            target_date = None

            # Prefer <time datetime>
            t = soup.find(
                'time',
                attrs={
                    'datetime': re.compile(
                        r'^\d{4}-\d{2}-\d{2}'
                    )
                }
            )

            if (
                t
                and t.get('datetime')
            ):

                target_date = (
                    t.get('datetime')[:10]
                )

            if not target_date:

                full_text = soup.get_text(
                    " ",
                    strip=True
                )

                m_iso = re.search(
                    r'\b(\d{4}-\d{2}-\d{2})\b',
                    full_text
                )

                if m_iso:
                    target_date = m_iso.group(1)

            if not target_date:

                m_dmy = re.search(
                    r'\b(\d{2})\/(\d{2})\/(\d{4})\b',
                    full_text
                )

                if m_dmy:

                    d, m, y = (
                        m_dmy.groups()
                    )

                    target_date = (
                        f"{y}-{m}-{d}"
                    )

            if not target_date:

                m_txt = re.search(
                    r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
                    r'(\d{1,2})(?:st|nd|rd|th)?\s+'
                    r'([A-Za-z]+)\s+'
                    r'(\d{4})',
                    full_text
                )

                if not m_txt:

                    m_txt = re.search(
                        r'(\d{1,2})(?:st|nd|rd|th)?\s+'
                        r'([A-Za-z]+)\s+'
                        r'(\d{4})',
                        full_text
                    )

                if m_txt:

                    day = m_txt.group(
                        1
                    ).zfill(2)

                    month_name = m_txt.group(
                        2
                    )

                    year = m_txt.group(
                        3
                    )

                    month_map = {
                        'January': '01',
                        'February': '02',
                        'March': '03',
                        'April': '04',
                        'May': '05',
                        'June': '06',
                        'July': '07',
                        'August': '08',
                        'September': '09',
                        'October': '10',
                        'November': '11',
                        'December': '12'
                    }

                    month = month_map.get(
                        str(month_name).capitalize(),
                        '01'
                    )

                    target_date = (
                        f"{year}-{month}-{day}"
                    )

            # ------------------------------------------------
            # DETAIL / ARCHIVE FALLBACKS
            # ------------------------------------------------

            if target_date:

                p = urlparse(
                    source_url
                )

                base = (
                    f"{p.scheme}://{p.netloc}"
                )

                year = datetime.strptime(
                    target_date,
                    '%Y-%m-%d'
                ).strftime('%Y')

                date_dash = datetime.strptime(
                    target_date,
                    '%Y-%m-%d'
                ).strftime('%d-%m-%Y')

                bases = []

                euro_millions = (
                    f"{p.scheme}://www.euro-millions.com"
                )

                euromillones = (
                    f"{p.scheme}://www.euromillones.com"
                )

                bases.append(
                    euro_millones
                )

                bases.append(
                    euro_millions
                )

                if base not in bases:
                    bases.insert(
                        0,
                        base
                    )

                seen = set()

                bases = [
                    b
                    for b in bases
                    if not (
                        b in seen
                        or seen.add(b)
                    )
                ]

                candidates = []

                for b in bases:

                    candidates.append(
                        urljoin(
                            b,
                            f"/en/results/euromillions/{target_date}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/en/results/euromillions/{date_dash}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/results/euromillions/{target_date}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/results/euromillions/{date_dash}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/results/{target_date}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/results/{date_dash}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/amp/results/{target_date}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/amp/results/{date_dash}"
                        )
                    )

                    candidates.append(
                        urljoin(
                            b,
                            f"/results-history-{year}"
                        )
                    )

                tried = []

                for url in candidates:

                    try:

                        r2 = requests.get(
                            url,
                            timeout=(5, 20),
                            headers={
                                "Accept": "text/html",
                                "User-Agent": (
                                    "Mozilla/5.0 "
                                    "(Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 "
                                    "Chrome/127 Safari/537.36"
                                )
                            }
                        )

                        tried.append({
                            "url": url,
                            "status": r2.status_code,
                            "length": len(r2.text)
                        })

                        if r2.status_code == 200:

                            if (
                                f"/results-history-{year}"
                                in url
                            ):

                                d2 = parse_draw_for_date(
                                    r2.text,
                                    target_date,
                                    collect_debug=False
                                )

                            else:

                                d2 = parse_draw_detail_page(
                                    r2.text,
                                    target_date,
                                    collect_debug=False
                                )

                            if d2:

                                draw = d2
                                break

                    except Exception as e:

                        tried.append({
                            "url": url,
                            "status": "error",
                            "error": str(e)
                        })

                if not draw:

                    return jsonify({
                        "error": "Could not parse latest draw via fallbacks",
                        "url": source_url,
                        "derived_date": target_date,
                        "html_preview": (
                            resp.text[:800] + "..."
                            if len(resp.text) > 800
                            else resp.text
                        ),
                        "html_length": len(resp.text),
                        "fallback_attempts": tried
                    }), 422

            else:

                return jsonify({
                    "error": "Could not parse draw from page",
                    "reason": "No target date could be derived",
                    "html_preview": (
                        resp.text[:500] + "..."
                        if len(resp.text) > 500
                        else resp.text
                    ),
                    "html_length": len(resp.text),
                    "url": source_url
                }), 422

        # ====================================================
        # DATABASE PERSISTENCE
        # ====================================================

        try:

            ok = upsert_draw(draw)

            if not ok:

                return jsonify({
                    "error": "Failed to persist draw",
                    "details": "upsert_draw returned False",
                    "draw": draw,
                    "db_debug": get_last_db_debug()
                }), 500

        except Exception as e:

            traceback.print_exc()

            return jsonify({
                "error": "Failed to persist draw",
                "details": str(e),
                "trace": traceback.format_exc(),
                "draw": draw,
                "db_debug": get_last_db_debug()
            }), 500

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        return jsonify({
            "status": "ok",
            "upserted": draw.get("draw_date"),
            "parsed": draw
        })

    except Exception as e:

        return jsonify({
            "error": "Sync failed",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# SYNC SPECIFIC DATE
# ============================================================

@app.route('/api/sync_date')
def sync_date():

    try:

        from .db import (
            ensure_schema,
            upsert_draw,
            get_last_db_debug
        )

        if not ensure_schema():
            return jsonify({
                "error": "Database schema check failed",
                "db_debug": get_last_db_debug()
            }), 500

        target_date = request.args.get(
            'date'
        )

        debug_flag = request.args.get(
            'debug'
        )

        collect_debug = (
            str(debug_flag or '').lower()
            in (
                '1',
                'true',
                'yes',
                'on'
            )
        )

        if not target_date:

            return jsonify({
                "error": (
                    "Missing required query param "
                    "'date' (YYYY-MM-DD)"
                )
            }), 400

        try:

            datetime.strptime(
                target_date,
                '%Y-%m-%d'
            )

        except Exception:

            return jsonify({
                "error": (
                    "Invalid date format. "
                    "Use YYYY-MM-DD"
                )
            }), 400

        # YOUR CHOSEN SOURCE
        source_url = os.getenv(
            "EURO_SOURCE_URL",
            "https://www.euromillones.com/en/results/euromillions"
        )

        headers = {
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": (
                "en-US,en;q=0.8"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0 Safari/537.36"
            )
        }

        primary_fetch_error = None
        resp = None
        draw = None

        # ----------------------------------------------------
        # PRIMARY PAGE
        # ----------------------------------------------------

        try:

            resp = requests.get(
                source_url,
                timeout=(5, 20),
                headers=headers
            )

            resp.raise_for_status()

            draw = parse_draw_for_date(
                resp.text,
                target_date,
                collect_debug=collect_debug
            )

        except Exception as e:

            primary_fetch_error = str(e)

        # ----------------------------------------------------
        # FALLBACK PAGES
        # ----------------------------------------------------

        if not draw:

            p = urlparse(
                source_url
            )

            base = (
                f"{p.scheme}://{p.netloc}"
            )

            date_dash = datetime.strptime(
                target_date,
                '%Y-%m-%d'
            ).strftime('%d-%m-%Y')

            year = datetime.strptime(
                target_date,
                '%Y-%m-%d'
            ).strftime('%Y')

            bases = []

            euro_millions = (
                f"{p.scheme}://www.euro-millions.com"
            )

            euromillones = (
                f"{p.scheme}://www.euromillones.com"
            )

            bases.append(
                euromillones
            )

            bases.append(
                euro_millions
            )

            if base not in bases:

                bases.insert(
                    0,
                    base
                )

            seen = set()

            bases = [
                b
                for b in bases
                if not (
                    b in seen
                    or seen.add(b)
                )
            ]

            candidates = []

            for b in bases:

                candidates.append(
                    urljoin(
                        b,
                        f"/en/results/euromillions/{target_date}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/en/results/euromillions/{date_dash}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/results/euromillions/{target_date}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/results/euromillions/{date_dash}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/results/{target_date}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/results/{date_dash}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/amp/results/{target_date}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/amp/results/{date_dash}"
                    )
                )

                candidates.append(
                    urljoin(
                        b,
                        f"/results-history-{year}"
                    )
                )

            tried = []

            for url in candidates:

                try:

                    r2 = requests.get(
                        url,
                        timeout=(5, 20),
                        headers=headers
                    )

                    tried.append({
                        "url": url,
                        "status": r2.status_code,
                        "length": len(r2.text)
                    })

                    if r2.status_code == 200:

                        if (
                            f"/results-history-{year}"
                            in url
                        ):

                            d2 = parse_draw_for_date(
                                r2.text,
                                target_date,
                                collect_debug=collect_debug
                            )

                        else:

                            d2 = parse_draw_detail_page(
                                r2.text,
                                target_date,
                                collect_debug=collect_debug
                            )

                        if d2:

                            draw = d2
                            break

                except Exception as e:

                    tried.append({
                        "url": url,
                        "status": "error",
                        "error": str(e)
                    })

            if not draw:

                if resp is not None:

                    time_tags = re.findall(
                        r'<time[^>]*datetime="(.*?)"',
                        resp.text[:50000],
                        flags=re.I
                    )

                    html_preview = (
                        resp.text[:800] + "..."
                        if len(resp.text) > 800
                        else resp.text
                    )

                    html_length = len(
                        resp.text
                    )

                else:

                    time_tags = []
                    html_preview = None
                    html_length = 0

                return jsonify({
                    "error": "Could not parse target draw from page",
                    "date": target_date,
                    "url": source_url,
                    "html_preview": html_preview,
                    "html_length": html_length,
                    "time_tags_found": time_tags[:10],
                    "fallback_attempts": tried,
                    "archive_hint": True,
                    "primary_fetch_error": primary_fetch_error
                }), 422

        # ====================================================
        # DATABASE PERSISTENCE
        # ====================================================

        try:

            ok = upsert_draw(draw)

            if not ok:

                return jsonify({
                    "error": "Failed to persist draw",
                    "details": "upsert_draw returned False",
                    "draw": draw,
                    "db_debug": get_last_db_debug()
                }), 500

        except Exception as e:

            traceback.print_exc()

            return jsonify({
                "error": "Failed to persist draw",
                "details": str(e),
                "trace": traceback.format_exc(),
                "draw": draw,
                "db_debug": get_last_db_debug()
            }), 500

        return jsonify({
            "status": "ok",
            "upserted": draw.get("draw_date"),
            "parsed": draw
        })

    except Exception as e:

        return jsonify({
            "error": "Sync date failed",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500
