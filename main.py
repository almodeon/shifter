import csv
from datetime import datetime, timedelta
from collections import defaultdict
import itertools
import random
import os

# Import the new classes
from shift_assigner import ShiftAssigner
from logger import Logger
from constraint_verifier import ConstraintVerifier
from export_manager import ExportManager
from config_manager import ConfigManager
from data_loader import DataLoader
from constraint_rules_engine import ConstraintRulesEngine, ConstraintSeverity

class HospitalScheduler:
    def __init__(self, people_data=None, night_dates=None, settings=None, config_file=None):
        self.people = people_data or {}
        self.schedule = {}
        self.shift_counts = {}
        self.required_night_dates = night_dates or []
        self.warnings = []  # New: track warnings when shifts cannot be assigned
        
        # Initialize configuration manager
        self.config = ConfigManager(config_file)
        
        # Override with provided settings if any
        if settings:
            self.config.update(settings)
        
        # Validate configuration
        is_valid, errors = self.config.validate_settings()
        if not is_valid:
            print("⚠️  Configuration validation errors:")
            for error in errors:
                print(f"   {error}")
            print("Using default values for invalid settings...")
        
        # Get settings from config manager
        self.settings = self.config.get_all_settings()
        
        # Initialize the logger
        self.logger = Logger(self.settings)
        
        self.logger.log('data_loading', 'info', f"Loaded {len(self.required_night_dates)} required night dates")
        self.logger.log('data_loading', 'info', f"Loaded {len(self.people)} people")

        # Create output directory if it doesn't exist
        self.output_dir = 'output'
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize the shift assigner
        self.shift_assigner = ShiftAssigner(self)
        
        # Initialize the constraint verifier
        self.constraint_verifier = ConstraintVerifier(self)
        
        # Initialize the export manager
        self.export_manager = ExportManager(self)
        
        # Initialize the data loader
        self.data_loader = DataLoader(self.logger)
    
    def _log(self, category, level, message):
        """Internal logging method - delegates to Logger class"""
        self.logger.log(category, level, message)

    def _should_log(self, category, level):
        """Check if we should log at this level for this category - delegates to Logger class"""
        return self.logger.should_log(category, level)
    
    def update_settings(self, new_settings):
        """Update scheduler settings and reinitialize components if needed"""
        self.config.update(new_settings)
        self.settings = self.config.get_all_settings()
        
        # Validate new settings
        is_valid, errors = self.config.validate_settings()
        if not is_valid:
            print("⚠️  Configuration validation errors after update:")
            for error in errors:
                print(f"   {error}")
        
        # Update logger settings
        self.logger.update_settings(self.settings['logging'])
    
    def save_config(self, config_file=None):
        """Save current configuration to file"""
        return self.config.save_to_file(config_file)
    
    def load_config(self, config_file):
        """Load configuration from file"""
        if self.config.load_from_file(config_file):
            self.settings = self.config.get_all_settings()
            self.logger.update_settings(self.settings['logging'])
            return True
        return False
    
    def apply_preset(self, preset_name):
        """Apply a configuration preset"""
        if self.config.apply_preset(preset_name):
            self.settings = self.config.get_all_settings()
            self.logger.update_settings(self.settings['logging'])
            print(f"✅ Applied preset: {preset_name}")
            return True
        else:
            print(f"❌ Unknown preset: {preset_name}")
            return False
    
    def print_config_summary(self):
        """Print configuration summary"""
        self.config.print_summary()
        
    @staticmethod
    def load_people_data_from_csv(csv_file, log_level='info'):
        """DEPRECATED: Use DataLoader.load_people_data() instead"""
        print("⚠️  Warning: load_people_data_from_csv is deprecated. Use DataLoader.load_people_data() for better format support.")
        loader = DataLoader()
        return loader.load_people_data(csv_file, log_level)

    @staticmethod
    def load_night_dates_from_csv(notti_file, log_level='info'):
        """DEPRECATED: Use DataLoader.load_night_dates() instead"""
        print("⚠️  Warning: load_night_dates_from_csv is deprecated. Use DataLoader.load_night_dates() for better format support.")
        loader = DataLoader()
        return loader.load_night_dates(notti_file, log_level)

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
        self.logger.log('multi_run_optimization', 'info', "=== MULTI-RUN OPTIMIZATION ===")
        self.logger.log('multi_run_optimization', 'info', f"Running up to {self.settings['multi_run']['max_runs']} attempts to find the best schedule...")
        
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
            self.logger.log('multi_run_optimization', 'debug', f"\nRun {run_id + 1}/{self.settings['multi_run']['max_runs']}...")
            
            try:
                # Reset scheduler state for each run
                self.schedule = {}
                self.shift_counts = {}
                self.warnings = []
                
                # Reinitialize the shift assigner for each run
                self.shift_assigner = ShiftAssigner(self)
                
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
                
                self.logger.log('multi_run_optimization', 'debug', f"  Result: {passed_count}/{total_constraints} constraints passed, {warning_count} warnings, {hour_difference}h difference")
                
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
                    self.logger.log('multi_run_optimization', 'info', f"  🎯 New best result!")
                
                # Early termination if perfect solution found
                if passed_count >= self.settings['multi_run']['target_passes']:
                    self.logger.log('multi_run_optimization', 'info', f"  ✅ Target of {self.settings['multi_run']['target_passes']} passed constraints reached!")
                    break
                
            except Exception as e:
                self.logger.log('multi_run_optimization', 'error', f"  ❌ Run failed with exception: {e}")
                continue
        
        # Restore original randomization settings
        self.settings['randomize_people_order'] = original_randomize_people
        self.settings['randomize_priority_tiebreaking'] = original_randomize_priority
        
        self.logger.log('multi_run_optimization', 'info', f"\n=== MULTI-RUN RESULTS ===")
        self.logger.log('multi_run_optimization', 'info', f"Completed {len(all_runs)} runs")
        self.logger.log('multi_run_optimization', 'info', f"Best result: {best_passed_count}/{len(best_constraint_results) if best_constraint_results else 0} constraints passed")
        
        # Display ranking of all runs
        self.logger.log('multi_run_optimization', 'info', f"\n=== RANKING OF ALL RUNS ===")
        
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
            self.logger.log('multi_run_optimization', 'info', f"\n=== USING BEST RESULT (Run {sorted_runs[0]['run_id'] + 1}) ===")
        
        return self.schedule
    
    def _export_multi_run_ranking(self, sorted_runs):
        """Export multi-run ranking to CSV - delegates to ExportManager"""
        self.export_manager.export_multi_run_ranking(sorted_runs)
    
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
        
        # Balanced assignment algorithm - now delegated to ShiftAssigner
        self.shift_assigner.assign_shifts_balanced(dates)
        
        return self.schedule
    
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

    def calculate_adjusted_afternoon_target(self, person_id):
        """Calculate adjusted afternoon shift target based on workload balancing - delegates to ShiftAssigner"""
        return self.shift_assigner.calculate_adjusted_afternoon_target(person_id)

    def print_schedule(self):
        """Print schedule to console"""
        if not self.logger.should_log('schedule_display', 'info'):
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
        """Export schedule to CSV file - delegates to ExportManager"""
        self.export_manager.export_schedule_to_csv(output_file)

    def export_staff_statistics_to_csv(self, start_date, end_date, output_file='staff_statistics.csv'):
        """Export detailed staff statistics to CSV file - delegates to ExportManager"""
        return self.export_manager.export_staff_statistics_to_csv(start_date, end_date, output_file)

    def export_all_formats(self, start_date, end_date, base_filename='schedule'):
        """Export schedule in all available formats - delegates to ExportManager"""
        self.export_manager.export_all(start_date, end_date, base_filename)

    def print_summary(self, start_date, end_date):
        """Print summary statistics for each person in table format"""
        if not self.logger.should_log('summary_statistics', 'info'):
            return
            
        print("\n=== SUMMARY STATISTICS ===\n")
        print(f"Required night dates: {self.required_night_dates}")
        print(f"Night dates in scheduling period: {[d for d in self.required_night_dates if start_date <= d <= end_date]}")
        
        # Print workload balancing status
        if self.settings['workload_balancing']['enabled']:
            self.logger.log('summary_statistics', 'info', f"Workload balancing: ENABLED")
            self.logger.log('summary_statistics', 'debug', f"  Night burden coefficient: {self.settings['workload_balancing']['night_burden_coefficient']}")
            self.logger.log('summary_statistics', 'debug', f"  Weekend burden coefficient: {self.settings['workload_balancing']['weekend_burden_coefficient']}")
            self.logger.log('summary_statistics', 'debug', f"  Max afternoon compensation: {self.settings['workload_balancing']['max_afternoon_compensation']}")
            
            # Debug: Print burden calculations for each person
            if self.logger.should_log('workload_balancing', 'debug'):
                self.logger.log('workload_balancing', 'debug', f"\nWORKLOAD BALANCING DEBUG:")
                all_burdens = []
                for pid in sorted(self.people.keys()):
                    night_count = self.shift_counts[pid]['night']
                    weekend_count = self.shift_counts[pid]['weekend_days']
                    burden = (night_count * self.settings['workload_balancing']['night_burden_coefficient'] + 
                             weekend_count * self.settings['workload_balancing']['weekend_burden_coefficient'])
                    all_burdens.append(burden)
                    adjusted_target = self.calculate_adjusted_afternoon_target(pid)
                    self.logger.log('workload_balancing', 'debug', f"  Person {pid}: Nights={night_count}, Weekends={weekend_count}, Burden={burden:.1f}, Afternoon Target={adjusted_target:.1f}")
                
                avg_burden = sum(all_burdens) / len(all_burdens) if all_burdens else 0
                self.logger.log('workload_balancing', 'debug', f"  Average burden: {avg_burden:.1f}")
        else:
            self.logger.log('summary_statistics', 'info', f"Workload balancing: DISABLED")
        
        # Print warnings if any
        if self.warnings:
            self.logger.log('summary_statistics', 'info', f"\n⚠️  SCHEDULING WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                self.logger.log('summary_statistics', 'info', f"   {warning}")
        
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
        """Comprehensive constraint verification - delegates to ConstraintVerifier class"""
        constraint_results = self.constraint_verifier.verify_constraints(start_date, end_date)
        # Store results for potential export
        self.last_constraint_results = constraint_results
        return constraint_results

def main():
    # Option 1: Use default configuration
    settings = None
    
    # Option 2: Use custom configuration inline (as before)
    # settings = {
    #     'min_morning_staff': 3,
    #     'max_afternoon_staff': 1,
    #     # ... other settings
    # }
    
    # Option 3: Use configuration file
    config_file = None  # or 'my_config.json'
    
    # Option 4: Use preset configuration
    preset = 'balanced'  # 'strict', 'balanced', 'optimized', 'debug'
    
    # Load CSV data using new DataLoader
    data_loader = DataLoader()
    
    # Check what formats are supported
    supported_formats = data_loader.get_supported_formats()
    dependencies = data_loader.check_dependencies()
    
    if 'error' not in ['error']:  # Only show if not in silent mode
        print(f"📁 Supported file formats: {', '.join(supported_formats)}")
        if not dependencies['excel_support']:
            print("💡 Tip: Install pandas and openpyxl for Excel (.xlsx) support: pip install pandas openpyxl")
    
    # Try to load data files (supports CSV, XLS, XLSX automatically)
    people_data = data_loader.load_people_data('desiderata.csv', log_level='error')
    
    # Try alternative formats if CSV not found
    if not people_data or len(people_data) < 2:  # Minimal validation
        for alt_file in ['desiderata.xlsx', 'desiderata.xls']:
            if os.path.exists(alt_file):
                print(f"📊 Found {alt_file}, loading...")
                people_data = data_loader.load_people_data(alt_file, log_level='error')
                break
    
    night_dates = data_loader.load_night_dates('notti.csv', log_level='error')
    
    # Try alternative formats for night dates
    if not night_dates:
        for alt_file in ['notti.xlsx', 'notti.xls']:
            if os.path.exists(alt_file):
                print(f"🌙 Found {alt_file}, loading...")
                night_dates = data_loader.load_night_dates(alt_file, log_level='error')
                break
    
    # Validate loaded data
    is_valid, validation_errors = data_loader.validate_data(people_data, night_dates)
    if not is_valid:
        print("⚠️  Data validation errors:")
        for error in validation_errors:
            print(f"   {error}")
    
    # Define scheduling period (example: October 2025)
    start_date = datetime(2025, 10, 1).date()
    end_date = datetime(2025, 10, 31).date()
    
    # Create scheduler instance
    scheduler = HospitalScheduler(
        people_data=people_data, 
        night_dates=night_dates, 
        settings=settings,
        config_file=config_file
    )
    
    # Apply preset if specified
    if preset:
        scheduler.apply_preset(preset)
    
    # Show configuration summary if settings display is enabled
    if scheduler.config.get('logging.settings_display') in ['info', 'debug']:
        scheduler.print_config_summary()
    
    # Generate schedule
    scheduler._log('data_loading', 'info', "Generating hospital schedule...")
    schedule = scheduler.generate_schedule(start_date, end_date)
    
    # Verify all constraints (only if not already in multi-run)
    if not scheduler.settings['multi_run']['enabled']:
        constraint_results = scheduler.verify_constraints(start_date, end_date)
    
    # Print to console
    scheduler.print_schedule()
    
    # Print summary statistics
    scheduler.print_summary(start_date, end_date)
    
    # Export results
    scheduler.export_to_csv('schedule_output.csv')
    scheduler.export_staff_statistics_to_csv(start_date, end_date, 'staff_statistics.csv')
    
    # Save configuration for next time (optional)
    # scheduler.save_config('last_used_config.json')
    
    scheduler._log('data_loading', 'info', "Schedule generation completed!")

if __name__ == "__main__":
    main()