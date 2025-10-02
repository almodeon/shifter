import csv
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import random
import os

class HospitalScheduler:
    def __init__(self, people_data=None, night_dates=None, settings=None):
        self.people = people_data or {}
        self.schedule = {}
        self.shift_counts = {}
        self.required_night_dates = night_dates or []
        self.warnings = []  # New: track warnings when shifts cannot be assigned
        
        # Default settings - all configurable
        self.settings = {
            'min_morning_staff': 3,
            'max_afternoon_staff': 1,
            'night_staff': 1,
            'min_weekly_hours': 34,
            'max_weekly_hours': 48,
            'morning_shift_hours': 6,
            'afternoon_shift_hours': 6,
            'night_shift_hours': 12,
            'sunday_mp_shift_hours': 12,
            'max_weekend_days_per_month': 2,
            'night_shifts_per_month': 1,
            'max_consecutive_days': 6,
            'min_rest_hours_between_shifts': 11,
            'min_continuous_rest_hours': 24,
            'weekend_morning_plus_afternoon': True,  # Saturday can have morning+afternoon
            'night_shifts_only_weekdays': False,
            'fill_up_to_minimum_hours': False, # New: whether to add extra shifts to reach minimum hours
            # Bias mitigation settings
            'randomize_people_order': False,  # Option 1: Randomize people order at start of scheduling
            'randomize_priority_tiebreaking': False,  # Option 5: Add randomization to priority scoring
            # Workload balancing settings
            'workload_balancing': {
                'enabled': False,  # Enable/disable workload balancing
                'night_burden_coefficient': 1.5,  # Each night reduces afternoon target by this much
                'weekend_burden_coefficient': 0.8,  # Each weekend day reduces afternoon target by this much
                'min_afternoon_shifts': 0,  # Never go below this many afternoon shifts per person
                'max_afternoon_compensation': 4  # Maximum afternoon shift reduction per person
            },
            # NEW: Multi-run optimization settings
            'multi_run': {
                'enabled': False,           # Enable multi-run optimization
                'max_runs': 100,           # Maximum number of runs to attempt
                'target_passes': 16,      # Stop early if this many constraints pass (max possible)
                'enable_randomization_for_multi_run': True  # Enable randomization during multi-run
            },
            # NEW: Afternoon shift balancing
            'afternoon_balancing': {
                'enabled': False,           # Enable afternoon shift weekly balancing
                'deprioritize_weekly_repeats': True,  # Lower priority for people with afternoon shifts this week
                'consider_weekly_hours': True,  # Consider weekly hours in afternoon shift priority
                'max_consecutive_afternoons': 1  # Maximum consecutive afternoon shifts allowed (0 = no limit)
            },
            # NEW: Logging/Output verbosity settings
            'logging': {
                'data_loading': 'info',              # silence, error, info, debug
                'settings_display': 'info',          # silence, error, info, debug  
                'multi_run_optimization': 'info',    # silence, error, info, debug
                'night_shift_assignment': 'info',    # silence, error, info, debug
                'workload_balancing': 'debug',       # silence, error, info, debug
                'weekend_shift_balancing': 'debug',  # silence, error, info, debug
                'fill_up_minimum_hours': 'info',     # silence, error, info, debug
                'shift_assignment_warnings': 'error', # silence, error, info, debug
                'constraint_verification': 'info',   # silence, error, info, debug
                'schedule_display': 'info',          # silence, error, info, debug
                'summary_statistics': 'info',       # silence, error, info, debug
                'export_notifications': 'info'      # silence, error, info, debug
            }
        }
        
        # Override with provided settings
        if settings:
            self.settings.update(settings)
        
        # Define logging levels
        self.LOG_LEVELS = {'silence': 0, 'error': 1, 'info': 2, 'debug': 3}
        
        self._log('data_loading', 'info', f"Loaded {len(self.required_night_dates)} required night dates")
        self._log('data_loading', 'info', f"Loaded {len(self.people)} people")

        # Create output directory if it doesn't exist
        self.output_dir = 'output'
        os.makedirs(self.output_dir, exist_ok=True)
        
    def _log(self, category, level, message):
        """Internal logging method that respects verbosity settings"""
        category_level = self.settings['logging'].get(category, 'info')
        if self.LOG_LEVELS[level] <= self.LOG_LEVELS[category_level]:
            print(message)

    def _should_log(self, category, level):
        """Check if we should log at this level for this category"""
        category_level = self.settings['logging'].get(category, 'info')
        return self.LOG_LEVELS[level] <= self.LOG_LEVELS[category_level]

    @staticmethod
    def load_people_data_from_csv(csv_file, log_level='info'):
        """Load person constraints from desiderata.csv file"""
        people_data = {}
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_file, 'r', encoding=encoding) as file:
                    reader = csv.DictReader(file)
                    
                    # Debug: print column names only if logging level allows
                    if log_level in ['info', 'debug']:
                        print(f"Columns found in {csv_file}: {reader.fieldnames}")
                    
                    for row in reader:
                        # Handle potential BOM or encoding issues in column names
                        person_key = None
                        for key in row.keys():
                            if 'persona' in key.lower() or key.strip() == 'Persona':
                                person_key = key
                                break
                        
                        if not person_key:
                            if log_level in ['error', 'info', 'debug']:
                                print(f"Available keys: {list(row.keys())}")
                            raise KeyError("Could not find 'Persona' column")
                        
                        person_id = row[person_key]
                        
                        # Parse night shift availability
                        night_available = True  # Default to available
                        notti_col = 'Notti'
                        if notti_col in row and row[notti_col].strip().upper() == 'N':
                            night_available = False
                        
                        # Parse forbidden shifts
                        forbidden_shifts = []
                        for i in range(1, 7):
                            shift_col = f'Turno vietato {i}'
                            if shift_col in row and row[shift_col].strip():
                                forbidden_shifts.append(HospitalScheduler.parse_shift(row[shift_col]))
                        
                        # Parse vacation dates (Ferie) and convert to forbidden shifts
                        ferie_col = 'Ferie'
                        if ferie_col in row and row[ferie_col].strip():
                            vacation_shifts = HospitalScheduler.parse_vacation_dates(row[ferie_col])
                            forbidden_shifts.extend(vacation_shifts)
                            if log_level in ['info', 'debug']:
                                print(f"Person {person_id}: Added {len(vacation_shifts)} vacation-based forbidden shifts")
                        
                        # Parse forbidden weekends
                        forbidden_weekends = []
                        for i in range(1, 4):
                            weekend_col = f'Weekend vietato {i}'
                            if weekend_col in row and row[weekend_col].strip():
                                forbidden_weekends.append(HospitalScheduler.parse_date(row[weekend_col]))
                        
                        people_data[person_id] = {
                            'forbidden_shifts': forbidden_shifts,
                            'forbidden_weekends': forbidden_weekends,
                            'night_available': night_available  # New: night shift availability
                        }
                        
                        if log_level in ['info', 'debug']:
                            print(f"Person {person_id}: Night shifts available = {night_available}")
                
                break  # Successfully read with this encoding
            
            except (UnicodeDecodeError, KeyError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    if log_level in ['error', 'info', 'debug']:
                        print(f"Could not read {csv_file} with any encoding: {e}")
                    # Create minimal setup for testing
                    for i in range(1, 6):
                        people_data[str(i)] = {
                            'forbidden_shifts': [],
                            'forbidden_weekends': [],
                            'night_available': True  # Default for testing
                        }
                continue
        
        return people_data

    @staticmethod
    def load_night_dates_from_csv(notti_file, log_level='info'):
        """Load required night dates from notti.csv file"""
        night_dates = []
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(notti_file, 'r', encoding=encoding) as file:
                    content = file.read()
                    lines = content.strip().split('\n')
                    
                    if log_level in ['info', 'debug']:
                        print(f"Reading required night dates from {notti_file}...")
                    for line in lines:
                        date_str = line.strip()
                        # Skip header line or empty lines
                        if date_str and not ('notte' in date_str.lower() or 'richiesta' in date_str.lower()):
                            parsed_date = HospitalScheduler.parse_date(date_str)
                            if parsed_date:
                                night_dates.append(parsed_date)
                                if log_level in ['debug']:
                                    print(f"  Required night date: {parsed_date}")
                
                break  # Successfully read with this encoding
                
            except (UnicodeDecodeError, FileNotFoundError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    if log_level in ['error', 'info', 'debug']:
                        print(f"Could not read {notti_file}: {e}")
                        print("No required night dates loaded")
                continue
        
        return night_dates
    
    # ...existing code...

    def load_constraints(self):
        """Load person constraints from desiderata.csv and required night dates from notti.csv"""
        # Load people constraints from desiderata.csv
        self.load_people_constraints()
        
        # Load required night dates from notti.csv
        self.load_night_dates()
        
        print(f"Loaded {len(self.required_night_dates)} required night dates")
        print(f"Loaded {len(self.people)} people")
    
    def load_people_constraints(self):
        """Load person constraints from desiderata.csv"""
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(self.csv_file, 'r', encoding=encoding) as file:
                    reader = csv.DictReader(file)
                    
                    # Debug: print column names
                    print(f"Columns found in desiderata.csv: {reader.fieldnames}")
                    
                    for row in reader:
                        # Handle potential BOM or encoding issues in column names
                        person_key = None
                        for key in row.keys():
                            if 'persona' in key.lower() or key.strip() == 'Persona':
                                person_key = key
                                break
                        
                        if not person_key:
                            print(f"Available keys: {list(row.keys())}")
                            raise KeyError("Could not find 'Persona' column")
                        
                        person_id = row[person_key]
                        
                        # Parse night shift availability
                        night_available = True  # Default to available
                        notti_col = 'Notti'
                        if notti_col in row and row[notti_col].strip().upper() == 'N':
                            night_available = False
                        
                        # Parse forbidden shifts
                        forbidden_shifts = []
                        for i in range(1, 7):
                            shift_col = f'Turno vietato {i}'
                            if shift_col in row and row[shift_col].strip():
                                forbidden_shifts.append(self.parse_shift(row[shift_col]))
                        
                        # Parse vacation dates (Ferie) and convert to forbidden shifts
                        ferie_col = 'Ferie'
                        if ferie_col in row and row[ferie_col].strip():
                            vacation_shifts = self.parse_vacation_dates(row[ferie_col])
                            forbidden_shifts.extend(vacation_shifts)
                            print(f"Person {person_id}: Added {len(vacation_shifts)} vacation-based forbidden shifts")
                        
                        # Parse forbidden weekends
                        forbidden_weekends = []
                        for i in range(1, 4):
                            weekend_col = f'Weekend vietato {i}'
                            if weekend_col in row and row[weekend_col].strip():
                                forbidden_weekends.append(self.parse_date(row[weekend_col]))
                        
                        self.people[person_id] = {
                            'forbidden_shifts': forbidden_shifts,
                            'forbidden_weekends': forbidden_weekends,
                            'night_available': night_available  # New: night shift availability
                        }
                        
                        print(f"Person {person_id}: Night shifts available = {night_available}")
                
                break  # Successfully read with this encoding
            
            except (UnicodeDecodeError, KeyError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    print(f"Could not read desiderata.csv with any encoding: {e}")
                    # Create minimal setup for testing
                    for i in range(1, 6):
                        self.people[str(i)] = {
                            'forbidden_shifts': [],
                            'forbidden_weekends': [],
                            'night_available': True  # Default for testing
                        }
                continue
    
    def load_night_dates(self):
        """Load required night dates from notti.csv"""
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        notti_file = 'notti.csv'
        
        for encoding in encodings:
            try:
                with open(notti_file, 'r', encoding=encoding) as file:
                    content = file.read()
                    lines = content.strip().split('\n')
                    
                    print("Reading required night dates from notti.csv...")
                    for line in lines:
                        date_str = line.strip()
                        # Skip header line or empty lines
                        if date_str and not ('notte' in date_str.lower() or 'richiesta' in date_str.lower()):
                            parsed_date = self.parse_date(date_str)
                            if parsed_date:
                                self.required_night_dates.append(parsed_date)
                                print(f"  Required night date: {parsed_date}")
                
                break  # Successfully read with this encoding
                
            except (UnicodeDecodeError, FileNotFoundError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    print(f"Could not read notti.csv: {e}")
                    print("No required night dates loaded")
                continue

    @staticmethod
    def parse_shift(shift_str):
        """Parse shift string like '03/10/2025 PN' into date and shift types"""
        parts = shift_str.strip().split()
        if len(parts) != 2:
            return None
        
        date_str, shift_types = parts
        date = HospitalScheduler.parse_date(date_str)
        if not date:
            return None
        
        shifts = []
        for char in shift_types:
            if char == 'M':
                shifts.append('morning')
            elif char == 'P':
                shifts.append('afternoon')
            elif char == 'N':
                shifts.append('night')
        
        return {'date': date, 'shifts': shifts}
    
    @staticmethod  
    def parse_date(date_str):
        """Parse date string in DD/MM/YYYY format"""
        try:
            return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
        except:
            return None
    
    @staticmethod
    def parse_vacation_dates(vacation_str, log_level='info'):
        """Parse vacation dates string and convert to forbidden shifts"""
        """
        Vacation dates are treated as:
        1. MPN (all shifts) forbidden on vacation days
        2. Night shifts forbidden on the day BEFORE vacation (since nights extend past midnight)
        """
        forbidden_shifts = []
        
        # Split by comma and parse each date
        date_strings = [d.strip() for d in vacation_str.split(',') if d.strip()]
        
        for date_str in date_strings:
            vacation_date = HospitalScheduler.parse_date(date_str)
            if vacation_date:
                # 1. Forbid all shifts (MPN) on the vacation day itself
                forbidden_shifts.append({
                    'date': vacation_date,
                    'shifts': ['morning', 'afternoon', 'night']
                })
                
                # 2. Forbid night shift on the day BEFORE vacation
                # (since night shift extends past midnight into vacation)
                day_before = vacation_date - timedelta(days=1)
                forbidden_shifts.append({
                    'date': day_before,
                    'shifts': ['night']
                })
                
                if log_level in ['debug']:
                    print(f"  Vacation {vacation_date}: blocked MPN on {vacation_date}, blocked N on {day_before}")
        
        return forbidden_shifts

    def generate_schedule(self, start_date, end_date):
        """Generate schedule for the given date range with optional multi-run optimization"""
        if self.settings['multi_run']['enabled']:
            return self._generate_schedule_multi_run(start_date, end_date)
        else:
            return self._generate_schedule_single(start_date, end_date)
    
    def _generate_schedule_multi_run(self, start_date, end_date):
        """Generate schedule using multi-run optimization"""
        self._log('multi_run_optimization', 'info', "=== MULTI-RUN OPTIMIZATION ===")
        self._log('multi_run_optimization', 'info', f"Running up to {self.settings['multi_run']['max_runs']} attempts to find the best schedule...")
        
        best_schedule = None
        best_constraint_results = None
        best_passed_count = -1
        best_hour_difference = float('inf')
        all_runs = []
        
        # Save original randomization settings
        original_randomize_people = self.settings.get('randomize_people_order', False)
        original_randomize_priority = self.settings.get('randomize_priority_tiebreaking', False)
        
        # Enable randomization for multi-run if specified
        if self.settings['multi_run']['enable_randomization_for_multi_run']:
            self.settings['randomize_people_order'] = True
            self.settings['randomize_priority_tiebreaking'] = True
        
        for run_id in range(self.settings['multi_run']['max_runs']):
            self._log('multi_run_optimization', 'debug', f"\nRun {run_id + 1}/{self.settings['multi_run']['max_runs']}...")
            
            try:
                # Reset scheduler state for each run
                self.schedule = {}
                self.shift_counts = {}
                self.warnings = []
                
                # Generate single schedule
                schedule = self._generate_schedule_single(start_date, end_date)
                
                # Verify constraints
                constraint_results = self.verify_constraints(start_date, end_date)
                
                # Count passed constraints
                passed_count = sum(1 for status in constraint_results.values() if status == 'PASS')
                total_constraints = len(constraint_results)
                warning_count = len(self.warnings)
                
                # Calculate hour difference between highest and lowest person
                person_hours = []
                all_dates = []
                current_date = start_date
                while current_date <= end_date:
                    all_dates.append(current_date)
                    current_date += timedelta(days=1)
                
                for person_id in self.people.keys():
                    total_hours = self.calculate_total_hours_for_person(person_id, all_dates)
                    person_hours.append(total_hours)
                
                hour_difference = max(person_hours) - min(person_hours) if person_hours else 0
                
                self._log('multi_run_optimization', 'debug', f"  Result: {passed_count}/{total_constraints} constraints passed, {warning_count} warnings, {hour_difference}h difference")
                
                # Store run results
                run_result = {
                    'run_id': run_id,
                    'schedule': schedule.copy(),
                    'constraint_results': constraint_results.copy(),
                    'passed_count': passed_count,
                    'total_constraints': total_constraints,
                    'warning_count': warning_count,
                    'hour_difference': hour_difference,
                    'warnings': self.warnings.copy(),
                    'shift_counts': self.shift_counts.copy(),
                    'success': passed_count == total_constraints and warning_count == 0
                }
                all_runs.append(run_result)
                
                # Check if this is the best so far (use hour difference as tiebreaker)
                is_better = False
                if passed_count > best_passed_count:
                    is_better = True
                elif passed_count == best_passed_count and best_passed_count >= 0:
                    # Same constraint passes - use hour difference as tiebreaker
                    if hour_difference < best_hour_difference:
                        is_better = True
                
                if is_better:
                    best_passed_count = passed_count
                    best_schedule = schedule.copy()
                    best_constraint_results = constraint_results.copy()
                    best_hour_difference = hour_difference
                    # Store the best run's state
                    best_warnings = self.warnings.copy()
                    best_shift_counts = self.shift_counts.copy()
                    self._log('multi_run_optimization', 'info', f"  🎯 New best result!")
                
                # Early termination if perfect solution found
                if passed_count >= self.settings['multi_run']['target_passes']:
                    self._log('multi_run_optimization', 'info', f"  ✅ Target of {self.settings['multi_run']['target_passes']} passed constraints reached!")
                    break
                
            except Exception as e:
                self._log('multi_run_optimization', 'error', f"  ❌ Run failed with exception: {e}")
                continue
        
        # Restore original randomization settings
        self.settings['randomize_people_order'] = original_randomize_people
        self.settings['randomize_priority_tiebreaking'] = original_randomize_priority
        
        self._log('multi_run_optimization', 'info', f"\n=== MULTI-RUN RESULTS ===")
        self._log('multi_run_optimization', 'info', f"Completed {len(all_runs)} runs")
        self._log('multi_run_optimization', 'info', f"Best result: {best_passed_count}/{len(best_constraint_results) if best_constraint_results else 0} constraints passed")
        
        # Display ranking of all runs
        self._log('multi_run_optimization', 'info', f"\n=== RANKING OF ALL RUNS ===")
        
        # Sort runs by passed count (descending), then by warning count (ascending), then by hour difference (ascending)
        sorted_runs = sorted(all_runs, key=lambda x: (-x['passed_count'], x['warning_count'], x['hour_difference']))
        
        # Short console display - just show passed constraints count
        if self._should_log('multi_run_optimization', 'info'):
            print(f"{'Rank':<4} {'Run':<4} {'Passed':<8} {'Warnings':<8} {'Hr_Diff':<8}")
            print("-" * 36)
            
            for rank, run in enumerate(sorted_runs, 1):
                print(f"{rank:<4} {run['run_id']+1:<4} {run['passed_count']:<8} {run['warning_count']:<8} {run['hour_difference']:<8}")

        # Export detailed ranking to CSV
        self._export_multi_run_ranking(sorted_runs)
        
        # Restore the best run's state to the scheduler
        if best_schedule:
            self.schedule = best_schedule
            self.warnings = best_warnings
            self.shift_counts = best_shift_counts
            self._log('multi_run_optimization', 'info', f"\n=== USING BEST RESULT (Run {sorted_runs[0]['run_id'] + 1}) ===")
        
        return self.schedule
    
    def _export_multi_run_ranking(self, sorted_runs):
        """Export multi-run ranking to CSV"""
        ranking_file = os.path.join(self.output_dir, 'multi_run_ranking.csv')
        
        # Define constraint order for CSV export
        constraint_order = [
            'forbidden_shifts', 'max_afternoon_staff', 'max_consecutive_days', 'monthly_night_limits',
            'morning_staff_weekdays', 'night_availability', 'night_coverage', 'night_rest_periods',
            'saturday_morning_staff', 'sunday_mp_staff', 'vacation_compliance', 'weekday_afternoon_coverage',
            'weekday_morning_coverage', 'weekend_coverage', 'weekend_days_per_month', 'weekly_hours'
        ]
        
        # Constraint name mapping for CSV headers
        constraint_short_names = {
            'forbidden_shifts': 'ForbShifts',
            'max_afternoon_staff': 'MaxAftnPers',
            'max_consecutive_days': 'ConsecDays',
            'monthly_night_limits': 'MonthNightLim',
            'morning_staff_weekdays': 'WDMornPers',
            'night_availability': 'NightAvl',
            'night_coverage': 'NightCover',
            'night_rest_periods': 'NightRest',
            'saturday_morning_staff': 'SatMornPers',
            'sunday_mp_staff': 'SunMPPers',
            'vacation_compliance': 'VacCompl',
            'weekday_afternoon_coverage': 'WDAftnCover',
            'weekday_morning_coverage': 'WDMornCover',
            'weekend_coverage': 'WkndCover',
            'weekend_days_per_month': 'WkndsMonth',
            'weekly_hours': 'WeekHrs'
        }
        
        # Export to CSV
        with open(ranking_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            
            # CSV Header
            header = ['Rank', 'Run_ID', 'Passed_Constraints', 'Total_Constraints', 'Warnings', 'Hour_Difference']
            for constraint in constraint_order:
                short_name = constraint_short_names.get(constraint, constraint[:9])
                header.append(short_name)
            writer.writerow(header)
            
            # CSV Data rows
            for rank, run in enumerate(sorted_runs, 1):
                row = [
                    rank,
                    run['run_id'] + 1,
                    run['passed_count'],
                    run['total_constraints'],
                    run['warning_count'],
                    run['hour_difference']
                ]
                
                # Add constraint results
                for constraint in constraint_order:
                    status = run['constraint_results'].get(constraint, 'N/A')
                    # Use * for FAIL, empty for PASS, ? for N/A
                    if status == 'FAIL':
                        row.append('*')
                    elif status == 'PASS':
                        row.append('')
                    else:
                        row.append('?')
                
                writer.writerow(row)
        
        self._log('export_notifications', 'info', f"Detailed ranking exported to: {ranking_file}")
    
    def _generate_schedule_single(self, start_date, end_date):
        """Generate a single schedule (original implementation)"""
        current_date = start_date
        dates = []
        
        while current_date <= end_date:
            dates.append(current_date)
            current_date += timedelta(days=1)
        
        # Initialize schedule structure
        for person_id in self.people.keys():
            self.schedule[person_id] = {}
            self.shift_counts[person_id] = {'morning': 0, 'afternoon': 0, 'night': 0, 'weekend_days': 0}
            for date in dates:
                self.schedule[person_id][date] = []
        
        # Balanced assignment algorithm
        self.assign_shifts_balanced(dates)
        
        return self.schedule
    
    def assign_shifts_balanced(self, dates):
        """Balanced shift assignment algorithm - never relax constraints"""
        people_list = list(self.people.keys())
        
        # NEW: Option 1 - Randomize people order at start of scheduling
        if self.settings.get('randomize_people_order', False):
            random.shuffle(people_list)
            self._log('night_shift_assignment', 'debug', f"Randomized people order: {people_list}")
        
        # First pass: assign night shifts to ensure everyone gets exactly the required amount
        self.assign_night_shifts_first(dates, people_list)
        
        # Pre-calculate afternoon targets after night shifts are assigned (for workload balancing)
        if self.settings['workload_balancing']['enabled']:
            self.afternoon_targets = {}
            for person_id in people_list:
                self.afternoon_targets[person_id] = self.calculate_adjusted_afternoon_target(person_id)
                self._log('workload_balancing', 'debug', f"Person {person_id} afternoon target: {self.afternoon_targets[person_id]:.1f}")
        
        # Second pass: assign morning and afternoon shifts
        for date in dates:
            is_weekend = date.weekday() >= 5  # Saturday = 5, Sunday = 6
            
            if is_weekend:
                if date.weekday() == 6:  # Sunday
                    # Sunday has only MP (morning+afternoon combined) shift
                    shifts_needed = ['mp']  # Special MP shift for Sunday
                else:  # Saturday
                    # Saturday has separate morning and afternoon shifts
                    shifts_needed = ['morning', 'afternoon']
            else:
                # Weekday shifts: morning, afternoon (night already assigned)
                shifts_needed = ['morning', 'afternoon']
            
            for shift in shifts_needed:
                if shift == 'morning':
                    if date.weekday() == 5:  # Saturday
                        required_people = self.settings.get('saturday_morning_staff', 2)
                    elif date.weekday() == 6:  # Sunday - no separate morning
                        continue
                    else:  # Weekday
                        required_people = self.settings['min_morning_staff']
                elif shift == 'afternoon':
                    if date.weekday() == 5:  # Saturday
                        required_people = self.settings.get('saturday_afternoon_staff', 1)
                    elif date.weekday() == 6:  # Sunday - no separate afternoon
                        continue
                    else:  # Weekday
                        required_people = self.settings['max_afternoon_staff']
                elif shift == 'mp':  # Sunday MP shift
                    required_people = self.settings.get('sunday_staff', 1)
                
                assigned_count = 0
                
                # Keep assigning until we meet requirements or run out of eligible people
                while assigned_count < required_people:
                    best_person = self.find_best_person_for_shift(people_list, date, shift)
                    if best_person:
                        self.schedule[best_person][date].append(shift)
                        
                        # Update shift counts
                        if shift == 'mp':
                            # MP counts as both morning and afternoon
                            self.shift_counts[best_person]['morning'] += 1
                            self.shift_counts[best_person]['afternoon'] += 1
                        else:
                            self.shift_counts[best_person][shift] += 1
                        
                        assigned_count += 1
                        
                        # Track weekend days - only for non-night shifts
                        if is_weekend and shift != 'night':
                            # Check if this person already worked this weekend day with non-night shifts
                            person_worked_this_weekend_day = False
                            for existing_shift in self.schedule[best_person][date]:
                                if existing_shift not in ['night', 'rest_after_night'] and existing_shift != shift:
                                    person_worked_this_weekend_day = True
                                    break
                            
                            # Only increment weekend_days counter if this is their first non-night shift on this weekend day
                            if not person_worked_this_weekend_day:
                                self.shift_counts[best_person]['weekend_days'] += 1
                    else:
                        # Add warning when shift cannot be assigned
                        warning = f"Could not assign {shift} shift on {date.strftime('%d/%m/%Y')} - no eligible staff (assigned {assigned_count}/{required_people})"
                        self.warnings.append(warning)
                        self._log('shift_assignment_warnings', 'error', f"Warning: {warning}")
                        break
        
        # Third pass: Add extra morning shifts to ensure everyone meets 34h minimum (if enabled)
        if self.settings['fill_up_to_minimum_hours']:
            self.ensure_minimum_hours(dates, people_list)
        else:
            self._log('fill_up_minimum_hours', 'info', "\nFill-up to minimum hours is disabled - skipping third pass")

    def ensure_minimum_hours(self, dates, people_list):
        """Add extra morning shifts on weekdays to ensure everyone meets minimum hours"""
        self._log('fill_up_minimum_hours', 'info', "\nThird pass: Ensuring minimum 34h per week for all people...")
        
        # Get all weekday dates (Monday-Friday) for potential extra morning shifts
        weekday_dates = [d for d in dates if d.weekday() < 5]
        
        for person_id in people_list:
            # Calculate total hours for this person across all weeks
            total_hours = 0
            for date in dates:
                for shift in self.schedule[person_id][date]:
                    if shift == 'morning':
                        total_hours += self.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        total_hours += self.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += self.settings['night_shift_hours']
            
            # Calculate average weekly hours
            total_weeks = len(dates) / 7
            avg_weekly_hours = total_hours / total_weeks if total_weeks > 0 else 0
            
            # If below minimum, add morning shifts
            if avg_weekly_hours < self.settings['min_weekly_hours']:
                hours_needed = (self.settings['min_weekly_hours'] * total_weeks) - total_hours
                shifts_needed = int(hours_needed / self.settings['morning_shift_hours']) + 1
                
                self._log('fill_up_minimum_hours', 'info', f"Person {person_id} has {avg_weekly_hours:.1f}h/week ({total_hours}h total), needs {shifts_needed} extra morning shifts")
                
                shifts_added = 0
                attempts = 0
                max_attempts = len(weekday_dates) * 3  # Allow multiple passes
                
                while shifts_added < shifts_needed and attempts < max_attempts:
                    for date in weekday_dates:
                        if shifts_added >= shifts_needed:
                            break
                        
                        attempts += 1
                        if attempts >= max_attempts:
                            break
                        
                        # Check if we can add a morning shift on this date
                        can_add, reason = self.can_add_extra_morning_shift(person_id, date)
                        if can_add:
                            self.schedule[person_id][date].append('morning')
                            self.shift_counts[person_id]['morning'] += 1
                            shifts_added += 1
                            self._log('fill_up_minimum_hours', 'debug', f"  Added morning shift for person {person_id} on {date}")
                            
                            # Recalculate hours after each addition
                            new_total_hours = 0
                            for check_date in dates:
                                for shift in self.schedule[person_id][check_date]:
                                    if shift == 'morning':
                                        new_total_hours += self.settings['morning_shift_hours']
                                    elif shift == 'afternoon':
                                        new_total_hours += self.settings['afternoon_shift_hours']
                                    elif shift == 'mp':
                                        new_total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                                    elif shift == 'night':
                                        new_total_hours += self.settings['night_shift_hours']
                            
                            new_avg_weekly = new_total_hours / total_weeks
                            if new_avg_weekly >= self.settings['min_weekly_hours']:
                                self._log('fill_up_minimum_hours', 'info', f"  Person {person_id} now has {new_avg_weekly:.1f}h/week - minimum reached!")
                                break
                        else:
                            # Only print detailed reasons for first few attempts to avoid spam
                            if attempts <= 10:
                                self._log('fill_up_minimum_hours', 'debug', f"  Person {person_id} cannot take morning shift on {date}: {reason}")
                
                if shifts_added < shifts_needed:
                    # Final check of actual hours
                    final_total_hours = 0
                    for check_date in dates:
                        for shift in self.schedule[person_id][check_date]:
                            if shift == 'morning':
                                final_total_hours += self.settings['morning_shift_hours']
                            elif shift == 'afternoon':
                                final_total_hours += self.settings['afternoon_shift_hours']
                            elif shift == 'mp':
                                final_total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                            elif shift == 'night':
                                final_total_hours += self.settings['night_shift_hours']
                    
                    final_avg_weekly = final_total_hours / total_weeks
                    self._log('fill_up_minimum_hours', 'error', f"  Warning: Person {person_id} added {shifts_added} of {shifts_needed} shifts, now has {final_avg_weekly:.1f}h/week")

    def can_add_extra_morning_shift(self, person_id, date):
        """Check if we can add an extra morning shift for this person on this date - returns (can_add, reason)"""
        # Check if this date is blocked for rest after night shift
        current_shifts = self.schedule[person_id].get(date, [])
        if 'rest_after_night' in current_shifts:
            return False, "blocked for rest after night shift"
        
        # Don't add if person already has morning shift
        if 'morning' in current_shifts:
            return False, "already has morning shift"
        
        # Don't add if person has night shift (conflicts)
        if 'night' in current_shifts:
            return False, "has night shift (conflict)"
        
        # Don't add if person has afternoon shift on weekday (only one shift per weekday)
        if date.weekday() < 5 and 'afternoon' in current_shifts:
            return False, "already has afternoon shift on weekday"
        
        # Check forbidden shifts
        person = self.people[person_id]
        for forbidden in person['forbidden_shifts']:
            if forbidden and forbidden['date'] == date and 'morning' in forbidden['shifts']:
                return False, "morning shift is forbidden on this date"
        
        # Enhanced night shift constraints
        prev_date = date - timedelta(days=1)
        next_date = date + timedelta(days=1)
        
        # Can't work the day after a night shift
        if prev_date in self.schedule[person_id]:
            prev_shifts = self.schedule[person_id].get(prev_date, [])
            if 'night' in prev_shifts:
                return False, "day after night shift"
        
        # # Can't work the day before a night shift
        # if next_date in self.schedule[person_id]:
        #     next_shifts = self.schedule[person_id].get(next_date, [])
        #     if 'night' in next_shifts:
        #         return False, "day before night shift"
        
        # Check weekly hour limits
        week_start = date - timedelta(days=date.weekday())
        weekly_hours = self.calculate_weekly_hours(person_id, week_start)
        projected_hours = weekly_hours + self.settings['morning_shift_hours']
        
        # Don't exceed 54h per week even for minimum requirement
        if projected_hours > 54:
            return False, f"would exceed 54h/week ({projected_hours:.1f}h)"
        
        # Check consecutive days constraint
        week_dates = []
        for i in range(7):
            week_dates.append(week_start + timedelta(days=i))
        
        days_worked_this_week = 0
        for week_date in week_dates:
            if week_date in self.schedule[person_id]:
                check_shifts = self.schedule[person_id][week_date]
                # Count as worked day only if has actual shifts (not rest days)
                if check_shifts and 'rest_after_night' not in check_shifts:
                    days_worked_this_week += 1
        
        # If adding this shift, would they work more than 6 days?
        if date in week_dates and not current_shifts:  # This would be a new working day
            if days_worked_this_week >= 6:
                return False, f"would exceed 6 consecutive days ({days_worked_this_week + 1} days)"
        
        return True, "OK"

    def assign_night_shifts_first(self, dates, people_list):
        """Assign night shifts only on required dates"""
        self._log('night_shift_assignment', 'info', f"Assigning night shifts only on required dates: {self.required_night_dates}")
        
        # Only assign night shifts on the specified dates
        available_night_dates = [d for d in self.required_night_dates if d in dates]
        
        if not available_night_dates:
            self._log('night_shift_assignment', 'error', "Warning: No required night dates found in the scheduling period")
            return
        
        self._log('night_shift_assignment', 'info', f"Available night dates in period: {available_night_dates}")
        
        # Filter people who are available for night shifts
        night_available_people = [p for p in people_list if self.people[p]['night_available']]
        
        if not night_available_people:
            self._log('night_shift_assignment', 'error', "ERROR: No people are available for night shifts!")
            for date in available_night_dates:
                warning = f"Could not assign night shift on {date.strftime('%d/%m/%Y')} - no staff available for night shifts"
                self.warnings.append(warning)
            return
        
        self._log('night_shift_assignment', 'info', f"People available for night shifts: {night_available_people}")
        
        # Group night dates by month to enforce monthly limits
        night_dates_by_month = defaultdict(list)
        for night_date in available_night_dates:
            month_key = (night_date.year, night_date.month)
            night_dates_by_month[month_key].append(night_date)
        
        # Initialize monthly night shift counters for each person
        monthly_night_counts = defaultdict(lambda: defaultdict(int))
        
        # Assign one person per required night date
        import random
        shuffled_people = night_available_people.copy()  # Only use night-available people
        random.shuffle(shuffled_people)
        
        person_index = 0
        for date in available_night_dates:
            # Find an available person for this night
            assigned = False
            attempts = 0
            month_key = (date.year, date.month)
            
            while not assigned and attempts < len(shuffled_people):
                person_id = shuffled_people[person_index % len(shuffled_people)]
                
                # Check if person has exceeded monthly night shift limit
                if monthly_night_counts[person_id][month_key] >= self.settings['night_shifts_per_month']:
                    person_index += 1
                    attempts += 1
                    continue
                
                if self.can_assign_shift(person_id, date, 'night'):
                    self.schedule[person_id][date].append('night')
                    self.shift_counts[person_id]['night'] += 1
                    monthly_night_counts[person_id][month_key] += 1
                    self._log('night_shift_assignment', 'debug', f"Assigned night shift to person {person_id} on {date} (month {month_key[1]}/{month_key[0]}: {monthly_night_counts[person_id][month_key]}/{self.settings['night_shifts_per_month']})")
                    
                    # CRITICAL: Block the next day completely for this person
                    next_date = date + timedelta(days=1)
                    if next_date <= dates[-1]:  # Only if next day is within scheduling period
                        # Clear any existing shifts on the next day
                        self.schedule[person_id][next_date] = ['rest_after_night']
                        self._log('night_shift_assignment', 'debug', f"  Blocked {next_date} for person {person_id} (rest after night shift)")
                    
                    assigned = True
                
                person_index += 1
                attempts += 1
            
            if not assigned:
                warning = f"Could not assign night shift on {date.strftime('%d/%m/%Y')} - no eligible night-available staff (monthly limits reached)"
                self.warnings.append(warning)
                self._log('shift_assignment_warnings', 'error', f"Warning: {warning}")

    def calculate_adjusted_afternoon_target(self, person_id):
        """Calculate adjusted afternoon shift target based on workload balancing"""
        if not self.settings['workload_balancing']['enabled']:
            return float('inf')  # No limit if balancing disabled
        
        # Calculate everyone's burden to find the average
        all_burdens = []
        for pid in self.people.keys():
            night_count = self.shift_counts[pid]['night']
            weekend_count = self.shift_counts[pid]['weekend_days']
            burden = (night_count * self.settings['workload_balancing']['night_burden_coefficient'] + 
                     weekend_count * self.settings['workload_balancing']['weekend_burden_coefficient'])
            all_burdens.append(burden)
        
        avg_burden = sum(all_burdens) / len(all_burdens) if all_burdens else 0
        
        # Calculate this person's burden
        night_count = self.shift_counts[person_id]['night']
        weekend_count = self.shift_counts[person_id]['weekend_days']
        person_burden = (night_count * self.settings['workload_balancing']['night_burden_coefficient'] + 
                        weekend_count * self.settings['workload_balancing']['weekend_burden_coefficient'])
        
        # Base afternoon target
        base_afternoons = 6  # Reasonable monthly target
        
        # Calculate compensation: people with LOWER burden get MORE afternoons
        burden_difference = avg_burden - person_burden  # Positive if person has lower burden than average
        
        compensation = min(
            abs(burden_difference),
            self.settings['workload_balancing']['max_afternoon_compensation']
        )
        
        if burden_difference > 0:
            # Person has lower burden than average → give MORE afternoon shifts
            adjusted_target = base_afternoons + compensation
        else:
            # Person has higher burden than average → give FEWER afternoon shifts
            adjusted_target = max(
                base_afternoons - compensation,
                self.settings['workload_balancing']['min_afternoon_shifts']
            )
        
        # Debug output
        self._log('workload_balancing', 'debug', f"DEBUG adjust_target: Person {person_id}: burden={person_burden:.1f}, avg={avg_burden:.1f}, diff={burden_difference:.1f}, comp={compensation:.1f}, target={adjusted_target:.1f}")
        
        return adjusted_target

    def find_best_person_for_shift(self, people_list, date, shift):
        """Find the best person for a shift based on current workload and constraints - no constraint relaxation"""
        eligible_people = []
        
        # NEW: Weekend shift balancing - exclude person(s) with maximum weekend shifts
        is_weekend_shift = date.weekday() >= 5 and shift in ['morning', 'afternoon', 'mp']
        excluded_people = set()
        
        if is_weekend_shift:
            # Find the maximum number of weekend shifts among all people
            weekend_counts = [self.shift_counts[pid]['weekend_days'] for pid in people_list]
            max_weekend_shifts = max(weekend_counts) if weekend_counts else 0
            
            # Exclude people who have the maximum number of weekend shifts
            for person_id in people_list:
                if self.shift_counts[person_id]['weekend_days'] == max_weekend_shifts and max_weekend_shifts > 0:
                    excluded_people.add(person_id)
            
            self._log('weekend_shift_balancing', 'debug', f"Weekend shift balancing on {date} ({shift}): max_weekend_shifts={max_weekend_shifts}, excluded={excluded_people}")
        
        for person_id in people_list:
            # Skip if person already has this shift type on this date
            if shift in self.schedule[person_id].get(date, []):
                continue
            
            # NEW: Skip if person is excluded due to maximum weekend shifts
            if person_id in excluded_people:
                continue
                
            if self.can_assign_shift(person_id, date, shift):
                # Check weekly hour constraints
                week_start = date - timedelta(days=date.weekday())
                weekly_hours = self.calculate_weekly_hours(person_id, week_start)
                
                # Estimate hours for this shift
                if shift == 'morning':
                    shift_hours = self.settings['morning_shift_hours']
                elif shift == 'afternoon':
                    shift_hours = self.settings['afternoon_shift_hours']
                elif shift == 'mp':  # Sunday MP shift
                    shift_hours = self.settings.get('sunday_mp_shift_hours', 12)
                else:  # night
                    shift_hours = self.settings['night_shift_hours']
                
                projected_hours = weekly_hours + shift_hours
                
                # Check if within limits - no relaxation
                if projected_hours <= self.settings['max_weekly_hours']:
                    # NEW: For afternoon shifts, check workload balancing
                    if shift == 'afternoon' and self.settings['workload_balancing']['enabled']:
                        current_afternoons = self.shift_counts[person_id]['afternoon']
                        adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                        
                        # Skip if person has reached their adjusted afternoon target
                        if current_afternoons >= adjusted_target:
                            continue
                    
                    eligible_people.append(person_id)
        
        # Return None if no eligible people - no constraint relaxation
        if not eligible_people:
            return None
        
        # Prioritize people who need more hours to reach minimum
        def priority_score(person_id):
            week_start = date - timedelta(days=date.weekday())
            weekly_hours = self.calculate_weekly_hours(person_id, week_start)
            
            # Higher priority for people below minimum hours (only if weekly hours consideration is enabled)
            if shift == 'afternoon' and self.settings['afternoon_balancing']['enabled']:
                if not self.settings['afternoon_balancing']['consider_weekly_hours']:
                    # Skip weekly hours consideration for afternoon shifts
                    if self.settings['workload_balancing']['enabled']:
                        current_afternoons = self.shift_counts[person_id]['afternoon']
                        adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                        # Prioritize those furthest below their adjusted target
                        base_priority = (0, current_afternoons - adjusted_target)
                    else:
                        # Use shift count only
                        base_priority = (0, self.shift_counts[person_id]['afternoon'])
                else:
                    # Use standard weekly hours logic
                    if weekly_hours < self.settings['min_weekly_hours']:
                        base_priority = (0, weekly_hours)
                    else:
                        if self.settings['workload_balancing']['enabled']:
                            current_afternoons = self.shift_counts[person_id]['afternoon']
                            adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                            base_priority = (1, current_afternoons - adjusted_target)
                        else:
                            base_priority = (1, self.shift_counts[person_id]['afternoon'])
            else:
                # Standard logic for non-afternoon shifts
                if weekly_hours < self.settings['min_weekly_hours']:
                    base_priority = (0, weekly_hours)
                else:
                    # NEW: For afternoon shifts, prioritize by adjusted target
                    if shift == 'afternoon' and self.settings['workload_balancing']['enabled']:
                        current_afternoons = self.shift_counts[person_id]['afternoon']
                        adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                        # Prioritize those furthest below their adjusted target
                        base_priority = (1, current_afternoons - adjusted_target)
                    else:
                        shift_key = shift if shift != 'mp' else 'morning'  # Use morning count for MP shifts
                        base_priority = (1, self.shift_counts[person_id][shift_key])
            
            # NEW: For afternoon shifts, add weekly balancing penalty
            if shift == 'afternoon' and self.settings['afternoon_balancing']['enabled']:
                if self.settings['afternoon_balancing']['deprioritize_weekly_repeats']:
                    # Count afternoon shifts this week for this person
                    week_start = date - timedelta(days=date.weekday())
                    week_end = week_start + timedelta(days=6)
                    
                    afternoon_shifts_this_week = 0
                    current_date = week_start
                    while current_date <= week_end and current_date <= date:  # Only count up to today
                        if current_date in self.schedule[person_id]:
                            if 'afternoon' in self.schedule[person_id][current_date]:
                                afternoon_shifts_this_week += 1
                            # MP shifts also count as afternoon
                            if 'mp' in self.schedule[person_id][current_date]:
                                afternoon_shifts_this_week += 1
                        current_date += timedelta(days=1)
                    
                    # Add penalty tier for people with afternoon shifts this week
                    if afternoon_shifts_this_week > 0:
                        base_priority = (base_priority[0] + 1, afternoon_shifts_this_week, base_priority[1])
            
            # NEW: Option 5 - Add randomization to tie-breaking
            if self.settings.get('randomize_priority_tiebreaking', False):
                return base_priority + (random.random(),)
            else:
                return base_priority
        
        return min(eligible_people, key=priority_score)
    
    def can_assign_shift(self, person_id, date, shift):
        """Check if person can be assigned to this shift"""
        person = self.people[person_id]
        
        # NEW: Check night shift availability
        if shift == 'night' and not person['night_available']:
            return False
        
        # NEW: Check consecutive afternoon shift limit
        if shift == 'afternoon' and self.settings['afternoon_balancing']['enabled']:
            max_consecutive = self.settings['afternoon_balancing']['max_consecutive_afternoons']
            if max_consecutive > 0:
                # Count consecutive afternoon shifts ending at the previous day
                consecutive_afternoons = 0
                check_date = date - timedelta(days=1)
                
                while check_date in self.schedule[person_id]:
                    day_shifts = self.schedule[person_id][check_date]
                    has_afternoon = 'afternoon' in day_shifts or 'mp' in day_shifts
                    
                    if has_afternoon:
                        consecutive_afternoons += 1
                        check_date -= timedelta(days=1)
                    else:
                        break
                
                # If adding this afternoon shift would exceed the limit, refuse
                if consecutive_afternoons >= max_consecutive:
                    return False
            
            # NEW: Check weekly afternoon shift limit
            max_weekly = self.settings['afternoon_balancing']['max_afternoons_per_week']
            if max_weekly > 0:
                # Count afternoon shifts in the current week
                week_start = date - timedelta(days=date.weekday())
                week_end = week_start + timedelta(days=6)
                
                afternoons_this_week = 0
                current_date = week_start
                while current_date <= week_end:
                    if current_date in self.schedule[person_id]:
                        day_shifts = self.schedule[person_id][current_date]
                        if 'afternoon' in day_shifts or 'mp' in day_shifts:
                            afternoons_this_week += 1
                    current_date += timedelta(days=1)
                
                # If adding this afternoon shift would exceed the weekly limit, refuse
                if afternoons_this_week >= max_weekly:
                    return False
        
        # Check forbidden shifts - for MP shift, check both M and P
        # This now includes vacation-generated forbidden shifts
        for forbidden in person['forbidden_shifts']:
            if forbidden and forbidden['date'] == date:
                if shift == 'mp':
                    # MP shift is forbidden if either M or P is forbidden
                    if 'morning' in forbidden['shifts'] or 'afternoon' in forbidden['shifts']:
                        return False
                elif shift in forbidden['shifts']:
                    return False
        
        # Check forbidden weekends
        if date.weekday() >= 5:  # Weekend
            for forbidden_weekend in person['forbidden_weekends']:
                if forbidden_weekend:
                    # Check if this weekend (Saturday or Sunday) is forbidden
                    weekend_start = date - timedelta(days=date.weekday() - 5)  # Get Saturday
                    if abs((weekend_start - forbidden_weekend).days) <= 1:
                        return False
        
        # STRICT CHECK: Never exceed max_weekend_days_per_month
        # But only count weekend days for non-night shifts
        if date.weekday() >= 5 and shift != 'night':  # This is a weekend day and not a night shift
            # Count weekend days already worked this month (excluding night-only days)
            month_key = (date.year, date.month)
            weekend_days_this_month = 0
            
            # Get all dates in this month
            month_start = date.replace(day=1)
            if month_key[1] == 12:
                next_month = month_start.replace(year=month_key[0] + 1, month=1)
            else:
                next_month = month_start.replace(month=month_key[1] + 1)
            month_end = next_month - timedelta(days=1)
            
            # Count existing weekend days worked this month (excluding night-only days)
            current_month_date = month_start
            while current_month_date <= month_end:
                if current_month_date.weekday() >= 5 and current_month_date in self.schedule[person_id]:
                    day_shifts = self.schedule[person_id][current_month_date]
                    # Only count as weekend day if has non-night shifts and not just rest
                    non_night_shifts = [s for s in day_shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:  # Has morning, afternoon, or mp shifts
                        weekend_days_this_month += 1
                current_month_date += timedelta(days=1)
            
            # If assigning this shift would exceed the monthly limit, refuse
            if weekend_days_this_month >= self.settings['max_weekend_days_per_month']:
                return False
        
        # Check if already has shifts or is blocked for rest
        current_shifts = self.schedule[person_id].get(date, [])
        if current_shifts:
            # If this date is blocked for rest after night shift, cannot assign anything
            if 'rest_after_night' in current_shifts:
                return False
            
            # If trying to assign night shift but already has other shifts
            if shift == 'night':
                return False
            
            # If already has night shift, cannot assign anything else
            if 'night' in current_shifts:
                return False
            
            # If trying to assign MP shift but already has other shifts
            if shift == 'mp' or 'mp' in current_shifts:
                return False
            
            # On weekdays, only one shift allowed (except night which is handled above)
            if date.weekday() < 5:
                return False
            
            # On Saturday, allow morning + afternoon based on settings
            if date.weekday() == 5 and not self.settings.get('weekend_morning_plus_afternoon', True):
                return False
        else:
            # If no current shifts, check if this date is blocked for rest after night shift
            if 'rest_after_night' in current_shifts:
                return False
        
        # Enhanced night shift constraints
        if shift == 'night':
            # Check day before: no shifts allowed
            prev_date = date - timedelta(days=1)
            if prev_date in self.schedule[person_id]:
                prev_shifts = self.schedule[person_id][prev_date]
                # If person worked the day before (and it's not just a rest day), cannot assign night
                if prev_shifts and 'rest_after_night' not in prev_shifts:
                    return False
            
            # Check day after: must be completely free
            next_date = date + timedelta(days=1)
            if next_date in self.schedule[person_id]:
                next_shifts = self.schedule[person_id][next_date]
                # If next day already has any shifts (other than being marked for rest), cannot assign night
                if next_shifts and 'rest_after_night' not in next_shifts:
                    return False
        else:
            # For non-night shifts, check if previous day had a night shift
            prev_date = date - timedelta(days=1)
            if prev_date in self.schedule[person_id]:
                prev_shifts = self.schedule[person_id][prev_date]
                if 'night' in prev_shifts:
                    return False
        
        # Check continuous rest requirement
        week_start = date - timedelta(days=date.weekday())
        days_worked_this_week = 0
        for i in range(7):
            check_date = week_start + timedelta(days=i)
            if check_date in self.schedule[person_id]:
                check_shifts = self.schedule[person_id][check_date]
                # Count as worked day only if has actual shifts (not rest days)
                if check_shifts and 'rest_after_night' not in check_shifts:
                    days_worked_this_week += 1
        
        if days_worked_this_week >= self.settings['max_consecutive_days']:
            return False
        
        return True
    
    def calculate_weekly_hours(self, person_id, week_start):
        """Calculate hours worked in a week starting from week_start"""
        hours = 0
        for i in range(7):
            date = week_start + timedelta(days=i)
            if date in self.schedule[person_id]:
                for shift in self.schedule[person_id][date]:
                    if shift == 'morning':
                        hours += self.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        hours += self.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        hours += self.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        hours += self.settings['night_shift_hours']
                    # Don't count 'rest_after_night' as hours
        return hours
    
    def calculate_total_hours_for_person(self, person_id, all_dates):
        """Calculate total hours for a person including vacation days"""
        total_hours = 0
        
        # Count shift hours
        for date in all_dates:
            for shift in self.schedule[person_id].get(date, []):
                if shift == 'morning':
                    total_hours += self.settings['morning_shift_hours']
                elif shift == 'afternoon':
                    total_hours += self.settings['afternoon_shift_hours']
                elif shift == 'mp':
                    total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                elif shift == 'night':
                    total_hours += self.settings['night_shift_hours']
        
        # Add vacation days (Ferie) - count as morning shift hours
        ferie_col = 'Ferie'
        if ferie_col in self.people[person_id]:
            vacation_shifts = self.people[person_id][ferie_col]
            for forbidden in vacation_shifts:
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates:
                        total_hours += self.settings['morning_shift_hours']
        
        return total_hours

    def print_schedule(self):
        """Print schedule to console"""
        if not self._should_log('schedule_display', 'info'):
            return
            
        print("\n=== HOSPITAL SCHEDULE ===\n")
        
        for person_id in sorted(self.people.keys()):
            print(f"Person {person_id}:")
            
            dates = sorted(self.schedule[person_id].keys())
            for date in dates:
                shifts = self.schedule[person_id][date]
                if shifts:
                    shift_str = ", ".join(shifts)
                    day_name = date.strftime("%A")
                    print(f"  {date.strftime('%d/%m/%Y')} ({day_name}): {shift_str}")
            
            # Calculate total hours including vacation days
            total_hours = self.calculate_total_hours_for_person(person_id, dates)
            
            counts = self.shift_counts[person_id]
            print(f"  Total hours: {total_hours}")
            print(f"  Shift distribution - M:{counts['morning']}, P:{counts['afternoon']}, N:{counts['night']}, Weekends:{counts['weekend_days']}")
            print()

    def export_to_csv(self, output_file):
        """Export schedule to CSV file (transposed format) with warnings column"""
        # Ensure the output file is in the output directory
        output_file = os.path.join(self.output_dir, os.path.basename(output_file))
        
        # Prepare data for CSV
        all_dates = set()
        
        for person_schedule in self.schedule.values():
            all_dates.update(person_schedule.keys())
        
        all_dates = sorted(list(all_dates))
        
        # Create header: Date, Day, Morning Count, Afternoon Count, Night Count, Warnings, then person columns
        people_ids = sorted(self.people.keys())
        header = ['Date', 'Day', 'Morning_Staff', 'Afternoon_Staff', 'Night_Staff', 'Warnings'] + people_ids
        
        rows = [header]
        
        # Add data for each date
        for date in all_dates:
            day_name = date.strftime('%A')
            
            # Count staff for each shift type on this date
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            
            # Prepare person data for this date
            person_data = []
            
            for person_id in people_ids:
                shifts = self.schedule[person_id].get(date, [])
                
                # Convert shifts to M, P, N, MP format
                shift_codes = []
                for shift in shifts:
                    if shift == 'morning':
                        shift_codes.append('M')
                        morning_count += 1
                    elif shift == 'afternoon':
                        shift_codes.append('P')
                        afternoon_count += 1
                    elif shift == 'mp':
                        shift_codes.append('MP')
                        morning_count += 1  # MP counts as both morning and afternoon staff
                        afternoon_count += 1
                    elif shift == 'night':
                        shift_codes.append('N')
                        night_count += 1
                
                shift_str = "".join(shift_codes) if shift_codes else ""
                person_data.append(shift_str)
            
            # Find warnings for this date
            date_warnings = [w for w in self.warnings if date.strftime('%d/%m/%Y') in w]
            warnings_str = "; ".join(date_warnings) if date_warnings else ""
            
            # Create row: Date, Day, Staff counts, Warnings, then person shifts
            row = [
                date.strftime('%d/%m/%Y'),
                day_name,
                morning_count,
                afternoon_count, 
                night_count,
                warnings_str
            ] + person_data
            
            rows.append(row)
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerows(rows)
        
        self._log('export_notifications', 'info', f"Schedule exported to {output_file}")

    def print_summary(self, start_date, end_date):
        """Print summary statistics for each person in table format"""
        if not self._should_log('summary_statistics', 'info'):
            return
            
        print("\n=== SUMMARY STATISTICS ===\n")
        print(f"Required night dates: {self.required_night_dates}")
        print(f"Night dates in scheduling period: {[d for d in self.required_night_dates if start_date <= d <= end_date]}")
        
        # Print workload balancing status
        if self.settings['workload_balancing']['enabled']:
            self._log('summary_statistics', 'info', f"Workload balancing: ENABLED")
            self._log('summary_statistics', 'debug', f"  Night burden coefficient: {self.settings['workload_balancing']['night_burden_coefficient']}")
            self._log('summary_statistics', 'debug', f"  Weekend burden coefficient: {self.settings['workload_balancing']['weekend_burden_coefficient']}")
            self._log('summary_statistics', 'debug', f"  Max afternoon compensation: {self.settings['workload_balancing']['max_afternoon_compensation']}")
            
            # Debug: Print burden calculations for each person
            if self._should_log('workload_balancing', 'debug'):
                self._log('workload_balancing', 'debug', f"\nWORKLOAD BALANCING DEBUG:")
                all_burdens = []
                for pid in sorted(self.people.keys()):
                    night_count = self.shift_counts[pid]['night']
                    weekend_count = self.shift_counts[pid]['weekend_days']
                    burden = (night_count * self.settings['workload_balancing']['night_burden_coefficient'] + 
                             weekend_count * self.settings['workload_balancing']['weekend_burden_coefficient'])
                    all_burdens.append(burden)
                    adjusted_target = self.calculate_adjusted_afternoon_target(pid)
                    self._log('workload_balancing', 'debug', f"  Person {pid}: Nights={night_count}, Weekends={weekend_count}, Burden={burden:.1f}, Afternoon Target={adjusted_target:.1f}")
                
                avg_burden = sum(all_burdens) / len(all_burdens) if all_burdens else 0
                self._log('workload_balancing', 'debug', f"  Average burden: {avg_burden:.1f}")
        else:
            self._log('summary_statistics', 'info', f"Workload balancing: DISABLED")
        
        # Print warnings if any
        if self.warnings:
            self._log('summary_statistics', 'info', f"\n⚠️  SCHEDULING WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                self._log('summary_statistics', 'info', f"   {warning}")
        
        print()
        
        total_days = (end_date - start_date).days + 1
        total_weeks = total_days / 7
        
        # Collect data for all people
        summary_data = []
        violations = []
        
        # Check monthly night shift violations for each person
        months_in_period = set((date.year, date.month) for date in [start_date + timedelta(days=i) for i in range(total_days)])
        
        for person_id in sorted(self.people.keys()):
            dates = sorted(self.schedule[person_id].keys())
            
            # Count shifts and calculate hours using correct method
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            mp_count = 0
            weekend_days = 0
            
            # Check monthly night shift violations
            for month_year in months_in_period:
                month_dates = [d for d in dates if (d.year, d.month) == month_year]
                night_shifts_this_month = 0
                
                for date in month_dates:
                    if 'night' in self.schedule[person_id][date]:
                        night_shifts_this_month += 1
                
                if night_shifts_this_month > self.settings['night_shifts_per_month']:
                    violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {night_shifts_this_month} night shifts (max {self.settings['night_shifts_per_month']})")
            
            # Count shifts properly from the schedule
            for date in dates:
                shifts = self.schedule[person_id][date]
                is_weekend = date.weekday() >= 5
                
                # Only count weekend days if they have non-night shifts
                if shifts and is_weekend:
                    non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:  # Has morning, afternoon, or mp shifts
                        weekend_days += 1
                
                # Count each shift type
                for shift in shifts:
                    if shift == 'morning':
                        morning_count += 1
                    elif shift == 'afternoon':
                        afternoon_count += 1
                    elif shift == 'mp':
                        mp_count += 1
                    elif shift == 'night':
                        night_count += 1
            
            # Calculate total hours including vacation days
            total_hours = self.calculate_total_hours_for_person(person_id, [start_date + timedelta(days=i) for i in range(total_days)])
            
            avg_hours_per_week = total_hours / total_weeks if total_weeks > 0 else 0
            
            # Check for other violations
            if avg_hours_per_week < self.settings['min_weekly_hours']:
                violations.append(f"Person {person_id}: {avg_hours_per_week:.1f}h/week (below {self.settings['min_weekly_hours']}h minimum)")
            elif avg_hours_per_week > self.settings['max_weekly_hours']:
                violations.append(f"Person {person_id}: {avg_hours_per_week:.1f}h/week (above {self.settings['max_weekly_hours']}h maximum)")
            
            # Display M+MP and P+MP totals for better understanding
            total_morning_shifts = morning_count + mp_count
            total_afternoon_shifts = afternoon_count + mp_count
            
            summary_data.append([
                person_id, 
                total_hours, 
                total_morning_shifts, 
                total_afternoon_shifts, 
                night_count, 
                weekend_days, 
                f"{avg_hours_per_week:.1f}"
            ])
        
        # Print table header
        print("┌────────┬─────────────┬─────┬─────┬─────┬──────────┬─────────────────────┐")
        print("│ Person │ Total Hours │  M  │  P  │  N  │ Weekends │ Avg Hours per Week  │")
        print("├────────┼─────────────┼─────┼─────┼─────┼──────────┼─────────────────────┤")
        
        # Print data rows
        for row in summary_data:
            person, total_h, m, p, n, weekends, avg = row
            print(f"│   {person:<4} │     {total_h:<7} │  {m:<2} │  {p:<2} │  {n:<2} │    {weekends:<5} │        {avg:<12} │")
        
        print("└────────┴─────────────┴─────┴─────┴─────┴──────────┴─────────────────────┘")
        
        # Print violations if any
        if violations:
            print("\n⚠️  CONSTRAINT VIOLATIONS:")
            for violation in violations:
                print(f"   {violation}")
        else:
            print("\n✅ All constraints satisfied!")
    
    def verify_constraints(self, start_date, end_date):
        """Comprehensive constraint verification with pass/not-pass for each constraint"""
        if not self._should_log('constraint_verification', 'info'):
            # Silent mode - just return results without printing
            return self._verify_constraints_silent(start_date, end_date)
            
        self._log('constraint_verification', 'info', "\n" + "="*80)
        self._log('constraint_verification', 'info', "CONSTRAINT VERIFICATION")
        self._log('constraint_verification', 'info', "="*80)
        
        all_dates = []
        current_date = start_date
        while current_date <= end_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)
        
        total_weeks = len(all_dates) / 7
        constraints_status = {}
        
        # 1. Check minimum morning staff (weekdays)
        self._log('constraint_verification', 'info', "\n1. MINIMUM MORNING STAFF (WEEKDAYS)")
        self._log('constraint_verification', 'info', "-" *   40)
        morning_violations = []
        for date in all_dates:
            if date.weekday() < 5:  # Weekday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings['min_morning_staff']
                if morning_staff < required:
                    morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if morning_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in morning_violations[:5]:  # Show first 5
                self._log('constraint_verification', 'debug', f"   {violation}")
            if len(morning_violations) > 5:
                self._log('constraint_verification', 'debug', f"   ... and {len(morning_violations) - 5} more violations")
            constraints_status['morning_staff_weekdays'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['morning_staff_weekdays'] = 'PASS'
        
        # 2. Check Saturday morning staff
        self._log('constraint_verification', 'info', "\n2. SATURDAY MORNING STAFF")
        self._log('constraint_verification', 'info', "-" * 40)
        saturday_morning_violations = []
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings.get('saturday_morning_staff', 2)
                if morning_staff < required:
                    saturday_morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if saturday_morning_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in saturday_morning_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['saturday_morning_staff'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['saturday_morning_staff'] = 'PASS'
        
        # 3. Check afternoon staff (max 1)
        self._log('constraint_verification', 'info', "\n3. MAXIMUM AFTERNOON STAFF")
        self._log('constraint_verification', 'info', "-" * 40)
        afternoon_violations = []
        for date in all_dates:
            if date.weekday() < 6:  # Not Sunday (Sunday has MP shift)
                afternoon_staff = sum(1 for person_id in self.people.keys() 
                                    if 'afternoon' in self.schedule[person_id].get(date, []))
                max_allowed = self.settings['max_afternoon_staff']
                if afternoon_staff > max_allowed:
                    afternoon_violations.append(f"{date}: {afternoon_staff} staff (max {max_allowed})")
        
        if afternoon_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in afternoon_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['max_afternoon_staff'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['max_afternoon_staff'] = 'PASS'
        
        # 4. Check Sunday MP staff
        self._log('constraint_verification', 'info', "\n4. SUNDAY MP STAFF")
        self._log('constraint_verification', 'info', "-" * 40)
        sunday_violations = []
        for date in all_dates:
            if date.weekday() == 6:  # Sunday
                mp_staff = sum(1 for person_id in self.people.keys() 
                             if 'mp' in self.schedule[person_id].get(date, []))
                required = self.settings.get('sunday_staff', 1)
                if mp_staff != required:
                    sunday_violations.append(f"{date}: {mp_staff} staff (need exactly {required})")
        
        if sunday_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in sunday_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['sunday_mp_staff'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['sunday_mp_staff'] = 'PASS'
        
        # 5. Check required night shifts coverage
        self._log('constraint_verification', 'info', "\n5. REQUIRED NIGHT SHIFTS COVERAGE")
        self._log('constraint_verification', 'info', "-" * 40)
        night_coverage_violations = []
        required_nights_in_period = [d for d in self.required_night_dates if start_date <= d <= end_date]
        
        for night_date in required_nights_in_period:
            night_staff = sum(1 for person_id in self.people.keys() 
                            if 'night' in self.schedule[person_id].get(night_date, []))
            if night_staff != 1:
                night_coverage_violations.append(f"{night_date}: {night_staff} staff (need exactly 1)")
        
        if night_coverage_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_coverage_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
           
            constraints_status['night_coverage'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['night_coverage'] = 'PASS'
        
        # 6. Check monthly night shift limits
        self._log('constraint_verification', 'info', "\n6. MONTHLY NIGHT SHIFT LIMITS")
        self._log('constraint_verification', 'info', "-" * 40)
        monthly_night_violations = []
        
        months_in_period = set((date.year, date.month) for date in all_dates)
        for person_id in self.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                night_shifts_this_month = 0
                
                for date in month_dates:
                    if 'night' in self.schedule[person_id].get(date, []):
                        night_shifts_this_month += 1
                
                if night_shifts_this_month > self.settings['night_shifts_per_month']:
                    monthly_night_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {night_shifts_this_month} night shifts (max {self.settings['night_shifts_per_month']})")
        
        if monthly_night_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in monthly_night_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['monthly_night_limits'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['monthly_night_limits'] = 'PASS'
        
        # 7. Check weekly hours (34-48h)
        self._log('constraint_verification', 'info', "\n7. WEEKLY HOURS (34-48h)")
        self._log('constraint_verification', 'info', "-" * 40)
        weekly_hours_violations = []
        
        for person_id in self.people.keys():
            total_hours = 0
            for date in all_dates:
                for shift in self.schedule[person_id][date]:
                    if shift == 'morning':
                        total_hours += self.settings['morning_shift_hours']
                   
                    elif shift == 'afternoon':
                        total_hours += self.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += self.settings['night_shift_hours']
            
            avg_weekly = total_hours / total_weeks if total_weeks > 0 else 0
            
            if avg_weekly < self.settings['min_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (below {self.settings['min_weekly_hours']}h)")
            elif avg_weekly > self.settings['max_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (above {self.settings['max_weekly_hours']}h)")
        
        if weekly_hours_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekly_hours_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['weekly_hours'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['weekly_hours'] = 'PASS'
        
        # 8. Check maximum consecutive days
        self._log('constraint_verification', 'info', "\n8. MAXIMUM CONSECUTIVE DAYS")
        self._log('constraint_verification', 'info', "-" * 40)
        consecutive_violations = []
        
        for person_id in self.people.keys():
            consecutive_days = 0
            max_consecutive = 0
            
            for date in all_dates:
                if self.schedule[person_id][date] and 'rest_after_night' not in self.schedule[person_id][date]:
                    consecutive_days += 1
                    max_consecutive = max(max_consecutive, consecutive_days)
                else:
                    consecutive_days = 0
            
            if max_consecutive > self.settings['max_consecutive_days']:
                consecutive_violations.append(f"Person {person_id}: {max_consecutive} consecutive days (max {self.settings['max_consecutive_days']})")
        
        if consecutive_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in consecutive_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['max_consecutive_days'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['max_consecutive_days'] = 'PASS'
        
        # 9. Check night shift rest periods
        self._log('constraint_verification', 'info', "\n9. NIGHT SHIFT REST PERIODS")
        self._log('constraint_verification', 'info', "-" * 40)
        night_rest_violations = []
        
        for person_id in self.people.keys():
            for date in all_dates:
                if 'night' in self.schedule[person_id].get(date, []):
                    # Check same day: no other shifts allowed on the night shift day
                   
                    same_day_shifts = [shift for shift in self.schedule[person_id].get(date, []) if shift != 'night' and shift != 'rest_after_night']
                    if same_day_shifts:
                        night_rest_violations.append(f"Person {person_id}: has {', '.join(same_day_shifts)} shift(s) on same day as night shift {date}")
                    
                    # Check day after: must be completely free (should be marked as rest)
                    next_date = date + timedelta(days=1)
                    if next_date in [d for d in all_dates]:
                        next_shifts = self.schedule[person_id].get(next_date, [])
                        # The day after should either be empty or contain only 'rest_after_night'
                        working_shifts = [shift for shift in next_shifts if shift != 'rest_after_night']
                        if working_shifts:
                            night_rest_violations.append(f"Person {person_id}: worked {next_date} after night on {date} (shifts: {', '.join(working_shifts)})")
        
        if night_rest_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_rest_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['night_rest_periods'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['night_rest_periods'] = 'PASS'
        
        # 10. Check weekend days per month
        self._log('constraint_verification', 'info', "\n10. WEEKEND DAYS PER MONTH")
        self._log('constraint_verification', 'info', "-" * 40)
        weekend_violations = []
        
        months_in_period = set((date.year, date.month) for date in all_dates)
        for person_id in self.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                weekend_days_worked = 0
                
                for date in month_dates:
                    if date.weekday() >= 5 and self.schedule[person_id].get(date, []):
                        day_shifts = self.schedule[person_id][date]
                        # Only count weekend days with non-night shifts (excluding rest days)
                        non_night_shifts = [s for s in day_shifts if s not in ['night', 'rest_after_night']]
                        if non_night_shifts:  # Has morning, afternoon, or mp shifts
                            weekend_days_worked += 1
                
                if weekend_days_worked > self.settings['max_weekend_days_per_month']:
                    weekend_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {weekend_days_worked} weekend days (max {self.settings['max_weekend_days_per_month']})")
        
        if weekend_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekend_violations[:5]:
                self._log('constraint_verification', 'debug', f"   {violation}")
            if len(weekend_violations) > 5:
                self._log('constraint_verification', 'debug', f"   ... and {len(weekend_violations) - 5} more violations")
            constraints_status['weekend_days_per_month'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['weekend_days_per_month'] = 'PASS'
        
        # 11. Check forbidden shifts compliance
        self._log('constraint_verification', 'info', "\n11. FORBIDDEN SHIFTS COMPLIANCE")
        self._log('constraint_verification', 'info', "-" * 40)
        forbidden_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                forbidden_violations.append(f"Person {person_id}: assigned forbidden {forbidden_shift} on {date}")
        
        if forbidden_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in forbidden_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['forbidden_shifts'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['forbidden_shifts'] = 'PASS'
        
        # 12. NEW: Check vacation (Ferie) compliance
        self._log('constraint_verification', 'info', "\n12. VACATION (FERIE) COMPLIANCE")
        self._log('constraint_verification', 'info', "-" * 40)
        vacation_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            # Check all forbidden shifts to identify vacation-related violations
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                # Check if this is a vacation-related constraint
                                # Vacation constraints have all MPN shifts forbidden on vacation days
                                # or N shifts forbidden on the day before vacation
                                if len(forbidden['shifts']) == 3 and all(s in forbidden['shifts'] for s in ['morning', 'afternoon', 'night']):
                                    # This is a vacation day (MPN all forbidden)
                                    vacation_violations.append(f"Person {person_id}: assigned {forbidden_shift} on vacation day {date}")
                                elif forbidden['shifts'] == ['night'] and len([f for f in person_data['forbidden_shifts'] 
                                    if f and f['date'] == date + timedelta(days=1) and len(f['shifts']) == 3]) > 0:
                                    # This is a night shift before vacation day
                                    vacation_violations.append(f"Person {person_id}: assigned night shift on {date} (night before vacation)")
        
        if vacation_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in vacation_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['vacation_compliance'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['vacation_compliance'] = 'PASS'
        
        # 13. Check night shift availability compliance (renumbered)
        self._log('constraint_verification', 'info', "\n13. NIGHT SHIFT AVAILABILITY COMPLIANCE")
        self._log('constraint_verification', 'info', "-" * 40)
        night_availability_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            if not person_data['night_available']:
                # Check if this person was assigned any night shifts
                for date in all_dates:
                    if 'night' in self.schedule[person_id].get(date, []):
                        night_availability_violations.append(f"Person {person_id}: assigned night shift on {date} but not available for nights")
        
        if night_availability_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_availability_violations:
                self._log('constraint_verification', 'debug', f"   {violation}")
            constraints_status['night_availability'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['night_availability'] = 'PASS'
        
        # 14. Check weekday morning shift coverage (renumbered)
        self._log('constraint_verification', 'info', "\n14. WEEKDAY MORNING SHIFT COVERAGE")
        self._log('constraint_verification', 'info', "-" * 40)
        weekday_morning_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings['min_morning_staff']
                if morning_staff < required:
                    weekday_morning_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {morning_staff}/{required} morning staff")
        
        if weekday_morning_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekday_morning_violations[:5]:
                self._log('constraint_verification', 'debug', f"   {violation}")
            if len(weekday_morning_violations) > 5:
                self._log('constraint_verification', 'debug', f"   ... and {len(weekday_morning_violations) - 5} more violations")
            constraints_status['weekday_morning_coverage'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['weekday_morning_coverage'] = 'PASS'
        
        # 15. Check weekday afternoon shift coverage (renumbered)
        self._log('constraint_verification', 'info', "\n15. WEEKDAY AFTERNOON SHIFT COVERAGE")
        self._log('constraint_verification', 'info', "-" * 40)
        weekday_afternoon_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                afternoon_staff = sum(1 for person_id in self.people.keys() 
                                    if 'afternoon' in self.schedule[person_id].get(date, []))
                required = self.settings['max_afternoon_staff']  # This acts as target coverage
                if afternoon_staff != required:
                    weekday_afternoon_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {afternoon_staff}/{required} afternoon staff")
        
        if weekday_afternoon_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekday_afternoon_violations[:5]:
                self._log('constraint_verification', 'debug', f"   {violation}")
            if len(weekday_afternoon_violations) > 5:
                self._log('constraint_verification', 'debug', f"   ... and {len(weekday_afternoon_violations) - 5} more violations")
            constraints_status['weekday_afternoon_coverage'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['weekday_afternoon_coverage'] = 'PASS'
        
        # 16. Check weekend shift coverage (renumbered)
        self._log('constraint_verification', 'info', "\n16. WEEKEND SHIFT COVERAGE")
        self._log('constraint_verification', 'info', "-" * 40)
        weekend_coverage_violations = []
        
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                saturday_morning = sum(1 for person_id in self.people.keys() 
                                     if 'morning' in self.schedule[person_id].get(date, []))
                saturday_afternoon = sum(1 for person_id in self.people.keys() 
                                       if 'afternoon' in self.schedule[person_id].get(date, []))
                
                required_morning = self.settings.get('saturday_morning_staff', 0)
                required_afternoon = self.settings.get('saturday_afternoon_staff', 0)
                
                if saturday_morning != required_morning:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_morning}/{required_morning} morning staff")
                if saturday_afternoon != required_afternoon:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_afternoon}/{required_afternoon} afternoon staff")
                    
            elif date.weekday() == 6:  # Sunday
                sunday_mp = sum(1 for person_id in self.people.keys() 
                              if 'mp' in self.schedule[person_id].get(date, []))
                required_mp = self.settings.get('sunday_staff', 1)
                
                if sunday_mp != required_mp:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Sunday): {sunday_mp}/{required_mp} MP staff")
        
        if weekend_coverage_violations:
            self._log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekend_coverage_violations[:5]:
                self._log('constraint_verification', 'debug', f"   {violation}")
            if len(weekend_coverage_violations) > 5:
                self._log('constraint_verification', 'debug', f"   ... and {len(weekend_coverage_violations) - 5} more violations")
            constraints_status['weekend_coverage'] = 'FAIL'
        else:
            self._log('constraint_verification', 'info', "✅ PASS")
            constraints_status['weekend_coverage'] = 'PASS'
        
        # Summary (updated to include new constraint)
        self._log('constraint_verification', 'info', "\n" + "="*80)
        self._log('constraint_verification', 'info', "CONSTRAINT VERIFICATION SUMMARY")
        self._log('constraint_verification', 'info', "="*80)
        
        passed = sum(1 for status in constraints_status.values() if status == 'PASS')
        total = len(constraints_status)
        
        if self._should_log('constraint_verification', 'info'):
            for i, (constraint, status) in enumerate(constraints_status.items(), 1):
                status_symbol = "✅" if status == 'PASS' else "❌"
                print(f"{i:2}. {constraint.replace('_', ' ').title():<30} {status_symbol} {status}")
        
        self._log('constraint_verification', 'info', f"\nOVERALL: {passed}/{total} constraints passed")
        
        if self.warnings:
            self._log('constraint_verification', 'info', f"⚠️  {len(self.warnings)} SCHEDULING WARNINGS")
        
        if passed == total and not self.warnings:
            self._log('constraint_verification', 'info', "🎉 ALL CONSTRAINTS SATISFIED WITH NO WARNINGS!")
        elif passed == total:
            self._log('constraint_verification', 'info', "✅ ALL CONSTRAINTS SATISFIED (with warnings)")
        else:
            self._log('constraint_verification', 'info', f"⚠️  {total - passed} CONSTRAINT(S) VIOLATED")
        
        self._log('constraint_verification', 'info', "="*80)
        
        return constraints_status
    
    def _verify_constraints_silent(self, start_date, end_date):
        """Silent constraint verification - returns results without printing"""
        all_dates = []
        current_date = start_date
        while current_date <= end_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)
        
        total_weeks = len(all_dates) / 7
        constraints_status = {}
        
        # 1. Check minimum morning staff (weekdays)
        morning_violations = []
        for date in all_dates:
            if date.weekday() < 5:  # Weekday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings['min_morning_staff']
                if morning_staff < required:
                    morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if morning_violations:
            constraints_status['morning_staff_weekdays'] = 'FAIL'
        else:
            constraints_status['morning_staff_weekdays'] = 'PASS'
        
        # 2. Check Saturday morning staff
        saturday_morning_violations = []
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings.get('saturday_morning_staff', 2)
                if morning_staff < required:
                    saturday_morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if saturday_morning_violations:
            constraints_status['saturday_morning_staff'] = 'FAIL'
        else:
            constraints_status['saturday_morning_staff'] = 'PASS'
        
        # 3. Check afternoon staff (max 1)
        afternoon_violations = []
        for date in all_dates:
            if date.weekday() < 6:  # Not Sunday (Sunday has MP shift)
                afternoon_staff = sum(1 for person_id in self.people.keys() 
                                    if 'afternoon' in self.schedule[person_id].get(date, []))
                max_allowed = self.settings['max_afternoon_staff']
                if afternoon_staff > max_allowed:
                    afternoon_violations.append(f"{date}: {afternoon_staff} staff (max {max_allowed})")
        
        if afternoon_violations:
            constraints_status['max_afternoon_staff'] = 'FAIL'
        else:
            constraints_status['max_afternoon_staff'] = 'PASS'
        
        # 4. Check Sunday MP staff
        sunday_violations = []
        for date in all_dates:
            if date.weekday() == 6:  # Sunday
                mp_staff = sum(1 for person_id in self.people.keys() 
                             if 'mp' in self.schedule[person_id].get(date, []))
                required = self.settings.get('sunday_staff', 1)
                if mp_staff != required:
                    sunday_violations.append(f"{date}: {mp_staff} staff (need exactly {required})")
        
        if sunday_violations:
            constraints_status['sunday_mp_staff'] = 'FAIL'
        else:
            constraints_status['sunday_mp_staff'] = 'PASS'
        
        # 5. Check required night shifts coverage
        night_coverage_violations = []
        required_nights_in_period = [d for d in self.required_night_dates if start_date <= d <= end_date]
        
        for night_date in required_nights_in_period:
            night_staff = sum(1 for person_id in self.people.keys() 
                            if 'night' in self.schedule[person_id].get(night_date, []))
            if night_staff != 1:
                night_coverage_violations.append(f"{night_date}: {night_staff} staff (need exactly 1)")
        
        if night_coverage_violations:
            constraints_status['night_coverage'] = 'FAIL'
        else:
            constraints_status['night_coverage'] = 'PASS'
        
        # 6. Check monthly night shift limits
        monthly_night_violations = []
        
        months_in_period = set((date.year, date.month) for date in all_dates)
        for person_id in self.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                night_shifts_this_month = 0
                
                for date in month_dates:
                    if 'night' in self.schedule[person_id].get(date, []):
                        night_shifts_this_month += 1
                
                if night_shifts_this_month > self.settings['night_shifts_per_month']:
                    monthly_night_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {night_shifts_this_month} night shifts (max {self.settings['night_shifts_per_month']})")
        
        if monthly_night_violations:
            constraints_status['monthly_night_limits'] = 'FAIL'
        else:
            constraints_status['monthly_night_limits'] = 'PASS'
        
        # 7. Check weekly hours (34-48h)
        weekly_hours_violations = []
        
        for person_id in self.people.keys():
            total_hours = 0
            for date in all_dates:
                for shift in self.schedule[person_id][date]:
                    if shift == 'morning':
                        total_hours += self.settings['morning_shift_hours']
                   
                    elif shift == 'afternoon':
                        total_hours += self.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += self.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += self.settings['night_shift_hours']
            
            avg_weekly = total_hours / total_weeks if total_weeks > 0 else 0
            
            if avg_weekly < self.settings['min_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (below {self.settings['min_weekly_hours']}h)")
            elif avg_weekly > self.settings['max_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (above {self.settings['max_weekly_hours']}h)")
        
        if weekly_hours_violations:
            constraints_status['weekly_hours'] = 'FAIL'
        else:
            constraints_status['weekly_hours'] = 'PASS'
        
        # 8. Check maximum consecutive days
        consecutive_violations = []
        
        for person_id in self.people.keys():
            consecutive_days = 0
            max_consecutive = 0
            
            for date in all_dates:
                if self.schedule[person_id][date] and 'rest_after_night' not in self.schedule[person_id][date]:
                    consecutive_days += 1
                    max_consecutive = max(max_consecutive, consecutive_days)
                else:
                    consecutive_days = 0
            
            if max_consecutive > self.settings['max_consecutive_days']:
                consecutive_violations.append(f"Person {person_id}: {max_consecutive} consecutive days (max {self.settings['max_consecutive_days']})")
        
        if consecutive_violations:
            constraints_status['max_consecutive_days'] = 'FAIL'
        else:
            constraints_status['max_consecutive_days'] = 'PASS'
        
        # 9. Check night shift rest periods
        night_rest_violations = []
        
        for person_id in self.people.keys():
            for date in all_dates:
                if 'night' in self.schedule[person_id].get(date, []):
                    # Check same day: no other shifts allowed on the night shift day
                   
                    same_day_shifts = [shift for shift in self.schedule[person_id].get(date, []) if shift != 'night' and shift != 'rest_after_night']
                    if same_day_shifts:
                        night_rest_violations.append(f"Person {person_id}: has {', '.join(same_day_shifts)} shift(s) on same day as night shift {date}")
                    
                    # Check day after: must be completely free (should be marked as rest)
                    next_date = date + timedelta(days=1)
                    if next_date in [d for d in all_dates]:
                        next_shifts = self.schedule[person_id].get(next_date, [])
                        # The day after should either be empty or contain only 'rest_after_night'
                        working_shifts = [shift for shift in next_shifts if shift != 'rest_after_night']
                        if working_shifts:
                            night_rest_violations.append(f"Person {person_id}: worked {next_date} after night on {date} (shifts: {', '.join(working_shifts)})")
        
        if night_rest_violations:
            constraints_status['night_rest_periods'] = 'FAIL'
        else:
            constraints_status['night_rest_periods'] = 'PASS'
        
        # 10. Check weekend days per month
        weekend_violations = []
        
        months_in_period = set((date.year, date.month) for date in all_dates)
        for person_id in self.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                weekend_days_worked = 0
                
                for date in month_dates:
                    if date.weekday() >= 5 and self.schedule[person_id].get(date, []):
                        day_shifts = self.schedule[person_id][date]
                        # Only count weekend days with non-night shifts (excluding rest days)
                        non_night_shifts = [s for s in day_shifts if s not in ['night', 'rest_after_night']]
                        if non_night_shifts:  # Has morning, afternoon, or mp shifts
                            weekend_days_worked += 1
                
                if weekend_days_worked > self.settings['max_weekend_days_per_month']:
                    weekend_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {weekend_days_worked} weekend days (max {self.settings['max_weekend_days_per_month']})")
        
        if weekend_violations:
            constraints_status['weekend_days_per_month'] = 'FAIL'
        else:
            constraints_status['weekend_days_per_month'] = 'PASS'
        
        # 11. Check forbidden shifts compliance
        forbidden_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                forbidden_violations.append(f"Person {person_id}: assigned forbidden {forbidden_shift} on {date}")
        
        if forbidden_violations:
            constraints_status['forbidden_shifts'] = 'FAIL'
        else:
            constraints_status['forbidden_shifts'] = 'PASS'
        
        # 12. NEW: Check vacation (Ferie) compliance
        vacation_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            # Check all forbidden shifts to identify vacation-related violations
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                # Check if this is a vacation-related constraint
                                # Vacation constraints have all MPN shifts forbidden on vacation days
                                # or N shifts forbidden on the day before vacation
                                if len(forbidden['shifts']) == 3 and all(s in forbidden['shifts'] for s in ['morning', 'afternoon', 'night']):
                                    # This is a vacation day (MPN all forbidden)
                                    vacation_violations.append(f"Person {person_id}: assigned {forbidden_shift} on vacation day {date}")
                                elif forbidden['shifts'] == ['night'] and len([f for f in person_data['forbidden_shifts'] 
                                    if f and f['date'] == date + timedelta(days=1) and len(f['shifts']) == 3]) > 0:
                                    # This is a night shift before vacation day
                                    vacation_violations.append(f"Person {person_id}: assigned night shift on {date} (night before vacation)")
        
        if vacation_violations:
            constraints_status['vacation_compliance'] = 'FAIL'
        else:
            constraints_status['vacation_compliance'] = 'PASS'
        
        # 13. Check night shift availability compliance (renumbered)
        night_availability_violations = []
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            if not person_data['night_available']:
                # Check if this person was assigned any night shifts
                for date in all_dates:
                    if 'night' in self.schedule[person_id].get(date, []):
                        night_availability_violations.append(f"Person {person_id}: assigned night shift on {date} but not available for nights")
        
        if night_availability_violations:
            constraints_status['night_availability'] = 'FAIL'
        else:
            constraints_status['night_availability'] = 'PASS'
        
        # 14. Check weekday morning shift coverage (renumbered)
        weekday_morning_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                morning_staff = sum(1 for person_id in self.people.keys() 
                                  if 'morning' in self.schedule[person_id].get(date, []))
                required = self.settings['min_morning_staff']
                if morning_staff < required:
                    weekday_morning_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {morning_staff}/{required} morning staff")
        
        if weekday_morning_violations:
            constraints_status['weekday_morning_coverage'] = 'FAIL'
        else:
            constraints_status['weekday_morning_coverage'] = 'PASS'
        
        # 15. Check weekday afternoon shift coverage (renumbered)
        weekday_afternoon_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                afternoon_staff = sum(1 for person_id in self.people.keys() 
                                    if 'afternoon' in self.schedule[person_id].get(date, []))
                required = self.settings['max_afternoon_staff']  # This acts as target coverage
                if afternoon_staff != required:
                    weekday_afternoon_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {afternoon_staff}/{required} afternoon staff")
        
        if weekday_afternoon_violations:
            constraints_status['weekday_afternoon_coverage'] = 'FAIL'
        else:
            constraints_status['weekday_afternoon_coverage'] = 'PASS'
        
        # 16. Check weekend shift coverage (renumbered)
        weekend_coverage_violations = []
        
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                saturday_morning = sum(1 for person_id in self.people.keys() 
                                     if 'morning' in self.schedule[person_id].get(date, []))
                saturday_afternoon = sum(1 for person_id in self.people.keys() 
                                       if 'afternoon' in self.schedule[person_id].get(date, []))
                
                required_morning = self.settings.get('saturday_morning_staff', 0)
                required_afternoon = self.settings.get('saturday_afternoon_staff', 0)
                
                if saturday_morning != required_morning:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_morning}/{required_morning} morning staff")
                if saturday_afternoon != required_afternoon:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_afternoon}/{required_afternoon} afternoon staff")
                    
            elif date.weekday() == 6:  # Sunday
                sunday_mp = sum(1 for person_id in self.people.keys() 
                              if 'mp' in self.schedule[person_id].get(date, []))
                required_mp = self.settings.get('sunday_staff', 1)
                
                if sunday_mp != required_mp:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Sunday): {sunday_mp}/{required_mp} MP staff")
        
        if weekend_coverage_violations:
            constraints_status['weekend_coverage'] = 'FAIL'
        else:
            constraints_status['weekend_coverage'] = 'PASS'
        
        return constraints_status

    def export_staff_statistics_to_csv(self, start_date, end_date, output_file='staff_statistics.csv'):
        """Export detailed staff statistics to CSV file"""
        # Ensure the output file is in the output directory
        output_file = os.path.join(self.output_dir, os.path.basename(output_file))
        
        total_days = (end_date - start_date).days + 1
        total_weeks = total_days / 7
        all_dates = [start_date + timedelta(days=i) for i in range(total_days)]
        
        # Prepare data for all people
        staff_data = []
        
        for person_id in sorted(self.people.keys()):
            # Count shifts from schedule
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            mp_count = 0
            weekend_days = 0
            shift_hours = 0
            
            # Count shifts properly from the schedule
            dates = sorted(self.schedule[person_id].keys())
            for date in dates:
                shifts = self.schedule[person_id][date]
                is_weekend = date.weekday() >= 5
                
                # Count weekend days if they have non-night shifts
                if shifts and is_weekend:
                    non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:
                        weekend_days += 1
                
                # Count each shift type and calculate hours from shifts
                for shift in shifts:
                    if shift == 'morning':
                        morning_count += 1
                        shift_hours += self.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        afternoon_count += 1
                        shift_hours += self.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        mp_count += 1
                        shift_hours += self.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        night_count += 1
                        shift_hours += self.settings['night_shift_hours']
            
            # Calculate vacation hours (weekday vacation days count as morning shift hours)
            vacation_hours = 0
            person_data = self.people[person_id]
            for forbidden in person_data['forbidden_shifts']:
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates and vacation_date.weekday() < 5:  # Monday-Friday only
                        vacation_hours += self.settings['morning_shift_hours']
            
            # Total hours including vacation
            total_hours = shift_hours + vacation_hours
            
            # Average hours per week
            avg_hours_per_week = total_hours / total_weeks if total_weeks > 0 else 0
            
            # Display M+MP and P+MP totals
            total_morning_shifts = morning_count + mp_count
            total_afternoon_shifts = afternoon_count + mp_count
            
            staff_data.append([
                person_id,
                total_hours,
                vacation_hours,
                total_morning_shifts,
                total_afternoon_shifts,
                night_count,
                weekend_days,
                f"{avg_hours_per_week:.1f}"
            ])
        
        # Write to CSV
        header = [
            'Person_ID',
            'Total_Hours',
            'Vacation_Hours',
            'Morning_Shifts',
            'Afternoon_Shifts',
            'Night_Shifts',
            'Weekend_Days',
            'Avg_Hours_Per_Week'
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(header)
            writer.writerows(staff_data)
        
        self._log('export_notifications', 'info', f"Staff statistics exported to {output_file}")
        return staff_data

def main():
    # Configurable settings - modify these as needed
    settings = {
        'min_morning_staff': 3,
        'max_afternoon_staff': 1,
        'night_staff': 1,
        'saturday_morning_staff': 0,
        'saturday_afternoon_staff': 0,
        'sunday_staff': 1,
        'min_weekly_hours': 34,
        'max_weekly_hours': 48,
        'morning_shift_hours': 6,
        'afternoon_shift_hours': 6,
        'night_shift_hours': 12,
        'sunday_mp_shift_hours': 12,
        'max_weekend_days_per_month': 2,
        'night_shifts_per_month': 1,
        'max_consecutive_days': 6,
        'min_rest_hours_between_shifts': 11,
        'min_continuous_rest_hours': 24,
        'weekend_morning_plus_afternoon': True,
        'night_shifts_only_weekdays': False,
        'fill_up_to_minimum_hours': True,  # Set to False to disable filling up to minimum hours
        # Bias mitigation settings
        'randomize_people_order': False,  # Set to True to enable Option 1: randomize people order
        'randomize_priority_tiebreaking': False,  # Set to True to enable Option 5: randomize tie-breaking
        # Workload balancing settings
        'workload_balancing': {
            'enabled': False,  # Enable workload balancing
            'night_burden_coefficient': 20,
            'weekend_burden_coefficient': 15,
            'min_afternoon_shifts': 0,
            'max_afternoon_compensation': 3
        },
        # Multi-run optimization settings
        'multi_run': {
            'enabled': False,           # Enable multi-run optimization
            'max_runs': 100,           # Maximum number of runs to attempt
            'target_passes': 16,      # Stop early if this many constraints pass (max possible)
            'enable_randomization_for_multi_run': True  # Enable randomization during multi-run
        },
        # NEW: Afternoon shift balancing settings
        'afternoon_balancing': {
            'enabled': True,           # Enable afternoon shift weekly balancing
            'deprioritize_weekly_repeats': True,  # Lower priority for people with afternoon shifts this week
            'consider_weekly_hours': False,  # Consider weekly hours in afternoon shift priority
            'max_consecutive_afternoons': 0,  # Maximum consecutive afternoon shifts allowed (0 = no limit)
            'max_afternoons_per_week': 0  # Maximum afternoon shifts per week per person (0 = no limit)
        },
        # NEW: Logging/Output verbosity settings
        'logging': {
            'data_loading': 'error',              # silence, error, info, debug
            'settings_display': 'error',          # silence, error, info, debug  
            'multi_run_optimization': 'error',    # silence, error, info, debug
            'night_shift_assignment': 'error',    # silence, error, info, debug
            'workload_balancing': 'error',     # silence, error, info, debug
            'weekend_shift_balancing': 'error', # silence, error, info, debug
            'fill_up_minimum_hours': 'error',     # silence, error, info, debug
            'shift_assignment_warnings': 'error', # silence, error, info, debug
            'constraint_verification': 'error',   # silence, error, info, debug
            'schedule_display': 'error',          # silence, error, info, debug
            'summary_statistics': 'info',       # silence, error, info, debug
            'export_notifications': 'info'      # silence, error, info, debug
        }
    }
    
    # Load CSV data with appropriate logging level
    data_loading_level = settings['logging']['data_loading']
    
    people_data = HospitalScheduler.load_people_data_from_csv('desiderata.csv', log_level=data_loading_level)
    night_dates = HospitalScheduler.load_night_dates_from_csv('notti.csv', log_level=data_loading_level)
    
    # Define scheduling period (example: October 2025)
    start_date = datetime(2025, 10, 1).date()
    end_date = datetime(2025, 10, 31).date()
    
    # Check settings display logging level
    settings_display_level = settings['logging']['settings_display']
    if settings_display_level in ['info', 'debug']:
        print("=== SCHEDULER SETTINGS ===")
        for key, value in settings.items():
            print(f"{key}: {value}")
        print()
    
    # Create scheduler instance
    scheduler = HospitalScheduler(people_data=people_data, night_dates=night_dates, settings=settings)
    
    scheduler._log('data_loading', 'info', "Generating hospital schedule...")
    schedule = scheduler.generate_schedule(start_date, end_date)
    
    # Verify all constraints (only if not already in multi-run)
    if not scheduler.settings['multi_run']['enabled']:
        constraint_results = scheduler.verify_constraints(start_date, end_date)
    
    # Print to console
    scheduler.print_schedule()
    
    # Print summary statistics
    scheduler.print_summary(start_date, end_date)
    
    # Export to CSV
    output_file = 'schedule_output.csv'  # This will be placed in output/ directory by the method
    scheduler.export_to_csv(output_file)
    
    # Export staff statistics
    scheduler.export_staff_statistics_to_csv(start_date, end_date, 'staff_statistics.csv')
    
    scheduler._log('data_loading', 'info', "Schedule generation completed!")

if __name__ == "__main__":
    main()