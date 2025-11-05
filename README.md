# Euromillions API - Vercel Deployment

This project is a Vercel deployment of the [Euromillions API](https://github.com/pedro-mealha/euromillions-api) by Pedro Mealha.

## Deployment Instructions

### Prerequisites

1. Install Vercel CLI:
```
npm install -g vercel
```

2. Login to Vercel:
```
vercel login
```

### Deployment Steps

1. Navigate to the project directory:
```
cd path/to/project
```

2. Deploy to Vercel:
```
vercel
```

3. Follow the prompts to complete the deployment.

4. For production deployment:
```
vercel --prod
```

### Environment Variables

Set up the following environment variables in your Vercel project:

- `DATABASE_URL`: PostgreSQL connection string
- `FLASK_ENV`: Set to "production" for production deployment
- `EURO_SOURCE_URL`: JSON endpoint for latest Euromillions draw (see below)

You can set these variables using the Vercel dashboard or CLI:
```
vercel env add DATABASE_URL
```

## Environment Variables (Private)

**Important**: Never commit your actual environment variables to GitHub. Set these in your Vercel project settings instead.

**Vercel Project Settings**:
1. Go to your Vercel project dashboard
2. Navigate to Settings > Environment Variables
3. Add these variables:
   - `DATABASE_URL`: Your PostgreSQL connection string
   - `FLASK_ENV`: Set to "production"

**Local Development**:
1. Copy `.env.example` to `.env` (this file is in `.gitignore`)
2. Add your actual database connection string to `.env`

## Security Note

This repository is public. Never commit:
- Actual database connection strings
- API keys or secrets
- Any sensitive configuration data

- `/` - API information
- `/api/draws` - Get all draws
- `/api/draws/{id}` - Get draw by ID
- `/api/draws/year/{year}` - Get draws by year
- `/api/stats` - Get statistics
- `/api/latest` - Get most recent stored draw (DB with mock fallback)
- `/api/sync` - Fetch latest draw from `EURO_SOURCE_URL` and upsert to DB

## Automatic Updates (Cron)

This project uses Vercel Cron to trigger updates on draw days (Tuesday and Friday):

```
"crons": [
  { "path": "/api/sync", "schedule": "0 21 * * 2,5" }
]
```

- Schedule is UTC; adjust as needed for publishing time.
- Cron sends a GET request to `/api/sync`.
- Ensure `EURO_SOURCE_URL` and `DATABASE_URL` are configured in Vercel.

### EURO_SOURCE_URL expected formats

The sync now **scrapes** the latest draw from the configured HTML page (`EURO_SOURCE_URL`) instead of expecting JSON.
Parsing supports the structure used by `https://www.euromillones.com/en/results/euromillions`:
- Draw date from the latest-result heading
- Numbers and stars from ball elements
- Jackpot and winner counts when present

If you prefer a JSON feed, replace the scraper (`scrape_latest_draw`) with your own fetch/normalize logic.

## Database Setup

This deployment requires a PostgreSQL database. You can use:
- Vercel Postgres
- Any PostgreSQL provider (Supabase, Railway, etc.)

Make sure to set the `DATABASE_URL` environment variable with your database connection string.
