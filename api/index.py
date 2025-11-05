# Add a print at the very top to confirm the file is loaded.
print("DEBUG: api/index.py is being loaded.", flush=True)

import logging
logging.basicConfig(level=logging.INFO)

try:
    print("DEBUG: Attempting to import Flask...", flush=True)
    from flask import Flask, jsonify, request
    print("DEBUG: Flask imported successfully.", flush=True)

    import os
    import json
    from datetime import datetime

    print("DEBUG: Attempting to import dotenv...", flush=True)
    from dotenv import load_dotenv
    print("DEBUG: dotenv imported successfully.", flush=True)

    print("DEBUG: Attempting to import requests...", flush=True)
    import requests
    print("DEBUG: requests imported successfully.", flush=True)

    print("DEBUG: Attempting to import BeautifulSoup...", flush=True)
    from bs4 import BeautifulSoup
    print("DEBUG: BeautifulSoup imported successfully.", flush=True)

    print("DEBUG: Attempting to import db module...", flush=True)
    from db import ensure_schema, get_draws as db_get_draws, upsert_draw, get_latest_draw
    print("DEBUG: db module imported successfully.", flush=True)

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
        # Optional filters: year, limit
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

        # Try DB first
        draws = db_get_draws(limit=limit, year=year)
        if draws:
            # Normalize date for JSON
            normalized = []
            for d in draws:
                nd = dict(d)
                if isinstance(nd.get('draw_date'), (datetime,)):
                    nd['draw_date'] = nd['draw_date'].strftime('%Y-%m-%d')
                elif nd.get('draw_date') and hasattr(nd.get('draw_date'), 'isoformat'):
                    nd['draw_date'] = nd['draw_date'].isoformat()
                normalized.append(nd)
            return jsonify({"data": normalized, "count": len(normalized)})

        # Fallback to mock if DB empty or unavailable
        return jsonify({"data": MOCK_DRAWS, "count": len(MOCK_DRAWS)})

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

    # Helper to normalize payload from EURO_SOURCE_URL into our schema
    def normalize_euro_payload(payload):
        # If already in our format
        if all(k in payload for k in ["draw_date", "numbers", "stars"]):
            return {
                "draw_date": payload.get("draw_date"),
                "numbers": payload.get("numbers", []),
                "stars": payload.get("stars", []),
                "jackpot": payload.get("jackpot"),
                "winners": payload.get("winners", {})
            }
        # Try common alternative keys
        date = payload.get("date") or payload.get("drawDate")
        numbers = payload.get("mainNumbers") or payload.get("numbers") or []
        stars = payload.get("luckyStars") or payload.get("stars") or []
        jackpot = payload.get("jackpot") or payload.get("prize")
        winners = payload.get("winners") or {}
        if date and numbers and stars:
            # Normalize date to YYYY-MM-DD if possible
            try:
                # Attempt ISO parsing
                dt = datetime.fromisoformat(date.replace('Z',''))
                date = dt.strftime('%Y-%m-%d')
            except Exception:
                # Leave as-is
                pass
            return {
                "draw_date": date,
                "numbers": numbers,
                "stars": stars,
                "jackpot": jackpot,
                "winners": winners,
            }
        return None

    @app.route('/api/latest')
    def latest_draw():
        row = get_latest_draw()
        if row:
            d = dict(row)
            if isinstance(d.get('draw_date'), (datetime,)):
                d['draw_date'] = d['draw_date'].strftime('%Y-%m-%d')
            elif d.get('draw_date') and hasattr(d.get('draw_date'), 'isoformat'):
                d['draw_date'] = d['draw_date'].isoformat()
            return jsonify({"data": d})
        # Fallback to last mock
        if MOCK_DRAWS:
            return jsonify({"data": MOCK_DRAWS[-1]})
        return jsonify({"error": "No draws available"}), 404

    # Scrape latest draw from euromillones.com HTML
    def scrape_latest_draw(soup):
        logging.info("Starting to scrape latest draw.")
        # Find the latest result block
        result = soup.find('div', class_='latest-result')
        if not result:
            logging.error("Scraper error: 'latest-result' div not found.")
            return None

        # Date
        draw_date = None
        date_tag = result.find('h3')
        if date_tag:
            date_text = date_tag.get_text(strip=True)
            logging.info(f"Found date text: {date_text}")
            try:
                draw_date = datetime.strptime(date_text, '%A, %d %B %Y').strftime('%Y-%m-%d')
            except (ValueError, TypeError) as e:
                logging.error(f"Scraper error: Could not parse date '{date_text}'. Error: {e}")
                return None
        else:
            logging.error("Scraper error: 'h3' date tag not found.")
            return None

        if not draw_date:
            return None

        # Numbers and stars
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
                logging.warning(f"Scraper warning: Could not parse ball/star value '{txt}'. Skipping.")
                continue

        logging.info(f"Found numbers: {numbers} and stars: {stars}")
        if len(numbers) != 5 or len(stars) != 2:
            logging.error(f"Scraper error: Found {len(numbers)} numbers and {len(stars)} stars. Expected 5 and 2.")
            return None

        # Jackpot
        jackpot = None
        jackpot_div = result.find('div', class_='jackpot')
        if jackpot_div:
            jackpot_text = jackpot_div.get_text(strip=True).replace(',', '').replace('€', '')
            try:
                jackpot = int(float(jackpot_text))
                logging.info(f"Found jackpot: {jackpot}")
            except (ValueError, TypeError):
                jackpot = None
                logging.warning("Scraper warning: Could not parse jackpot value.")

        # Winners table (optional)
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
            logging.info(f"Found {len(winners)} winner tiers.")

        scraped_data = {
            "draw_date": draw_date,
            "numbers": numbers,
            "stars": stars,
            "jackpot": jackpot,
            "winners": winners
        }
        logging.info(f"Successfully scraped draw data for {draw_date}")
        return scraped_data

    @app.route('/api/sync', methods=['GET', 'POST'])
    def sync_latest():
        logging.info("Starting sync process.")
        # Ensure schema exists
        ensure_schema()
        logging.info("DB schema ensured.")

        source_url = os.getenv('EURO_SOURCE_URL')
        if not source_url:
            logging.error("EURO_SOURCE_URL not configured.")
            return jsonify({"error": "EURO_SOURCE_URL not configured"}), 500
        logging.info(f"Fetching data from {source_url}")

        try:
        resp = requests.get(source_url, timeout=10)
        resp.raise_for_status()
        # Use built-in HTML parser to avoid lxml dependency issues in serverless.
        soup = BeautifulSoup(resp.text, 'html.parser')
        logging.info("Successfully fetched and parsed source HTML.")
        except Exception as e:
            logging.error(f"Failed to fetch source: {e}")
            return jsonify({"error": f"Failed to fetch source: {e}"}), 502

        # Scrape latest draw
        logging.info("Attempting to scrape latest draw from HTML.")
        draw = scrape_latest_draw(soup)
        if not draw:
            logging.error("Scraping returned no data. Aborting sync.")
            return jsonify({"error": "Could not parse draw from page"}), 422
        logging.info(f"Successfully scraped draw for date: {draw.get('draw_date')}")

        logging.info("Attempting to upsert draw into database.")
        ok = upsert_draw(draw)
        if not ok:
            logging.error("Failed to persist draw to database.")
            return jsonify({"error": "Failed to persist draw"}), 500
        logging.info("Successfully persisted draw.")

        return jsonify({"status": "ok", "upserted": draw.get("draw_date")})

except Exception as e:
    logging.exception("Failed to initialize the Flask application.")
    # Re-raise the exception to ensure the process exits with an error code.
    raise
