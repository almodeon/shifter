import csv
from datetime import datetime, timedelta
from collections import defaultdict
import random
import os
import json
import sys

# Import the new classes
from shift_assigner import ShiftAssigner
from logger import Logger
from constraint_verifier import ConstraintVerifier
from export_manager import ExportManager
from config_manager import ConfigManager
from data_loader import DataLoader

class HospitalScheduler:
    def __init__(self, people_data=None, night_dates=None, festivity_dates=None, settings=None, config=None):
        self.people = people_data or {}
        self.schedule = {}
        self.shift_counts = {}
        self.required_night_dates = night_dates or []
        self.festivity_dates = festivity_dates or []
        self.warnings = []  # New: track warnings when shifts cannot be assigned
        
        # Initialize configuration manager
        if config is None:
            self.config = ConfigManager()
            print("✅ Default configuration loaded")
        else:
            self.config = config
            print("✅ Custom configuration loaded")
        
        # Override with provided settings if any
        if settings:
            self.config.update(settings)
            print("✅ Custom settings applied")
        
        self.print_config_summary()

        # Validate configuration
        is_valid, errors = self.config.validate_settings()
        if not is_valid:
            print("⚠️  Configuration validation errors:")
            for error in errors:
                print(f"   {error}")
            print("Using default values for invalid settings...")
        
        # Get settings from config manager (this should now include merged settings)
        self.settings = self.config.get_all_settings()
        
        # Initialize the logger
        self.logger = Logger(self.settings)
        
        # Initialize results dictionary
        self.results = {}  # New property to store results
        
        self.logger.log('data_loading', 'info', f"Loaded {len(self.required_night_dates)} required night dates")
        self.logger.log('data_loading', 'info', f"Loaded {len(self.festivity_dates)} festivity dates")
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
        
        # Check if desiderata enforcement is enabled
        enforce_desiderata = self.settings['multi_run'].get('enforce_desiderata', False)
        prioritize_minimal_unassigned = self.settings['multi_run'].get('prioritize_minimal_unassigned_shifts', False)
        scoring_enabled = self.settings['multi_run'].get('person_scoring', {}).get('enabled', False)
        only_consider_best_passes = self.settings['multi_run'].get('only_consider_best_passes', True)
        target_best_pass_runs = self.settings['multi_run'].get('target_best_pass_runs', 100)
        accumulate_best_pass_runs = self.settings['multi_run'].get('accumulate_best_pass_runs', False)
        
        if enforce_desiderata:
            self.logger.log('multi_run_optimization', 'info', "Desiderata enforcement: ENABLED - only compliant runs will be considered")
        
        if prioritize_minimal_unassigned:
            self.logger.log('multi_run_optimization', 'info', "Minimal unassigned shifts: ENABLED - prioritizing solutions with fewest unassigned shifts")
        
        if scoring_enabled:
            scoring_settings = self.settings['multi_run']['person_scoring']
            self.logger.log('multi_run_optimization', 'info', 
                f"Person scoring: ENABLED - coeffs: night={scoring_settings.get('night_score_coeff', 2.0)}, "
                f"weekend={scoring_settings.get('weekend_score_coeff', 1.5)}, "
                f"afternoon={scoring_settings.get('afternoon_score_coeff', 1.0)}")
        
        best_schedule = None
        best_constraint_results = None
        best_passed_count = -1
        best_unassigned_count = float('inf')  # <-- ensure initialized
        best_hour_difference = float('inf')   # <-- ensure initialized
        best_discrimination_score = float('inf')  # <-- ensure initialized
        all_runs = []
        max_passed_count = -1  # Track the highest number of passes seen
        best_pass_runs = 0     # Track number of runs with best passes

        # Progress bar settings
        max_runs = self.settings['multi_run']['max_runs']
        show_progress = self.settings['multi_run'].get('show_progress_bar', True)
        progress_width = 50
        
        # Save original randomization settings
        original_randomize_people = self.settings.get('randomize_people_order', False)
        original_randomize_priority = self.settings.get('randomize_priority_tiebreaking', False)
        
        # Save original logging settings if silence is enabled
        original_logging_settings = None
        if self.settings['multi_run'].get('silence_output', True):
            original_logging_settings = self.logger.logging_settings.copy()
            # Set all logging to 'silence' except multi_run_optimization
            silenced_settings = {}
            for category in self.logger.logging_settings:
                if category == 'multi_run_optimization':
                    silenced_settings[category] = self.logger.logging_settings[category]
                else:
                    silenced_settings[category] = 'silence'
            self.logger.update_settings(silenced_settings)
        
        # Enable randomization for multi-run if specified
        if self.settings['multi_run']['enable_randomization_for_multi_run']:
            self.settings['randomize_people_order'] = True
            self.settings['randomize_priority_tiebreaking'] = True
        
        # Initialize progress bar
        if show_progress:
            print(f"\nProgress: [{'':>{progress_width}}] 0/{max_runs} (0.0%)", end='', flush=True)
        
        skipped_runs = 0  # Track runs skipped due to desiderata violations
        
        run_id = 0
        while run_id < max_runs:
            self.logger.log('multi_run_optimization', 'debug', f"\nRun {run_id + 1}/{max_runs}...")
            
            try:
                # Reset scheduler state for each run
                self.schedule = {}
                self.shift_counts = {}
                self.warnings = []
                
                # Reinitialize the shift assigner for each run
                self.shift_assigner = ShiftAssigner(self)
                
                # Generate single schedule
                schedule = self._generate_schedule_single(start_date, end_date)
                
                # Check desiderata compliance if enforcement is enabled
                if enforce_desiderata:
                    is_compliant, violation_reason = self._check_desiderata_compliance(start_date, end_date)
                    if not is_compliant:
                        skipped_runs += 1
                        self.logger.log('multi_run_optimization', 'debug', f"  Skipped run {run_id + 1}: {violation_reason}")
                        continue  # Skip this run and try the next one
                
                # Verify constraints
                constraint_results = self.verify_constraints(start_date, end_date)
                
                # Count passed constraints
                passed_count = sum(1 for status in constraint_results.values() if status == 'PASS')
                total_constraints = len(constraint_results)
                failed_count = total_constraints - passed_count
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
                
                # Calculate unassigned shifts count
                unassigned_count = self.calculate_total_unassigned_shifts(start_date, end_date)
                
                # Calculate discrimination score for this solution
                discrimination_score = self.calculate_solution_discrimination_score(schedule, self.shift_counts)
                
                self.logger.log('multi_run_optimization', 'debug', 
                    f"  Result: {passed_count}/{total_constraints} constraints passed, "
                    f"{failed_count} failed, {warning_count} warnings, "
                    f"{unassigned_count} unassigned, {hour_difference}h difference, "
                    f"discrimination_score={discrimination_score:.1f}")
                
                # Store run results with discrimination score
                run_result = {
                    'run_id': run_id,
                    'schedule': schedule.copy(),
                    'constraint_results': constraint_results.copy(),
                    'passed_count': passed_count,
                    'total_constraints': total_constraints,
                    'failed_count': failed_count,
                    'warning_count': warning_count,
                    'unassigned_count': unassigned_count,
                    'hour_difference': hour_difference,
                    'discrimination_score': discrimination_score,  # NEW: Store discrimination score
                    'warnings': self.warnings.copy(),
                    'shift_counts': self.shift_counts.copy(),
                    'success': passed_count == total_constraints and warning_count == 0 and unassigned_count == 0
                }
                all_runs.append(run_result)

                # Track the highest number of passes seen
                if passed_count > max_passed_count:
                    max_passed_count = passed_count
                    best_pass_runs = 1
                elif passed_count == max_passed_count:
                    best_pass_runs += 1

                # Check if this is the best so far
                is_better = False

                # Defensive: ensure best_unassigned_count etc. are initialized
                # (already initialized above, but keep for clarity)

                if prioritize_minimal_unassigned:
                    if unassigned_count < best_unassigned_count:
                        is_better = True
                    elif unassigned_count == best_unassigned_count:
                        if passed_count > best_passed_count:
                            is_better = True
                        elif passed_count == best_passed_count:
                            if 'best_warnings' in locals():
                                best_warnings_len = len(best_warnings)
                            else:
                                best_warnings_len = float('inf')
                            if warning_count < best_warnings_len:
                                is_better = True
                            elif warning_count == best_warnings_len:
                                if hour_difference < best_hour_difference:
                                    is_better = True
                                elif hour_difference == best_hour_difference and scoring_enabled:
                                    if discrimination_score < best_discrimination_score:
                                        is_better = True
                else:
                    if passed_count > best_passed_count:
                        is_better = True
                    elif passed_count == best_passed_count:
                        if 'best_warnings' in locals():
                            best_warnings_len = len(best_warnings)
                        else:
                            best_warnings_len = float('inf')
                        if warning_count < best_warnings_len:
                            is_better = True
                        elif warning_count == best_warnings_len:
                            if unassigned_count < best_unassigned_count:
                                is_better = True
                            elif unassigned_count == best_unassigned_count:
                                if hour_difference < best_hour_difference:
                                    is_better = True
                                elif hour_difference == best_hour_difference and scoring_enabled:
                                    if discrimination_score < best_discrimination_score:
                                        is_better = True

                if is_better:
                    best_passed_count = passed_count
                    best_unassigned_count = unassigned_count
                    best_schedule = schedule.copy()
                    best_constraint_results = constraint_results.copy()
                    best_hour_difference = hour_difference
                    best_discrimination_score = discrimination_score
                    best_warnings = self.warnings.copy()
                    best_shift_counts = self.shift_counts.copy()
                    self.logger.log('multi_run_optimization', 'info', f"  🎯 New best result!")
                
                # Update progress bar
                if show_progress:
                    progress = (run_id + 1) / max_runs
                    filled_width = int(progress_width * progress)
                    bar = '█' * filled_width + '░' * (progress_width - filled_width)
                    percent = progress * 100

                    # Add status indicator
                    status = ""
                    if is_better:
                        status = " 🎯"
                    elif failed_count <= self.settings['multi_run']['target_fails']:
                        status = " ✅"

                    # Include skipped runs info if enforcement is enabled
                    skip_info = f" (Skipped: {skipped_runs})" if enforce_desiderata and skipped_runs > 0 else ""
                    # Show best_pass_runs / target_best_pass_runs in progress bar
                    best_pass_runs_info = ""
                    if only_consider_best_passes and accumulate_best_pass_runs:
                        best_pass_runs_info = f" | Top: {best_pass_runs}/{target_best_pass_runs}"
                    print(
                        f"\rProgress: [{bar}] {run_id + 1}/{max_runs} ({percent:.1f}%) - Best: {best_passed_count}/{total_constraints}{status}{skip_info}{best_pass_runs_info}",
                        end='', flush=True
                    )
                
                # Early termination if target reached (for best pass runs)
                if accumulate_best_pass_runs and only_consider_best_passes:
                    if best_pass_runs >= target_best_pass_runs:
                        self.logger.log('multi_run_optimization', 'info', f"  ✅ Target of {target_best_pass_runs} best-pass runs reached!")
                        break

                # Early termination if target reached (for fails)
                if failed_count <= self.settings['multi_run']['target_fails']:
                    self.logger.log('multi_run_optimization', 'info', f"  ✅ Target of ≤{self.settings['multi_run']['target_fails']} failed constraints reached!")
                    break
                
            except Exception as e:
                self.logger.log('multi_run_optimization', 'error', f"  ❌ Run failed with exception: {e}")
                continue
            run_id += 1
        
        # Clear progress bar line
        if show_progress:
            print()  # New line after progress bar
        
        # Restore original settings
        self.settings['randomize_people_order'] = original_randomize_people
        self.settings['randomize_priority_tiebreaking'] = original_randomize_priority
        
        # Restore original logging settings if they were silenced
        if original_logging_settings is not None:
            self.logger.update_settings(original_logging_settings)
        
        self.logger.log('multi_run_optimization', 'info', f"\n=== MULTI-RUN RESULTS ===")
        self.logger.log('multi_run_optimization', 'info', f"Completed {len(all_runs)} runs")
        self.logger.log('multi_run_optimization', 'info', f"Best result: {best_passed_count}/{len(best_constraint_results) if best_constraint_results else 0} constraints passed")
        
        # Display ranking of all runs
        self.logger.log('multi_run_optimization', 'info', f"\n=== RANKING OF ALL RUNS ===")
        
        # Filter runs to only those with the highest number of passes if setting is enabled
        if only_consider_best_passes and all_runs:
            all_runs = [run for run in all_runs if run['passed_count'] == max_passed_count]
            self.logger.log('multi_run_optimization', 'info', f"Filtered to {len(all_runs)} runs with best passes ({max_passed_count}/{total_constraints})")

        # Sort runs based on priority setting with discrimination score as final tiebreaker
        if prioritize_minimal_unassigned:
            # Sort by: unassigned (asc), passed (desc), warnings (asc), hour_diff (asc), discrimination_score (asc)
            sorted_runs = sorted(all_runs, key=lambda x: (
                x['unassigned_count'], 
                -x['passed_count'], 
                x['warning_count'], 
                x['hour_difference'],
                x.get('discrimination_score', float('inf'))
            ))
            self.logger.log('multi_run_optimization', 'info', f"Best result: {best_unassigned_count} unassigned, {best_passed_count}/{len(best_constraint_results) if best_constraint_results else 0} constraints passed")
        else:
            # Sort by: passed (desc), warnings (asc), unassigned (asc), hour_diff (asc), discrimination_score (asc)
            sorted_runs = sorted(all_runs, key=lambda x: (
                -x['passed_count'], 
                x['warning_count'], 
                x['unassigned_count'],
                x['hour_difference'],
                x.get('discrimination_score', float('inf'))
            ))
            self.logger.log('multi_run_optimization', 'info', f"Best result: {best_passed_count}/{len(best_constraint_results) if best_constraint_results else 0} constraints passed")
        
        # Short console display - show unassigned shifts if prioritized
        if self._should_log('multi_run_optimization', 'info'):
            if prioritize_minimal_unassigned:
                print(f"{'Rank':<4} {'Run':<4} {'Unassigned':<10} {'Passed':<8} {'Warnings':<8} {'Hr_Diff':<8}")
                print("-" * 46)
                
                for rank, run in enumerate(sorted_runs, 1):
                    print(f"{rank:<4} {run['run_id']+1:<4} {run['unassigned_count']:<10} {run['passed_count']:<8} {run['warning_count']:<8} {run['hour_difference']:<8}")
            else:
                # UPDATED: Show unassigned shifts even when not prioritized
                print(f"{'Rank':<4} {'Run':<4} {'Passed':<8} {'Warnings':<8} {'Unassigned':<10} {'Hr_Diff':<8}")
                print("-" * 50)
                
                for rank, run in enumerate(sorted_runs, 1):
                    print(f"{rank:<4} {run['run_id']+1:<4} {run['passed_count']:<8} {run['warning_count']:<8} {run['unassigned_count']:<10} {run['hour_difference']:<8}")

        # Export detailed ranking to CSV
        self._export_multi_run_ranking(sorted_runs)
        
        # Restore the best run's state to the scheduler
        if best_schedule:
            self.schedule = best_schedule
            self.warnings = best_warnings
            self.shift_counts = best_shift_counts
            self.logger.log('multi_run_optimization', 'info', f"\n=== USING BEST RESULT (Run {sorted_runs[0]['run_id'] + 1}) ===")
        
        # Report desiderata enforcement results
        if enforce_desiderata:
            compliant_runs = len(all_runs)
            total_attempts = max_runs
            self.logger.log('multi_run_optimization', 'info', f"Desiderata enforcement: {compliant_runs} compliant runs out of {total_attempts} attempts ({skipped_runs} skipped)")
        
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
        """Calculate total hours for a person including vacation days and tirocinio"""
        total_hours = 0
        person = self.people[person_id]
        
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
        
        # Add tirocinio hours (NEW)
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday only
                is_tirocinio_day = ('tirocinio_dates' in person and 
                                  date in person['tirocinio_dates'])
                
                if is_tirocinio_day:
                    assigned_shifts = self.schedule[person_id].get(date, [])
                    # Person gets tirocinio morning hours UNLESS they have afternoon shift
                    if 'afternoon' not in assigned_shifts and 'mp' not in assigned_shifts:
                        total_hours += self.settings['morning_shift_hours']
        
        # Add vacation days (Ferie) - count as morning shift hours for weekdays
        for forbidden in person.get('forbidden_shifts', []):
            if forbidden and len(forbidden['shifts']) == 3:
                # This is a vacation day (all MPN shifts forbidden)
                vacation_date = forbidden['date']
                if vacation_date in all_dates and vacation_date.weekday() < 5:  # Weekday only
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

    def export_to_csv(self, output_file, start_date=None, end_date=None):
        """Export schedule to CSV file - delegates to ExportManager"""
        self.export_manager.export_schedule_to_csv(output_file, start_date, end_date)
        self.results['schedule'] = output_file  # Save the filename in results

    def export_staff_statistics_to_csv(self, start_date, end_date, output_file='staff_statistics.csv'):
        """Export detailed staff statistics to CSV file - delegates to ExportManager"""
        if self.settings.get('export_staff_statistics', False):  # Check if enabled
            self.export_manager.export_staff_statistics_to_csv(start_date, end_date, output_file)
            self.results['staff_statistics'] = output_file  # Save the filename in results
        else:
            self.results['staff_statistics'] = None  # Save None if not enabled

    def export_all_formats(self, start_date, end_date, base_filename='schedule'):
        """Export schedule in all available formats - delegates to ExportManager"""
        if self.settings.get('export_all_formats', False):  # Check if enabled
            self.export_manager.export_all(start_date, end_date, base_filename)
            self.results['all_formats'] = f"{base_filename}.*"  # Save the base filename in results
        else:
            self.results['all_formats'] = None  # Save None if not enabled

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
        all_dates = [start_date + timedelta(days=i) for i in range(total_days)]
        
        # Collect data for all people
        summary_data = []
        violations = []
        
        # Check monthly night shift violations for each person
        months_in_period = set((date.year, date.month) for date in all_dates)
        
        for person_id in sorted(self.people.keys()):
            person = self.people[person_id]
            dates = sorted(self.schedule[person_id].keys())
            
            # Count shifts separately (no double counting for MP)
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
            
            # Count shifts properly from the schedule (separate counts, no double counting)
            for date in dates:
                shifts = self.schedule[person_id][date]
                is_weekend = date.weekday() >= 5
                
                # Only count weekend days if they have non-night shifts
                if shifts and is_weekend:
                    non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:  # Has morning, afternoon, or mp shifts
                        weekend_days += 1
                
                # Count each shift type separately
                for shift in shifts:
                    if shift == 'morning':
                        morning_count += 1
                    elif shift == 'afternoon':
                        afternoon_count += 1
                    elif shift == 'mp':
                        mp_count += 1
                    elif shift == 'night':
                        night_count += 1
            
            # Count Ferie (vacation) days - weekdays only
            ferie_count = 0
            for forbidden in person.get('forbidden_shifts', []):
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates and vacation_date.weekday() < 5:  # Weekday only
                        ferie_count += 1
            
            # Count Tirocinio days (excluding days when they have afternoon shifts)
            tirocinio_count = 0
            for date in all_dates:
                if date.weekday() < 5:  # Monday-Friday only
                    is_tirocinio_day = ('tirocinio_dates' in person and 
                                      date in person['tirocinio_dates'])
                    
                    if is_tirocinio_day:
                        assigned_shifts = self.schedule[person_id].get(date, [])
                        # Count tirocinio only if they DON'T have afternoon shift
                        if 'afternoon' not in assigned_shifts and 'mp' not in assigned_shifts:
                            tirocinio_count += 1
            
            # Calculate total hours including vacation days and tirocinio
            total_hours = self.calculate_total_hours_for_person(person_id, all_dates)
            
            avg_hours_per_week = total_hours / total_weeks if total_weeks > 0 else 0
            
            # Check for other violations
            if avg_hours_per_week < self.settings['min_weekly_hours']:
                violations.append(f"Person {person_id}: {avg_hours_per_week:.1f}h/week (below {self.settings['min_weekly_hours']}h minimum)")
            elif avg_hours_per_week > self.settings['max_weekly_hours']:
                violations.append(f"Person {person_id}: {avg_hours_per_week:.1f}h/week (above {self.settings['max_weekly_hours']}h maximum)")
            
            summary_data.append([
                person_id, 
                total_hours, 
                morning_count,      # M only (no MP included)
                afternoon_count,    # P only (no MP included)
                mp_count,           # MP only
                night_count,        # N
                ferie_count,        # F
                tirocinio_count,    # T
                weekend_days,       # Weekends
                f"{avg_hours_per_week:.1f}"
            ])
        
        # Print table header with MP column
        print("┌────────────┬─────────────┬─────┬─────┬─────┬─────┬─────┬─────┬──────────┬─────────────────────┐")
        print("│ Person     │ Total Hours │  M  │  P  │ MP  │  N  │  F  │  T  │ Weekends │ Avg Hours per Week  │")
        print("├────────────┼─────────────┼─────┼─────┼─────┼─────┼─────┼─────┼──────────┼─────────────────────┤")
        
        # Print data rows
        for row in summary_data:
            person, total_h, m, p, mp, n, f, t, weekends, avg = row
            print(f"│ {person:<10} │     {total_h:<7} │  {m:<2} │  {p:<2} │  {mp:<2} │  {n:<2} │  {f:<2} │  {t:<2} │    {weekends:<5} │        {avg:<12} │")
        
        print("└────────────┴─────────────┴─────┴─────┴─────┴─────┴─────┴─────┴──────────┴─────────────────────┘")
        print("\nLegend: M=Morning, P=Afternoon, MP=Morning+Afternoon combined, N=Night, F=Ferie,\nT=Tirocinio, Weekends=Weekend days worked")
        
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

    def _check_desiderata_compliance(self, start_date, end_date):
        """Check if current schedule complies with desiderata (forbidden shifts and vacation)"""
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        for person_id in self.people.keys():
            person_data = self.people[person_id]
            
            # Check forbidden shifts compliance
            for forbidden in person_data.get('forbidden_shifts', []):
                if forbidden and forbidden['date'] in all_dates:
                    assigned_shifts = self.schedule[person_id].get(forbidden['date'], [])
                    for forbidden_shift in forbidden['shifts']:
                        if forbidden_shift in assigned_shifts:
                            return False, f"Person {person_id} assigned forbidden {forbidden_shift} on {forbidden['date']}"

            # Check forbidden weekends compliance
            for forbidden_weekend in person_data.get('forbidden_weekends', []):
                if forbidden_weekend:
                    # Check if this weekend (Saturday or Sunday) is forbidden
                    for date in all_dates:
                        if date.weekday() >= 5:  # Weekend day
                            weekend_start = date - timedelta(days=date.weekday() - 5)  # Get Saturday
                            if abs((weekend_start - forbidden_weekend).days) <= 1:
                                assigned_shifts = self.schedule[person_id].get(date, [])
                                # Only flag if they have non-night shifts (actual weekend work)
                                non_night_shifts = [s for s in assigned_shifts if s not in ['night', 'rest_after_night']]
                                if non_night_shifts:
                                    return False, f"Person {person_id} assigned weekend work on forbidden weekend {forbidden_weekend}"
        
        return True, "Compliant"
    
    def calculate_total_unassigned_shifts(self, start_date, end_date):
        """Calculate total number of shifts that should have been assigned but weren't"""
        unassigned_count = 0
        current_date = start_date
        
        while current_date <= end_date:
            is_weekend = current_date.weekday() >= 5
            is_festivity = current_date in self.festivity_dates
            
            if is_festivity:
                # Festivity days need MP shifts
                required_mp = self.settings.get('festivity_staff', 1)
                actual_mp = self._count_assigned_shifts_on_date(current_date, 'mp')
                unassigned_count += max(0, required_mp - actual_mp)
                
            elif current_date.weekday() == 6:  # Sunday
                # Sunday needs MP shifts
                required_mp = self.settings.get('sunday_staff', 1)
                actual_mp = self._count_assigned_shifts_on_date(current_date, 'mp')
                unassigned_count += max(0, required_mp - actual_mp)
                
            elif current_date.weekday() == 5:  # Saturday
                # Saturday morning
                required_morning = self.settings.get('saturday_morning_staff', 0)
                actual_morning = self._count_assigned_shifts_on_date(current_date, 'morning')
                unassigned_count += max(0, required_morning - actual_morning)
                
                # Saturday afternoon
                required_afternoon = self.settings.get('saturday_afternoon_staff', 0)
                actual_afternoon = self._count_assigned_shifts_on_date(current_date, 'afternoon')
                unassigned_count += max(0, required_afternoon - actual_afternoon)
                
                # Saturday MP
                required_mp = self.settings.get('saturday_mp_staff', 1)
                actual_mp = self._count_assigned_shifts_on_date(current_date, 'mp')
                unassigned_count += max(0, required_mp - actual_mp)
                
            else:  # Weekdays
                # Morning shifts (required)
                required_morning = self.settings['min_morning_staff']
                actual_morning = self._count_assigned_shifts_on_date(current_date, 'morning')
                unassigned_count += max(0, required_morning - actual_morning)
                
                # Afternoon shifts (optional, but count if setting > 0)
                required_afternoon = self.settings['target_afternoon_staff']
                actual_afternoon = self._count_assigned_shifts_on_date(current_date, 'afternoon')
                unassigned_count += max(0, required_afternoon - actual_afternoon)
            
            # Night shifts (if required)
            if current_date in self.required_night_dates:
                required_night = self.settings['night_staff']
                actual_night = self._count_assigned_shifts_on_date(current_date, 'night')
                unassigned_count += max(0, required_night - actual_night)
            
            current_date += timedelta(days=1)
        
        return unassigned_count

    def _count_assigned_shifts_on_date(self, date, shift_type):
        """Count how many people are assigned a specific shift type on a specific date"""
        count = 0
        for person_id in self.people.keys():
            if shift_type in self.schedule[person_id].get(date, []):
                count += 1
        return count

    def calculate_solution_discrimination_score(self, schedule, shift_counts):
        """Calculate discrimination score using max differences between people"""
        scoring_settings = self.settings['multi_run'].get('person_scoring', {})
        
        if not scoring_settings.get('enabled', False):
            return 0  # No scoring discrimination
        
        night_coeff = scoring_settings.get('night_score_coeff', 2.0)
        weekend_coeff = scoring_settings.get('weekend_score_coeff', 1.5)
        afternoon_coeff = scoring_settings.get('afternoon_score_coeff', 1.0)
        
        # Collect counts for each person
        night_counts = []
        weekend_counts = []
        afternoon_counts = []
        
        for person_id in self.people.keys():
            counts = shift_counts.get(person_id, {'morning': 0, 'afternoon': 0, 'night': 0, 'weekend_days': 0})
            
            night_counts.append(counts['night'])
            weekend_counts.append(counts['weekend_days'])
            afternoon_counts.append(counts['afternoon'])
        
        # Calculate max differences
        max_night_difference = max(night_counts) - min(night_counts) if night_counts else 0
        max_weekend_difference = max(weekend_counts) - min(weekend_counts) if weekend_counts else 0
        max_afternoon_difference = max(afternoon_counts) - min(afternoon_counts) if afternoon_counts else 0
        
        # Calculate discrimination score (lower is better - more balanced)
        discrimination_score = (
            max_night_difference * night_coeff +
            max_weekend_difference * weekend_coeff +
            max_afternoon_difference * afternoon_coeff
        )
        
        return discrimination_score

