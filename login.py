"""Login system with email-based security code authentication."""

import os
import random
import smtplib
import secrets
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash
from langsmith import traceable

# Email configuration - load from environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
EMAIL_FROM_NAME = os.getenv('EMAIL_FROM_NAME', 'Beer Finder')

# In-memory storage for verification codes (in production, use Redis or database)
verification_codes = {}

# Session configuration
SESSION_SECRET_KEY = os.getenv('SESSION_SECRET_KEY', secrets.token_hex(32))

def init_login(app):
    """Initialize login system with Flask app."""
    app.secret_key = SESSION_SECRET_KEY
    app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    
    # In development, allow HTTP (set to False for production)
    if os.getenv('FLASK_ENV') == 'development':
        app.config['SESSION_COOKIE_SECURE'] = False
    
    register_login_routes(app)

def generate_security_code():
    """Generate a random 6-digit security code."""
    return str(random.randint(100000, 999999))

@traceable(name="send_security_code")
def send_security_code_email(email, code):
    """Send security code to user's email."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"Warning: Email not configured. Would send code {code} to {email}")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = f"{EMAIL_FROM_NAME} <{SMTP_EMAIL}>"
        msg['To'] = email
        msg['Subject'] = "Your Beer Finder Security Code"
        
        # Email body
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #3498db;">Beer Finder Security Code</h2>
                    <p>Your 6-digit security code is:</p>
                    <div style="background-color: #f8f9fa; padding: 20px; text-align: center; margin: 20px 0; border-radius: 8px;">
                        <h1 style="color: #2c3e50; margin: 0; font-size: 2.5rem; letter-spacing: 8px;">{code}</h1>
                    </div>
                    <p>This code will expire in 10 minutes.</p>
                    <p style="color: #7f8c8d; font-size: 0.9rem;">If you didn't request this code, please ignore this email.</p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()  # Enable encryption
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def require_auth(f):
    """Decorator to require authentication for routes."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def register_login_routes(app):
    """Register login-related routes."""
    
    @app.route('/login', methods=['GET'])
    def login_page():
        """Display login page."""
        if session.get('authenticated'):
            return redirect(url_for('index'))
        return render_template('login.html')
    
    @app.route('/api/login/send-code', methods=['POST'])
    def send_code():
        """Send security code to user's email."""
        try:
            data = request.get_json()
            email = data.get('email', '').strip().lower()
            
            if not email or '@' not in email:
                return jsonify({'error': 'Please enter a valid email address'}), 400
            
            # Generate security code
            code = generate_security_code()
            
            # Store code with expiration (10 minutes)
            verification_codes[email] = {
                'code': code,
                'expires_at': datetime.now() + timedelta(minutes=10),
                'attempts': 0
            }
            
            # Send email
            if send_security_code_email(email, code):
                return jsonify({'success': True, 'message': 'Security code sent to your email'})
            else:
                # In development, return the code for testing
                if os.getenv('FLASK_ENV') == 'development':
                    return jsonify({
                        'success': True, 
                        'message': f'Email not configured. Use code: {code}',
                        'dev_code': code
                    })
                return jsonify({'error': 'Failed to send email. Please try again.'}), 500
                
        except Exception as e:
            print(f"Error in send_code: {e}")
            return jsonify({'error': 'An error occurred. Please try again.'}), 500
    
    @app.route('/api/login/verify', methods=['POST'])

    @traceable(name="verify_security_code")
    def verify_code():
        """Verify security code and authenticate user."""
        try:
            data = request.get_json()
            email = data.get('email', '').strip().lower()
            code = data.get('code', '').strip()
            zipcode = data.get('zipcode', '').strip() 
            
            if not email or not code:
                return jsonify({'error': 'Email and code are required'}), 400
            
            # Check if code exists
            if email not in verification_codes:
                return jsonify({'error': 'No security code found. Please request a new code.'}), 400
            
            stored_data = verification_codes[email]
            
            # Check expiration
            if datetime.now() > stored_data['expires_at']:
                del verification_codes[email]
                return jsonify({'error': 'Security code has expired. Please request a new one.'}), 400
            
            # Check attempts (max 5 attempts)
            if stored_data['attempts'] >= 5:
                del verification_codes[email]
                return jsonify({'error': 'Too many failed attempts. Please request a new code.'}), 400
            
            # Verify code
            if code != stored_data['code']:
                stored_data['attempts'] += 1
                remaining = 5 - stored_data['attempts']
                return jsonify({
                    'error': f'Invalid code. {remaining} attempts remaining.',
                    'attempts_remaining': remaining
                }), 400
            
            # Code is correct - authenticate user
            session['authenticated'] = True
            session['email'] = email
            session['zipcode'] = zipcode
            session['login_time'] = datetime.now().isoformat()
            
            # Clean up verification code
            del verification_codes[email]
            
            return jsonify({'success': True, 'redirect': url_for('index')})
            
        except Exception as e:
            print(f"Error in verify_code: {e}")
            return jsonify({'error': 'An error occurred. Please try again.'}), 500
    @app.route('/api/logout', methods=['POST'])
    def logout():
        """Logout user and clear selected beers."""
        # Clear selected beers file
        selected_beers_file = 'selected_beers.json'
        if os.path.exists(selected_beers_file):
            try:
                os.remove(selected_beers_file)
            except Exception as e:
                print(f"Error removing selected beers file: {e}")
        
        # Clear the session
        session.clear()
        return jsonify({'success': True, 'redirect': url_for('login_page')})
    
    @app.route('/api/auth/check', methods=['GET'])
    def check_auth():
        """Check if user is authenticated."""
        if session.get('authenticated'):
            return jsonify({
                'authenticated': True,
                'email': session.get('email')
            })
        return jsonify({'authenticated': False}), 401
    

def cleanup_expired_codes():
    """Clean up expired verification codes (call periodically)."""
    now = datetime.now()
    expired_emails = [
        email for email, data in verification_codes.items()
        if now > data['expires_at']
    ]
    for email in expired_emails:
        del verification_codes[email]

