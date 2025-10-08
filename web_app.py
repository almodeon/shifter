from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from main import HospitalScheduler
from data_loader import DataLoader
from config_manager import ConfigManager  # Move this import to the top

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
        
        # Last day of current month
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        default_end = f"{now.year}-{now.month:02d}-{last_day:02d}"
        
        # Next month code (commented out):
        # # Calculate next month
        # if now.month == 12:
        #     next_month = 1
        #     next_year = now.year + 1
        # else:
        #     next_month = now.month + 1
        #     next_year = now.year
        # 
        # # First day of next month
        # default_start = f"{next_year}-{next_month:02d}-01"
        # 
        # # Last day of next month
        # import calendar
        # last_day = calendar.monthrange(next_year, next_month)[1]
        # default_end = f"{next_year}-{next_month:02d}-{last_day:02d}"
        
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
        
        # Extract all data from request BEFORE starting thread
        request_data = {
            'files': {},
            'form': dict(request.form)
        }
        
        # Save uploaded files to request_data
        for key in request.files:
            file = request.files[key]
            if file and file.filename:
                request_data['files'][key] = {
                    'filename': file.filename,
                    'content': file.read()
                }
        
        # Start background job with extracted data
        thread = threading.Thread(target=process_schedule, args=(request_data,))
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
        
        files = request_data['files']
        form = request_data['form']
        
        # Check debug mode
        debug_mode = 'debug_mode_enabled' in form
        
        # Initialize DataLoader (like main.py)
        data_loader = DataLoader()
        
        # Check what formats are supported
        supported_formats = data_loader.get_supported_formats()
        dependencies = data_loader.check_dependencies()
        
        with job_lock:
            job_status['progress'] = 'Loading data files...'
        
        if debug_mode:
            # Get default file names directly from ConfigManager (like main.py)
            config = ConfigManager()
            
            people_file = config.get('data_files.people_data_file')
            night_file = config.get('data_files.night_dates_file')
            festivity_file = config.get('data_files.festivity_dates_file')
            
            # Load data files with fallback logic (like main.py)
            people_data = data_loader.load_people_data(people_file, log_level='error')
            
            # If the specified file doesn't exist, try alternative formats
            if not people_data or len(people_data) < 2:
                file_base = os.path.splitext(people_file)[0]  # Remove extension to get base name
                for ext in ['xlsx', 'xls', 'csv']:
                    alt_file = f'{file_base}.{ext}'
                    if os.path.exists(alt_file) and alt_file != people_file:  # Don't retry the same file
                        people_data = data_loader.load_people_data(alt_file, log_level='error')
                        if people_data and len(people_data) >= 2:
                            break
            
            night_dates = data_loader.load_night_dates(night_file, log_level='error')
            
            # If the specified file doesn't exist, try alternative formats
            if not night_dates:
                file_base = os.path.splitext(night_file)[0]
                for ext in ['xlsx', 'xls', 'csv']:
                    alt_file = f'{file_base}.{ext}'
                    if os.path.exists(alt_file) and alt_file != night_file:
                        night_dates = data_loader.load_night_dates(alt_file, log_level='error')
                        if night_dates:
                            break
            
            # Load festivity dates
            festivity_dates = data_loader.load_festivity_dates(festivity_file, log_level='error')
            
            # If the specified file doesn't exist, try alternative formats
            if not festivity_dates:
                file_base = os.path.splitext(festivity_file)[0]
                for ext in ['xlsx', 'xls', 'csv']:
                    alt_file = f'{file_base}.{ext}'
                    if os.path.exists(alt_file) and alt_file != festivity_file:
                        festivity_dates = data_loader.load_festivity_dates(alt_file, log_level='error')
                        if festivity_dates:
                            break
        else:
            # Save uploaded files and load from them (existing logic)
            people_file = None
            night_file = None
            festivity_file = None
            
            # Write files from extracted data
            if 'people_file' in files:
                people_file = os.path.join(temp_dir, 'people.' + files['people_file']['filename'].split('.')[-1])
                with open(people_file, 'wb') as f:
                    f.write(files['people_file']['content'])
            
            if 'night_file' in files:
                night_file = os.path.join(temp_dir, 'nights.' + files['night_file']['filename'].split('.')[-1])
                with open(night_file, 'wb') as f:
                    f.write(files['night_file']['content'])
            
            if 'festivity_file' in files:
                festivity_file = os.path.join(temp_dir, 'festivities.' + files['festivity_file']['filename'].split('.')[-1])
                with open(festivity_file, 'wb') as f:
                    f.write(files['festivity_file']['content'])
            
            # Load data using DataLoader
            people_data = data_loader.load_people_data(people_file, log_level='error') if people_file else {}
            night_dates = data_loader.load_night_dates(night_file, log_level='error') if night_file else []
            festivity_dates = data_loader.load_festivity_dates(festivity_file, log_level='error') if festivity_file else []
        
        # Create config manager (now available for both modes)
        config = ConfigManager()
        
        # Validate loaded data
        is_valid, validation_errors = data_loader.validate_data(people_data, night_dates, festivity_dates)
        if not is_valid:
            error_msg = "Data validation errors: " + "; ".join(validation_errors)
            raise Exception(error_msg)
        
        # Parse form data
        start_date = datetime.strptime(form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(form['end_date'], '%Y-%m-%d').date()
        
        # Build ONLY the settings overrides from the web form (let ConfigManager handle defaults)
        form_overrides = {
            # Staff requirements (all exposed in web form)
            'min_morning_staff': int(form.get('min_morning_staff', 3)),
            'max_afternoon_staff': int(form.get('max_afternoon_staff', 1)),
            'night_staff': int(form.get('night_staff', 1)),
            'saturday_morning_staff': int(form.get('saturday_morning_staff', 0)),
            'saturday_afternoon_staff': int(form.get('saturday_afternoon_staff', 0)),
            'saturday_mp_staff': int(form.get('saturday_mp_staff', 1)),
            'sunday_staff': int(form.get('sunday_staff', 1)),
            'festivity_staff': int(form.get('festivity_staff', 1)),
            
            # Work limits (all exposed in web form)
            'max_weekend_days_per_month': int(form.get('max_weekend_days_per_month', 2)),
            'night_shifts_per_month': int(form.get('night_shifts_per_month', 1)),
            
            # Multi-run settings (all exposed in web form)
            'multi_run': {
                'enabled': 'multi_run_enabled' in form,
                'max_runs': int(form.get('max_runs', 100)),
                'silence_output': True,
                'show_progress_bar': False,
                'person_scoring': {
                    'enabled': 'person_scoring_enabled' in form
                }
            },
            
            # Afternoon balancing (all exposed in web form)
            'afternoon_balancing': {
                'enabled': 'afternoon_balancing_enabled' in form,
                'deprioritize_weekly_repeats': 'deprioritize_weekly_repeats' in form,
                'consider_weekly_hours': 'consider_weekly_hours' in form,
                'enforce_strict_weekly_balance': 'enforce_strict_weekly_balance' in form,
                'consider_weekends_afternoons': 'consider_weekends_afternoons' in form,
                'give_precedence_to_afternoon_over_morning': 'give_precedence_to_afternoon_over_morning' in form,
                'prefer_not_in_internship': 'prefer_not_in_internship' in form
            },
            
            # Web-specific logging overrides (reduce noise in web interface)
            'logging': {
                'data_loading': 'error',
                'settings_display': 'error',
                'multi_run_optimization': 'info',
                'night_shift_assignment': 'error',
                'workload_balancing': 'error',
                'weekend_shift_balancing': 'error',
                'fill_up_minimum_hours': 'error',
                'shift_assignment_warnings': 'error',
                'shift_assignment_debug': 'error',
                'afternoon_balancing': 'error',
                'constraint_verification': 'error',
                'schedule_display': 'error',
                'summary_statistics': 'error',
                'export_notifications': 'info'
            }
        }
        
        with job_lock:
            job_status['progress'] = 'Creating scheduler...'
        
        # Create scheduler with PRE-LOADED data and let it use ConfigManager defaults + form overrides
        scheduler = HospitalScheduler(
            people_data=people_data,
            night_dates=night_dates,
            festivity_dates=festivity_dates,
            settings=form_overrides,  # Only pass the form overrides
            config=config
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
        
        # Verify constraints to get summary (only if not already in multi-run)
        if not scheduler.settings['multi_run']['enabled']:
            constraint_results = scheduler.verify_constraints(start_date, end_date)
        else:
            # For multi-run, use the last constraint results if available
            constraint_results = getattr(scheduler, 'last_constraint_results', {})
        
        passed_count = sum(1 for status in constraint_results.values() if status == 'PASS')
        total_constraints = len(constraint_results)
        failed_count = total_constraints - passed_count
        
        # Format constraint results for display
        constraint_details = []
        for constraint_name, status in constraint_results.items():
            icon = "✅" if status == 'PASS' else "❌"
            # Clean up constraint name for display
            display_name = constraint_name.replace('_', ' ').title()
            constraint_details.append({
                'name': display_name,
                'status': status,
                'icon': icon
            })
        
        # Sort constraints: failed first, then passed
        constraint_details.sort(key=lambda x: (x['status'] == 'PASS', x['name']))
        
        # Create results
        if failed_count == 0:
            summary = f"✅ All {total_constraints} constraints passed!"
        else:
            summary = f"⚠️ {passed_count}/{total_constraints} constraints passed ({failed_count} failed)"
        
        results = {
            'summary': summary,
            'constraint_details': constraint_details,
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