def merge_settings(base_settings, overrides):
    """Recursively merge override settings into base settings"""
    if not overrides:
        return base_settings
    
    merged = base_settings.copy() if base_settings else {}
    
    for key, value in overrides.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = merge_settings(merged[key], value)
        else:
            merged[key] = value
    
    return merged

def parse_command_line_args():
    """Parse command line arguments for settings overrides"""
    overrides = {}
    
    if len(sys.argv) > 1:
        try:
            # Try to parse as JSON string
            overrides = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            # Try to parse as key=value pairs
            for arg in sys.argv[1:]:
                if '=' in arg:
                    key_path, value = arg.split('=', 1)
                    # Handle nested keys like "multi_run.max_runs=50"
                    keys = key_path.split('.')
                    current = overrides
                    for k in keys[:-1]:
                        if k not in current:
                            current[k] = {}
                        current = current[k]
                    
                    # Try to convert value to appropriate type
                    try:
                        if value.lower() in ['true', 'false']:
                            current[keys[-1]] = value.lower() == 'true'
                        elif value.isdigit():
                            current[keys[-1]] = int(value)
                        elif '.' in value and value.replace('.', '').isdigit():
                            current[keys[-1]] = float(value)
                        else:
                            current[keys[-1]] = value
                    except:
                        current[keys[-1]] = value
    
    return overrides

