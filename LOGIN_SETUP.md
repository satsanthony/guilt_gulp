# Login System Setup Guide

## Overview
The login system uses email-based authentication with a 6-digit security code sent to the user's email address. All data is encrypted in transit using HTTPS/TLS.

## Configuration

### Environment Variables
Add the following to your `.env` file:

```env
# Email Configuration (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM_NAME=Beer Finder

# Session Security
SESSION_SECRET_KEY=your-random-secret-key-here

# Development Mode (allows HTTP, shows dev code in response)
FLASK_ENV=development
```

### Gmail Setup (if using Gmail)
1. Enable 2-Factor Authentication on your Gmail account
2. Generate an App Password:
   - Go to Google Account settings
   - Security → 2-Step Verification → App passwords
   - Generate a password for "Mail"
   - Use this password as `SMTP_PASSWORD`

### Other Email Providers
- **Outlook/Hotmail**: `smtp-mail.outlook.com:587`
- **Yahoo**: `smtp.mail.yahoo.com:587`
- **Custom SMTP**: Use your provider's SMTP settings

## Security Features

1. **Encryption in Transit**: All form submissions use HTTPS (configure SSL certificate in production)
2. **Secure Sessions**: 
   - HttpOnly cookies (prevents JavaScript access)
   - Secure flag (HTTPS only in production)
   - SameSite protection (CSRF prevention)
3. **Code Expiration**: Security codes expire after 10 minutes
4. **Attempt Limiting**: Maximum 5 verification attempts per code
5. **Auto-cleanup**: Expired codes are automatically removed

## Development Mode

In development mode (`FLASK_ENV=development`):
- HTTP connections allowed (SESSION_COOKIE_SECURE=false)
- Security code shown in API response for testing
- Console logging enabled

## Production Deployment

1. Set `FLASK_ENV=production` or remove it
2. Use HTTPS (configure SSL certificate)
3. Set a strong `SESSION_SECRET_KEY` (use `secrets.token_hex(32)`)
4. Configure proper SMTP credentials
5. Consider using Redis for code storage instead of in-memory

## Usage

1. User visits `/login`
2. Enters email address
3. Receives 6-digit code via email
4. Enters code to authenticate
5. Redirected to main application

## API Endpoints

- `GET /login` - Login page
- `POST /api/login/send-code` - Send security code
- `POST /api/login/verify` - Verify code and authenticate
- `POST /api/logout` - Logout user
- `GET /api/auth/check` - Check authentication status

## Protected Routes

All main application routes are protected:
- `/` - Main search page
- `/selected` - Selected beers page
- `/api/search` - Search API
- `/api/selected` - Selected beers API

## Notes

- Security codes are stored in-memory (will be lost on server restart)
- For production, consider using Redis or a database for code storage
- Session data is stored server-side in Flask sessions
- Codes are automatically cleaned up on expiration










