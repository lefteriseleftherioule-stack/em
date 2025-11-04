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

## Database Setup

This deployment requires a PostgreSQL database. You can use:
- Vercel Postgres
- Any PostgreSQL provider (Supabase, Railway, etc.)

Make sure to set the `DATABASE_URL` environment variable with your database connection string.