def main(settings_overrides=None):
    # Clear terminal at start of each run
    import os
    os.system('cls' if os.name == 'nt' else 'clear')

    # Parse command line arguments if no overrides provided
    if settings_overrides is None:
        settings_overrides = parse_command_line_args()

    # Option 2: Use custom configuration inline (as before)
    base_settings = {
        # Staff requirements
        'min_morning_staff': 2,
        'target_afternoon_staff': 1,
        'night_staff': 1,
        'saturday_morning_staff': 0,
        'saturday_afternoon_staff': 0,
        'saturday_mp_staff': 1,        # Staff required for Saturday MP shift
        'sunday_staff': 1,
        'festivity_staff': 1,  # Staff required for festivity days (MP shift)
        
        # Working hours constraints
        'min_weekly_hours': 34,
        'max_weekly_hours': 48,
        'morning_shift_hours': 6,
        'afternoon_shift_hours': 6,
        'night_shift_hours': 12,
        'sunday_mp_shift_hours': 12,
        
        # Monthly and daily limits
        'max_weekend_days_per_month': 2,
        'night_shifts_per_month': 1,
        'max_consecutive_days': 6,
        'min_rest_hours_between_shifts': 11,
        'min_continuous_rest_hours': 24,
        
        # Scheduling rules
        'weekend_morning_plus_afternoon': True,  # Saturday can have morning+afternoon
        'night_shifts_only_weekdays': False,
        'fill_up_to_minimum_hours': True,  # Add extra shifts to reach minimum hours
        'prevent_consecutive_weekend_days': True,  # Prevent working both Saturday and Sunday in same weekend
        
        # Data file names (with extensions)
        'data_files': {
            'people_data_file': 'desiderata_original.csv',     # People/constraints data file with extension
            'night_dates_file': 'notti.csv',          # Required night dates file with extension
            'festivity_dates_file': 'festivi.csv',     # Festivity dates file with extension
        },
        
        # Bias mitigation settings
        'randomize_people_order': True,
        'randomize_priority_tiebreaking': True,
        'randomize_date_order': True, # Randomize date processing order for non-night shifts
        
        # Priority assignment settings
        'priority_assignment': {
            'night_priority_enabled': True,
            'weekend_priority_enabled': True,
            'priority_weight': 1.0
        },
        
        'workload_balancing': {
            'enabled': False,
            'night_burden_coefficient': 1.5,
            'weekend_burden_coefficient': 0.8,
            'min_afternoon_shifts': 0,
            'max_afternoon_compensation': 4
        },
        
        # Multi-run optimization settings
        'multi_run': {
            'enabled': True,
            'max_runs': 100,
            'target_fails': 0,
            'enable_randomization_for_multi_run': True,
            'silence_output': True,
            'show_progress_bar': True,
            'enforce_desiderata': True,  # Enforce desiderata compliance in multi-run
            'prioritize_minimal_unassigned_shifts': True,  # Only consider solutions with minimal unassigned shifts
            'person_scoring': {
                'enabled': True,
                'night_score_coeff': 2.0,      # Weight for night shifts
                'weekend_score_coeff': 2.0,    # Weight for weekend shifts
                'afternoon_score_coeff': 1.0   # Weight for afternoon shifts
            }
        },
        
        'afternoon_balancing': {
            'enabled': True,           # Enable afternoon shift weekly balancing
            'deprioritize_weekly_repeats': True,  # Lower priority for people with afternoon shifts this week
            'consider_weekly_hours': True,  # Consider weekly hours in afternoon shift priority
            'enforce_strict_weekly_balance': True,    # Only consider people with lowest weekly afternoon count
            'consider_weekends_afternoons': False,     # Count weekend MP shifts as afternoon shifts for balancing
            'give_precedence_to_afternoon_over_morning': True,  # Assign afternoon shifts before morning shifts
            'prefer_not_in_internship': True  # Prefer people not in internship for afternoon shifts
        },
        
        # Logging/Output verbosity settings (silence, error, info, debug)
        'logging': {
            'data_loading': 'error',              
            'settings_display': 'error',
            'multi_run_optimization': 'error',
            'night_shift_assignment': 'error',
            'workload_balancing': 'error',
            'weekend_shift_balancing': 'error',
            'fill_up_minimum_hours': 'error',
            'shift_assignment_warnings': 'debug',
            'shift_assignment_debug': 'debug',
            'afternoon_balancing': 'error',
            'constraint_verification': 'error',
            'schedule_display': 'error',
            'summary_statistics': 'info',
            'export_notifications': 'info'
        },
        
        # Constraint system settings (NEW)
        'constraint_system': {
            'enabled_constraint_groups': ['staffing', 'personal', 'work_hours', 'forbidden', 'festivity'],
            'disabled_constraints': [],  # List of specific constraint IDs to disable
            'custom_constraints': {},     # Custom constraint definitions
            'severity_levels': {
                'CRITICAL': True,   # Show critical constraint violations
                'HIGH': True,       # Show high priority violations  
                'MEDIUM': True,     # Show medium priority violations
                'LOW': False        # Hide low priority violations
            }
        },
    }
    
    # Merge base settings with overrides
    settings = merge_settings(base_settings, settings_overrides)
    
    # Option 3: Use configuration file
    config_file = None  # or 'my_config.json'
    
    # Option 4: Use preset configuration
    preset = None  # Set to None or comment out to use your custom settings
    # preset = 'balanced'  # 'strict', 'balanced', 'optimized', 'debug'
    
    # Load CSV data using new DataLoader
    data_loader = DataLoader()
    
    # Check what formats are supported
    supported_formats = data_loader.get_supported_formats()
    dependencies = data_loader.check_dependencies()
    
    if 'error' not in ['error']:  # Only show if not in silent mode
        print(f"📁 Supported file formats: {', '.join(supported_formats)}")
        if not dependencies['excel_support']:
            print("💡 Tip: Install pandas and openpyxl for Excel (.xlsx) support: pip install pandas openpyxl")
    
    # Get default file names directly from ConfigManager
    config = ConfigManager(config_file)
    
    # Apply preset first if specified
    if preset:
        config.apply_preset(preset)
    
    # --- CHANGED: Get file names from settings, not config ---
    people_file = settings['data_files']['people_data_file']
    night_file = settings['data_files']['night_dates_file']
    festivity_file = settings['data_files']['festivity_dates_file']
    
    # Load data files directly with specified extensions
    people_data = data_loader.load_people_data(people_file, log_level='error')
    
    # If the specified file doesn't exist, try alternative formats
    if not people_data or len(people_data) < 2:
        file_base = os.path.splitext(people_file)[0]  # Remove extension to get base name
        for ext in ['xlsx', 'xls', 'csv']:
            alt_file = f'{file_base}.{ext}'
            if os.path.exists(alt_file) and alt_file != people_file:  # Don't retry the same file
                print(f"📊 File {people_file} not found, trying {alt_file}...")
                people_data = data_loader.load_people_data(alt_file, log_level='error')
                if people_data and len(people_data) >= 2:
                    break

    print(f"👥 Loaded {len(people_data)} people from {people_file}")

    night_dates = data_loader.load_night_dates(night_file, log_level='error')
    
    # If the specified file doesn't exist, try alternative formats
    if not night_dates:
        file_base = os.path.splitext(night_file)[0]
        for ext in ['xlsx', 'xls', 'csv']:
            alt_file = f'{file_base}.{ext}'
            if os.path.exists(alt_file) and alt_file != night_file:
                print(f"🌙 File {night_file} not found, trying {alt_file}...")
                night_dates = data_loader.load_night_dates(alt_file, log_level='error')
                if night_dates:
                    break

    print(f"🌙 Loaded {len(night_dates)} night dates from {night_file}")
    
    # Load festivity dates
    festivity_dates = data_loader.load_festivity_dates(festivity_file, log_level='error')
    
    # If the specified file doesn't exist, try alternative formats
    if not festivity_dates:
        file_base = os.path.splitext(festivity_file)[0]
        for ext in ['xlsx', 'xls', 'csv']:
            alt_file = f'{file_base}.{ext}'
            if os.path.exists(alt_file) and alt_file != festivity_file:
                print(f"🎉 File {festivity_file} not found, trying {alt_file}...")
                festivity_dates = data_loader.load_festivity_dates(alt_file, log_level='error')
                if festivity_dates:
                    break

    print(f"🎉 Loaded {len(festivity_dates)} festivity dates from {festivity_file}")

    # Validate loaded data
    is_valid, validation_errors = data_loader.validate_data(people_data, night_dates, festivity_dates)
    if not is_valid:
        print("⚠️  Data validation errors:")
        for error in validation_errors:
            print(f"   {error}")
    
    # Define scheduling period (example: November 2025)
    start_date = datetime(2025, 11, 1).date()
    end_date = datetime(2025, 11, 30).date()
    
    # Create scheduler instance with actual data
    scheduler = HospitalScheduler(
        people_data=people_data, 
        night_dates=night_dates,
        festivity_dates=festivity_dates,
        settings=settings,  # Pass the merged settings here
        config=config       # And also pass the config manager
    )
    
    # Apply preset first if specified (this is redundant now, remove it)
    # if preset:
    #     scheduler.apply_preset(preset)
    
    # Then apply your custom settings (this is also redundant now, remove it)
    # if settings:
    #     scheduler.update_settings(settings)
    
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
    scheduler.export_to_csv('schedule_output.csv', start_date, end_date)
    scheduler.export_staff_statistics_to_csv(start_date, end_date, 'staff_statistics.csv')
    
    # Export debug information if available
    if hasattr(scheduler, 'assignment_failures'):
        scheduler.export_manager.export_assignment_debug('assignment_debug.csv')

    # Save all data to the specified output folder
    output_folder = 'history'  # Define your output folder name
    scheduler.export_manager.save_all_data(output_folder)  # Call save_all_data method

    # Save configuration for next time (optional)
    # scheduler.save_config('last_used_config.json')

    scheduler._log('data_loading', 'info', "Schedule generation completed!")

    # --- DOCX EXPORT (add this block) ---
    try:
        from doc_creator import ScheduleDocxCreator
        docx_creator = ScheduleDocxCreator(
            json_path="output/schedule_output.json",
            doc_path="output/schedule_output.docx"
            # Optionally add more settings here if needed
        )
        docx_creator.create_doc()
        print("✅ DOCX exported to output/schedule_output.docx")
    except Exception as e:
        print(f"❌ DOCX export failed: {e}")

if __name__ == "__main__":
    overrides = {
        'data_files': {
            'people_data_file': 'desiderata_NOV.csv',     # People/constraints data file with extension
            'night_dates_file': 'notti_NOV.csv',          # Required night dates file with extension
            'festivity_dates_file': 'festivi_NOV.csv',     # Festivity dates file with extension
        },
        'multi_run': {
            'enabled': True,
            'max_runs': 10000,
            'only_consider_best_passes': True,
            'target_best_pass_runs': 100,
            'accumulate_best_pass_runs': True
        },
        'logging': {
            'data_loading': 'error',              
            'settings_display': 'error',
            'multi_run_optimization': 'error',
            'night_shift_assignment': 'error',
            'workload_balancing': 'error',
            'weekend_shift_balancing': 'error',
            'fill_up_minimum_hours': 'debug',
            'shift_assignment_warnings': 'debug',
            'shift_assignment_debug': 'debug',
            'afternoon_balancing': 'error',
            'constraint_verification': 'error',
            'schedule_display': 'error',
            'summary_statistics': 'debug',
            'export_notifications': 'info'
        },
        # 'min_morning_staff': 3
    }
    main(overrides)