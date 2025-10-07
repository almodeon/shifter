from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from main import HospitalScheduler
from data_loader import DataLoader

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Global variables to track job status
job_status = {'running': False, 'progress': '', 'error': None, 'results': None}
job_lock = threading.Lock()

@app.route('/', methods=['GET', 'POST'])
def index():
    global job_status
    
    if request.method == 'GET':
        # Set default dates (current month)
        now = datetime.now()
        default_start = f"{now.year}-{now.month:02d}-01"
        default_end = f"{now.year}-{now.month:02d}-{now.day:02d}"
        
        return render_template('index.html', 
                             default_start=default_start, 
                             default_end=default_end,
                             status=job_status)
    
    # POST request - handle form submission
    if job_status['running']:
        return redirect(url_for('index'))
    
    try:
        # Reset job status
        with job_lock:
            job_status = {'running': True, 'progress': 'Starting...', 'error': None, 'results': None}
        
        # Start background job
        thread = threading.Thread(target=process_schedule, args=(request,))
        thread.daemon = True
        thread.start()
        
        return redirect(url_for('index'))
        
    except Exception as e:
        with job_lock:
            job_status = {'running': False, 'progress': '', 'error': str(e), 'results': None}
        return redirect(url_for('index'))

def process_schedule(request_data):
    """Background function to process the scheduling request"""
    global job_status
    
    try:
        with job_lock:
            job_status['progress'] = 'Processing files...'
        
        # Create temporary directory for this job
        temp_dir = tempfile.mkdtemp()
        
        # Save uploaded files
        people_file = None
        night_file = None
        festivity_file = None
        
        files = request_data.files
        form = request_data.form
        
        if 'people_file' in files and files['people_file'].filename:
            people_file = os.path.join(temp_dir, 'people.' + files['people_file'].filename.split('.')[-1])
            files['people_file'].save(people_file)
        
        if 'night_file' in files and files['night_file'].filename:
            night_file = os.path.join(temp_dir, 'nights.' + files['night_file'].filename.split('.')[-1])
            files['night_file'].save(night_file)
        
        if 'festivity_file' in files and files['festivity_file'].filename:
            festivity_file = os.path.join(temp_dir, 'festivities.' + files['festivity_file'].filename.split('.')[-1])
            files['festivity_file'].save(festivity_file)
        
        with job_lock:
            job_status['progress'] = 'Loading data...'
        
        # Load data
        data_loader = DataLoader()
        people_data = data_loader.load_people_data(people_file) if people_file else {}
        night_dates = data_loader.load_night_dates(night_file) if night_file else []
        festivity_dates = data_loader.load_festivity_dates(festivity_file) if festivity_file else []
        
        # Parse form data
        start_date = datetime.strptime(form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(form['end_date'], '%Y-%m-%d').date()
        
        # Build settings from form with all the configurable parameters
        settings = {
            # Staff requirements
            'min_morning_staff': int(form.get('min_morning_staff', 3)),
            'max_afternoon_staff': int(form.get('max_afternoon_staff', 1)),
            'night_staff': int(form.get('night_staff', 1)),
            'saturday_morning_staff': int(form.get('saturday_morning_staff', 0)),
            'saturday_mp_staff': int(form.get('saturday_mp_staff', 1)),
            'sunday_staff': int(form.get('sunday_staff', 1)),
            'festivity_staff': int(form.get('festivity_staff', 1)),
            
            # Work limits
            'max_weekend_days_per_month': int(form.get('max_weekend_days_per_month', 2)),
            'night_shifts_per_month': int(form.get('night_shifts_per_month', 4)),
            
            # Multi-run settings
            'multi_run': {
                'enabled': 'multi_run_enabled' in form,
                'max_runs': int(form.get('max_runs', 100)),
                'target_fails': 0,
                'silence_output': True,
                'show_progress_bar': False,
                'person_scoring': {
                    'enabled': 'person_scoring_enabled' in form
                }
            },
            
            # Afternoon balancing
            'afternoon_balancing': {
                'enabled': 'afternoon_balancing_enabled' in form
            },
            
            # Keep other defaults
            'workload_balancing': {
                'enabled': False  # Can add to form if needed
            },
            'logging': {
                'data_loading': 'error',
                'multi_run_optimization': 'error',
                'summary_statistics': 'info',
                'export_notifications': 'info'
            }
        }
        
        with job_lock:
            job_status['progress'] = 'Creating scheduler...'
        
        # Create scheduler with main.py integration
        scheduler = HospitalScheduler(
            people_data=people_data,
            night_dates=night_dates,
            festivity_dates=festivity_dates,
            settings=settings
        )
        
        with job_lock:
            job_status['progress'] = 'Generating schedule...'
        
        # Generate schedule using main.py logic
        schedule = scheduler.generate_schedule(start_date, end_date)
        
        with job_lock:
            job_status['progress'] = 'Exporting results...'
        
        # Create output directory
        output_dir = 'output'
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate timestamp for unique filenames
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Export files using main.py methods
        schedule_file = f'schedule_{timestamp}.csv'
        stats_file = f'staff_statistics_{timestamp}.csv'
        
        scheduler.export_to_csv(os.path.join(output_dir, schedule_file), start_date, end_date)
        scheduler.export_staff_statistics_to_csv(start_date, end_date, os.path.join(output_dir, stats_file))
        
        # Verify constraints to get summary
        constraint_results = scheduler.verify_constraints(start_date, end_date)
        passed_count = sum(1 for status in constraint_results.values() if status == 'PASS')
        total_constraints = len(constraint_results)
        
        # Create resultsK@
        results = {
            'summary': f'Constraints: {passed_count}/{total_constraints} passed. Schedule covers {(end_date - start_date).days + 1} days.',
            'files': [
                {'name': schedule_file, 'display_name': 'Schedule (CSV)'},
                {'name': stats_file, 'display_name': 'Staff Statistics (CSV)'}
            ],
            'warnings': scheduler.warnings if scheduler.warnings else None
        }
        
        with job_lock:
            job_status = {'running': False, 'progress': '', 'error': None, 'results': results}
        
        # Cleanup temp files
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    except Exception as e:
        with job_lock:
            job_status = {'running': False, 'progress': '', 'error': str(e), 'results': None}

@app.route('/download/<filename>')
def download_file(filename):
    """Serve files from output directory"""
    try:
        file_path = os.path.join('output', filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return "File not found", 404
    except Exception as e:
        return f"Error downloading file: {str(e)}", 500

@app.route('/status')
def get_status():
    """API endpoint to get current job status"""
    return jsonify(job_status)

if __name__ == '__main__':
    # Create output directory
    os.makedirs('output', exist_ok=True)
    
    print("🌐 Starting Hospital Scheduler Web Interface...")
    print("📍 Open your browser to: http://localhost:5000")
    print("📁 Output files will be saved to: ./output/")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
