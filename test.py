import csv
import random
from datetime import datetime, timedelta
from collections import defaultdict
import os
import sys
from main import HospitalScheduler

class SchedulerTester:
    def __init__(self, test_config=None):
        """Initialize the scheduler tester with configurable parameters"""
        # Default test configuration
        self.config = {
            'num_people': 5,
            'num_tests': 10,
            'date_range': {
                'start': datetime(2025, 10, 1).date(),
                'end': datetime(2025, 10, 31).date()
            },
            'prohibited_shifts': {
                'min_per_person': 0,
                'max_per_person': 3,
                'shift_types': ['M', 'P', 'N', 'MP', 'PN']  # Morning, Afternoon, Night, Morning+Afternoon, Afternoon+Night
            },
            'prohibited_weekends': {
                'min_per_person': 0,
                'max_per_person': 2
            },
            'night_availability': {
                'probability_unavailable': 0.2  # 20% chance person is unavailable for nights
            },
            'required_nights': {
                'min_nights': 2,
                'max_nights': 8
            },
            'scheduler_settings': {
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
                'night_shifts_only_weekdays': True,
                'fill_up_to_minimum_hours': True,
                'workload_balancing': {
                    'enabled': False,
                    'night_burden_coefficient': 20,
                    'weekend_burden_coefficient': 15,
                    'min_afternoon_shifts': 0,
                    'max_afternoon_compensation': 3
                }
            }
        }
        
        # Override with provided configuration
        if test_config:
            self.config.update(test_config)
        
        self.results = []
    
    def generate_random_date_in_range(self):
        """Generate a random weekday date within the test date range"""
        start_date = self.config['date_range']['start']
        end_date = self.config['date_range']['end']
        
        # Get all weekdays (Monday-Friday) in the range
        weekdays = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Monday=0, Friday=4
                weekdays.append(current_date)
            current_date += timedelta(days=1)
        
        if not weekdays:
            return start_date  # Fallback if no weekdays found
        
        return random.choice(weekdays)
    
    def generate_random_weekend_date(self):
        """Generate a random weekend date (Saturday) within the test date range"""
        start_date = self.config['date_range']['start']
        end_date = self.config['date_range']['end']
        
        # Find all Saturdays in the range
        current_date = start_date
        saturdays = []
        
        while current_date <= end_date:
            if current_date.weekday() == 5:  # Saturday
                saturdays.append(current_date)
            current_date += timedelta(days=1)
        
        return random.choice(saturdays) if saturdays else None
    
    def generate_random_people_data(self):
        """Generate random people data with prohibited shifts and weekends"""
        people_data = {}
        
        for person_id in range(1, self.config['num_people'] + 1):
            person_id_str = str(person_id)
            
            # Generate random prohibited shifts
            num_prohibited_shifts = random.randint(
                self.config['prohibited_shifts']['min_per_person'],
                self.config['prohibited_shifts']['max_per_person']
            )
            
            forbidden_shifts = []
            for _ in range(num_prohibited_shifts):
                shift_date = self.generate_random_date_in_range()
                shift_types = random.choice(self.config['prohibited_shifts']['shift_types'])
                
                # Convert shift type string to list of individual shifts
                shift_list = []
                if 'M' in shift_types:
                    shift_list.append('morning')
                if 'P' in shift_types:
                    shift_list.append('afternoon')
                if 'N' in shift_types:
                    shift_list.append('night')
                
                forbidden_shifts.append({
                    'date': shift_date,
                    'shifts': shift_list
                })
            
            # Generate random prohibited weekends
            num_prohibited_weekends = random.randint(
                self.config['prohibited_weekends']['min_per_person'],
                self.config['prohibited_weekends']['max_per_person']
            )
            
            forbidden_weekends = []
            for _ in range(num_prohibited_weekends):
                weekend_date = self.generate_random_weekend_date()
                if weekend_date:
                    forbidden_weekends.append(weekend_date)
            
            # Random night availability
            night_available = random.random() > self.config['night_availability']['probability_unavailable']
            
            people_data[person_id_str] = {
                'forbidden_shifts': forbidden_shifts,
                'forbidden_weekends': forbidden_weekends,
                'night_available': night_available
            }
        
        return people_data
    
    def generate_random_night_dates(self):
        """Generate random required night dates"""
        num_nights = random.randint(
            self.config['required_nights']['min_nights'],
            self.config['required_nights']['max_nights']
        )
        
        # Generate random weekday dates (Monday-Friday) for night shifts
        start_date = self.config['date_range']['start']
        end_date = self.config['date_range']['end']
        
        weekdays = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Monday-Friday
                weekdays.append(current_date)
            current_date += timedelta(days=1)
        
        if len(weekdays) < num_nights:
            num_nights = len(weekdays)
        
        return random.sample(weekdays, num_nights)
    
    def export_test_data_to_csv(self, people_data, night_dates, test_id):
        """Export generated test data to CSV files for debugging"""
        # Export desiderata data
        desiderata_file = f'test_desiderata_{test_id}.csv'
        with open(desiderata_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            
            # Header
            header = ['Persona', 'Notti'] + [f'Turno vietato {i}' for i in range(1, 7)] + [f'Weekend vietato {i}' for i in range(1, 4)]
            writer.writerow(header)
            
            # Data rows
            for person_id, data in people_data.items():
                row = [person_id]
                
                # Night availability
                row.append('N' if not data['night_available'] else 'Y')
                
                # Forbidden shifts (up to 6)
                shift_strings = []
                for forbidden in data['forbidden_shifts']:
                    if forbidden:
                        date_str = forbidden['date'].strftime('%d/%m/%Y')
                        shift_codes = []
                        for shift in forbidden['shifts']:
                            if shift == 'morning':
                                shift_codes.append('M')
                            elif shift == 'afternoon':
                                shift_codes.append('P')
                            elif shift == 'night':
                                shift_codes.append('N')
                        shift_strings.append(f"{date_str} {''.join(shift_codes)}")
                
                # Pad to 6 shift columns
                while len(shift_strings) < 6:
                    shift_strings.append('')
                row.extend(shift_strings[:6])
                
                # Forbidden weekends (up to 3)
                weekend_strings = []
                for weekend_date in data['forbidden_weekends']:
                    if weekend_date:
                        weekend_strings.append(weekend_date.strftime('%d/%m/%Y'))
                
                # Pad to 3 weekend columns
                while len(weekend_strings) < 3:
                    weekend_strings.append('')
                row.extend(weekend_strings[:3])
                
                writer.writerow(row)
        
        # Export night dates
        notti_file = f'test_notti_{test_id}.csv'
        with open(notti_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['Notte richiesta'])
            for night_date in night_dates:
                writer.writerow([night_date.strftime('%d/%m/%Y')])
        
        return desiderata_file, notti_file
    
    def run_single_test(self, test_id):
        """Run a single scheduling test with random data"""
        print(f"\n{'='*60}")
        print(f"RUNNING TEST {test_id + 1}")
        print(f"{'='*60}")
        
        # Generate random test data
        people_data = self.generate_random_people_data()
        night_dates = self.generate_random_night_dates()
        
        # Export test data for debugging (optional)
        if test_id < 3:  # Only export first 3 tests to avoid clutter
            desiderata_file, notti_file = self.export_test_data_to_csv(people_data, night_dates, test_id)
            print(f"Test data exported to: {desiderata_file}, {notti_file}")
        
        # Print test configuration
        print(f"Test configuration:")
        print(f"  People: {len(people_data)}")
        print(f"  Required night dates: {len(night_dates)}")
        
        # Count night-available people
        night_available_count = sum(1 for p in people_data.values() if p['night_available'])
        print(f"  Night-available people: {night_available_count}/{len(people_data)}")
        
        # Create scheduler and run
        try:
            scheduler = HospitalScheduler(
                people_data=people_data,
                night_dates=night_dates,
                settings=self.config['scheduler_settings']
            )
            
            start_date = self.config['date_range']['start']
            end_date = self.config['date_range']['end']
            
            # Generate schedule
            schedule = scheduler.generate_schedule(start_date, end_date)
            
            # Export schedule output for each test (like main.py does)
            if test_id < 3:  # Only export first 3 tests to avoid clutter
                schedule_output_file = f'test_schedule_output_{test_id}.csv'
                scheduler.export_to_csv(schedule_output_file)
                print(f"Schedule output exported to: {schedule_output_file}")
            
            # Verify constraints
            constraint_results = scheduler.verify_constraints(start_date, end_date)
            
            # Calculate statistics
            passed_constraints = sum(1 for status in constraint_results.values() if status == 'PASS')
            total_constraints = len(constraint_results)
            success_rate = passed_constraints / total_constraints if total_constraints > 0 else 0
            
            # Count warnings
            warning_count = len(scheduler.warnings)
            
            # Calculate person-specific statistics
            person_stats = {}
            total_days = (end_date - start_date).days + 1
            total_weeks = total_days / 7
            
            # NEW: Calculate hour difference between highest and lowest person
            person_hours = []
            
            for person_id in people_data.keys():
                morning_shifts = 0
                afternoon_shifts = 0
                night_shifts = 0
                weekend_days = 0
                total_hours = 0
                
                # Get all dates in the scheduling period
                all_dates = []
                current_date = start_date
                while current_date <= end_date:
                    all_dates.append(current_date)
                    current_date += timedelta(days=1)
                
                # Count shifts and calculate hours
                for date in all_dates:
                    shifts = scheduler.schedule[person_id].get(date, [])
                    is_weekend = date.weekday() >= 5
                    has_non_night_weekend_shifts = False
                    
                    for shift in shifts:
                        if shift == 'morning':
                            morning_shifts += 1
                            total_hours += self.config['scheduler_settings']['morning_shift_hours']
                            if is_weekend:
                                has_non_night_weekend_shifts = True
                        elif shift == 'afternoon':
                            afternoon_shifts += 1
                            total_hours += self.config['scheduler_settings']['afternoon_shift_hours']
                            if is_weekend:
                                has_non_night_weekend_shifts = True
                        elif shift == 'mp':
                            morning_shifts += 1  # MP counts as both
                            afternoon_shifts += 1
                            total_hours += self.config['scheduler_settings']['sunday_mp_shift_hours']
                            if is_weekend:
                                has_non_night_weekend_shifts = True
                        elif shift == 'night':
                            night_shifts += 1
                            total_hours += self.config['scheduler_settings']['night_shift_hours']
                    
                    # Count weekend days (only if has non-night shifts)
                    if is_weekend and has_non_night_weekend_shifts:
                        weekend_days += 1
                
                # Calculate average hours per week
                avg_hours = total_hours / total_weeks if total_weeks > 0 else 0
                
                # Add to person hours list for hour difference calculation
                person_hours.append(total_hours)
                
                person_stats[person_id] = {
                    'morning_shifts': morning_shifts,
                    'afternoon_shifts': afternoon_shifts,
                    'night_shifts': night_shifts,
                    'weekend_days': weekend_days,
                    'total_hours': total_hours,
                    'avg_hours': avg_hours
                }
            
            # Calculate hour difference
            hour_difference = max(person_hours) - min(person_hours) if person_hours else 0
            
            # Store results
            test_result = {
                'test_id': test_id,
                'success': passed_constraints == total_constraints and warning_count == 0,
                'passed_constraints': passed_constraints,
                'total_constraints': total_constraints,
                'success_rate': success_rate,
                'warning_count': warning_count,
                'hour_difference': hour_difference,  # NEW: Add hour difference
                'warnings': scheduler.warnings.copy(),
                'constraint_results': constraint_results.copy(),
                'people_count': len(people_data),
                'night_available_count': night_available_count,
                'required_nights_count': len(night_dates),
                'people_data': people_data,
                'night_dates': night_dates,
                'person_stats': person_stats  # Add person statistics
            }
            
            print(f"Result: {passed_constraints}/{total_constraints} constraints passed")
            print(f"Warnings: {warning_count}")
            print(f"Overall success: {'✅ PASS' if test_result['success'] else '❌ FAIL'}")
            
            return test_result
            
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            return {
                'test_id': test_id,
                'success': False,
                'error': str(e),
                'people_count': len(people_data),
                'night_available_count': sum(1 for p in people_data.values() if p['night_available']),
                'required_nights_count': len(night_dates)
            }
    
    def run_tests(self):
        """Run multiple scheduling tests and analyze results"""
        print(f"Starting {self.config['num_tests']} scheduling tests...")
        print(f"Date range: {self.config['date_range']['start']} to {self.config['date_range']['end']}")
        print(f"People per test: {self.config['num_people']}")
        
        # Run all tests
        for test_id in range(self.config['num_tests']):
            result = self.run_single_test(test_id)
            self.results.append(result)
        
        # Analyze results
        self.analyze_results()
    
    def analyze_results(self):
        """Analyze and report test results"""
        print(f"\n{'='*80}")
        print("TEST RESULTS ANALYSIS")
        print(f"{'='*80}")
        
        successful_tests = [r for r in self.results if r.get('success', False)]
        failed_tests = [r for r in self.results if not r.get('success', False)]
        
        print(f"Total tests: {len(self.results)}")
        print(f"Successful tests: {len(successful_tests)} ({len(successful_tests)/len(self.results)*100:.1f}%)")
        print(f"Failed tests: {len(failed_tests)} ({len(failed_tests)/len(self.results)*100:.1f}%)")
        
        if successful_tests:
            avg_success_rate = sum(r.get('success_rate', 0) for r in successful_tests) / len(successful_tests)
            avg_warnings = sum(r.get('warning_count', 0) for r in successful_tests) / len(successful_tests)
            print(f"Average constraint success rate: {avg_success_rate*100:.1f}%")
            print(f"Average warnings per successful test: {avg_warnings:.1f}")
        
        # NEW: Statistical analysis of person performance
        self.analyze_person_statistics()
        
        # NEW: Detailed constraint-by-constraint results for each test
        print(f"\n{'='*80}")
        print("DETAILED CONSTRAINT RESULTS BY TEST")
        print(f"{'='*80}")
        
        # Get all unique constraint names from all tests
        all_constraints = set()
        for result in self.results:
            if 'constraint_results' in result:
                all_constraints.update(result['constraint_results'].keys())
        
        constraint_list = sorted(list(all_constraints))
        
        if constraint_list:
            # Print header
            print(f"{'Test':<6}", end="")
            for constraint in constraint_list:
                # Shorten constraint names for display
                short_name = self.shorten_constraint_name(constraint)
                print(f"{short_name:<8}", end="")
            print(f"{'Overall':<8} {'Warnings':<8}")
            print("-" * (6 + len(constraint_list) * 8 + 16))
            
            # Print results for each test
            for result in self.results:
                test_num = result.get('test_id', 0) + 1
                print(f"{test_num:<6}", end="")
                
                if 'constraint_results' in result:
                    for constraint in constraint_list:
                        status = result['constraint_results'].get(constraint, 'N/A')
                        symbol = "✅" if status == 'PASS' else "❌" if status == 'FAIL' else "?"

                        print(f"{symbol:<8}", end="")
                    
                    overall_symbol = "✅" if result.get('success', False) else "❌"
                    warning_count = result.get('warning_count', 0)
                    print(f"{overall_symbol:<8} {warning_count:<8}")
                else:
                    # Test had an exception
                    for _ in constraint_list:
                        print(f"{'ERR':<8}", end="")
                    print(f"{'❌':<8} {'-':<8}")
            
            # Print constraint legend
            print(f"\nCONSTRAINT LEGEND:")
            for i, constraint in enumerate(constraint_list, 1):
                short_name = self.shorten_constraint_name(constraint)
                full_name = constraint.replace('_', ' ').title()
                print(f"{i:2}. {short_name:<8} = {full_name}")
        
        # Constraint failure analysis
        print(f"\nCONSTRAINT FAILURE ANALYSIS:")
        constraint_failures = defaultdict(int)
        
        for result in self.results:
            if 'constraint_results' in result:
                for constraint, status in result['constraint_results'].items():
                    if status == 'FAIL':
                        constraint_failures[constraint] += 1
        
        if constraint_failures:
            print("Most common constraint violations:")
            sorted_failures = sorted(constraint_failures.items(), key=lambda x: x[1], reverse=True)
            for constraint, count in sorted_failures[:10]:
                percentage = count / len(self.results) * 100
                print(f"  {constraint.replace('_', ' ').title()}: {count}/{len(self.results)} tests ({percentage:.1f}%)")
        else:
            print("No constraint violations found!")
        
        # Warning analysis
        print(f"\nWARNING ANALYSIS:")
        warning_types = defaultdict(int)
        
        for result in self.results:
            for warning in result.get('warnings', []):
                if 'Could not assign' in warning:
                    if 'night shift' in warning:
                        warning_types['Night shift assignment'] += 1
                    elif 'morning shift' in warning:
                        warning_types['Morning shift assignment'] += 1
                    elif 'afternoon shift' in warning:
                        warning_types['Afternoon shift assignment'] += 1
                    else:
                        warning_types['Other assignment'] += 1
        
        if warning_types:
            print("Most common warnings:")
            sorted_warnings = sorted(warning_types.items(), key=lambda x: x[1], reverse=True)
            for warning_type, count in sorted_warnings:
                print(f"  {warning_type}: {count} occurrences")
        else:
            print("No warnings found!")
        
        # Configuration correlation analysis
        print(f"\nCONFIGURATION CORRELATION ANALYSIS:")
        
        # Analyze night availability impact
        night_available_counts = [r.get('night_available_count', 0) for r in self.results if 'night_available_count' in r]
        successful_night_counts = [r.get('night_available_count', 0) for r in successful_tests if 'night_available_count' in r]
        
        if night_available_counts:
            avg_night_available = sum(night_available_counts) / len(night_available_counts)
            avg_successful_night = sum(successful_night_counts) / len(successful_night_counts) if successful_night_counts else 0
            print(f"Average night-available people: {avg_night_available:.1f}")
            print(f"Average night-available people in successful tests: {avg_successful_night:.1f}")
        
        # Show detailed results for failed tests
        if failed_tests and len(failed_tests) <= 5:
            print(f"\nDETAILED FAILURE ANALYSIS:")
            for result in failed_tests:
                print(f"\nTest {result['test_id'] + 1} failures:")
                if 'error' in result:
                    print(f"  Exception: {result['error']}")
                elif 'constraint_results' in result:
                    failed_constraints = [c for c, s in result['constraint_results'].items() if s == 'FAIL']
                    if failed_constraints:
                        print(f"  Failed constraints: {', '.join(failed_constraints)}")
                    if result.get('warnings'):
                        print(f"  Warnings: {len(result['warnings'])}")
                        for warning in result['warnings'][:3]:  # Show first 3 warnings
                            print(f"    - {warning}")
        
        # Export detailed results to CSV
        self.export_results_to_csv()
    
    def shorten_constraint_name(self, constraint_name):
        """Create shortened versions of constraint names for display"""
        name_map = {
            'morning_staff_weekdays': 'WDMornPers',
            'saturday_morning_staff': 'SatMornPers',
            'max_afternoon_staff': 'MaxAftnPers',
            'sunday_mp_staff': 'SunMPPers',
            'night_coverage': 'NightCover',
            'monthly_night_limits': 'MonthNightLim',
            'weekly_hours': 'WeekHrs',
            'max_consecutive_days': 'ConsecDays',
            'night_rest_periods': 'NightRest',
            'weekend_days_per_month': 'WkndsMonth',
            'forbidden_shifts': 'ForbShifts',
            'vacation_compliance': 'VacCompl',  # NEW: Add vacation compliance
            'night_availability': 'NightAvl',
            'weekday_morning_coverage': 'WDMornCover',
            'weekday_afternoon_coverage': 'WDAftnCover',
            'weekend_coverage': 'WkndCover'
        }
        return name_map.get(constraint_name, constraint_name[:7])

    def export_results_to_csv(self):
        """Export test results to CSV for further analysis"""
        results_file = 'test_results.csv'
        
        # Get all unique constraint names
        all_constraints = set()
        for result in self.results:
            if 'constraint_results' in result:
                all_constraints.update(result['constraint_results'].keys())
        
        constraint_list = sorted(list(all_constraints))
        
        # Get maximum number of people across all tests
        max_people = max(result.get('people_count', 0) for result in self.results)
        
        with open(results_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            
            # Header - use shortened constraint names
            header = [
                'Test_ID', 'Success', 'Passed_Constraints', 'Total_Constraints', 
                'Success_Rate', 'Warning_Count', 'People_Count', 'Night_Available_Count', 
                'Required_Nights_Count', 'Error', 'Hour_Difference'  # NEW: Add Hour_Difference
            ]
            
            # Add shortened constraint names as column headers
            for constraint in constraint_list:
                short_name = self.shorten_constraint_name(constraint)
                header.append(short_name)
            
            # Add person-specific columns
            for person_id in range(1, max_people + 1):
                header.extend([
                    f'M_{person_id}',        # Morning shifts
                    f'P_{person_id}',        # Afternoon shifts  
                    f'N_{person_id}',        # Night shifts
                    f'W_{person_id}',        # Weekend days
                    f'H_{person_id}',        # Total hours
                    f'A_{person_id}'         # Average hours per week
                ])
            
            writer.writerow(header)
            
            # Data rows
            for result in self.results:
                row = [
                    result.get('test_id', '') + 1,  # Show test number starting from 1
                    result.get('success', False),
                    result.get('passed_constraints', 0),
                    result.get('total_constraints', 0),
                    result.get('success_rate', 0),
                    result.get('warning_count', 0),
                    result.get('people_count', 0),
                    result.get('night_available_count', 0),
                    result.get('required_nights_count', 0),
                    result.get('error', ''),
                    result.get('hour_difference', 0)  # NEW: Add hour difference
                ]
                
                # Add individual constraint results: * for fail, empty for pass
                if 'constraint_results' in result:
                    for constraint in constraint_list:
                        status = result['constraint_results'].get(constraint, 'N/A')
                        if status == 'FAIL':
                            row.append('*')
                        elif status == 'PASS':
                            row.append('')
                        else:
                            row.append('?')
                else:
                    # Test had an exception - mark all constraints as ERROR
                    for _ in constraint_list:
                        row.append('ERR')
                
                # Add person-specific data
                person_stats = result.get('person_stats', {})
                for person_id in range(1, max_people + 1):
                    person_id_str = str(person_id)
                    
                    if person_id_str in person_stats:
                        stats = person_stats[person_id_str]
                        row.extend([
                            stats['morning_shifts'],
                            stats['afternoon_shifts'],
                            stats['night_shifts'],
                            stats['weekend_days'],
                            stats['total_hours'],
                            f"{stats['avg_hours']:.1f}"
                        ])
                    elif person_id <= result.get('people_count', 0):
                        # Person exists but no stats available (likely due to error)
                        row.extend(['N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A'])
                    else:
                        # Person doesn't exist in this test
                        row.extend(['', '', '', '', '', ''])
                
                writer.writerow(row)
        
        print(f"\nDetailed results exported to: {results_file}")
    
    def analyze_person_statistics(self):
        """Analyze and display statistical performance for each person across all tests"""
        print(f"\n{'='*80}")
        print("PERSON PERFORMANCE STATISTICS ACROSS ALL TESTS")
        print(f"{'='*80}")
        
        # Get maximum number of people across all tests
        max_people = max(result.get('people_count', 0) for result in self.results)
        
        # Consider ALL tests with person statistics, not just successful ones
        tests_with_stats = [r for r in self.results if 'person_stats' in r]
        
        if not tests_with_stats:
            print("No tests with person statistics available.")
            return
        
        # Collect statistics for each person
        person_statistics = {}
        
        for person_id in range(1, max_people + 1):
            person_id_str = str(person_id)
            
            # Collect data from all tests where this person exists
            morning_shifts = []
            afternoon_shifts = []
            night_shifts = []
            weekend_days = []
            total_hours = []
            avg_hours = []
            
            tests_with_person = 0
            
            for result in tests_with_stats:
                if person_id <= result.get('people_count', 0):
                    person_stats = result.get('person_stats', {})
                    if person_id_str in person_stats:
                        stats = person_stats[person_id_str]
                        morning_shifts.append(stats['morning_shifts'])
                        afternoon_shifts.append(stats['afternoon_shifts'])
                        night_shifts.append(stats['night_shifts'])
                        weekend_days.append(stats['weekend_days'])
                        total_hours.append(stats['total_hours'])
                        avg_hours.append(stats['avg_hours'])
                        tests_with_person += 1
            
            if tests_with_person > 0:
                person_statistics[person_id] = {
                    'tests_count': tests_with_person,
                    'avg_morning_shifts': sum(morning_shifts) / len(morning_shifts),
                    'avg_afternoon_shifts': sum(afternoon_shifts) / len(afternoon_shifts),
                    'avg_night_shifts': sum(night_shifts) / len(night_shifts),
                    'avg_weekend_days': sum(weekend_days) / len(weekend_days),
                    'avg_total_hours': sum(total_hours) / len(total_hours),
                    'avg_weekly_hours': sum(avg_hours) / len(avg_hours),
                    'std_morning_shifts': self.calculate_std(morning_shifts),
                    'std_afternoon_shifts': self.calculate_std(afternoon_shifts),
                    'std_night_shifts': self.calculate_std(night_shifts),
                    'std_weekend_days': self.calculate_std(weekend_days),
                    'std_total_hours': self.calculate_std(total_hours),
                    'std_weekly_hours': self.calculate_std(avg_hours)
                }
        
        if not person_statistics:
            print("No person statistics available.")
            return
        
        # Print statistics table
        print(f"Based on {len(tests_with_stats)} tests with person statistics (including failed tests)")
        print()
        print("┌────────┬───────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────────────┐")
        print("│ Person │ Tests │ Avg Morning │ Avg Aftern. │ Avg Nights  │ Avg Weekend │ Avg Tot Hrs │ Avg Weekly Hours    │")
        print("├────────┼───────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────────────┤")
        
        for person_id in sorted(person_statistics.keys()):
            stats = person_statistics[person_id]
            print(f"│   {person_id:<4} │  {stats['tests_count']:<4} │    {stats['avg_morning_shifts']:<6.1f}   │    {stats['avg_afternoon_shifts']:<6.1f}   │    {stats['avg_night_shifts']:<6.1f}   │    {stats['avg_weekend_days']:<6.1f}   │    {stats['avg_total_hours']:<6.1f}   │        {stats['avg_weekly_hours']:<10.1f}   │")
        
        print("└────────┴───────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────────────┘")
        
        # Print standard deviations table
        print("\nSTANDARD DEVIATIONS:")
        print("┌────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────────────┐")
        print("│ Person │ Std Morning │ Std Aftern. │ Std Nights  │ Std Weekend │ Std Tot Hrs │ Std Weekly Hours    │")
        print("├────────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────────────┤")
        
        for person_id in sorted(person_statistics.keys()):
            stats = person_statistics[person_id]
            print(f"│   {person_id:<4} │    {stats['std_morning_shifts']:<6.1f}   │    {stats['std_afternoon_shifts']:<6.1f}   │    {stats['std_night_shifts']:<6.1f}   │    {stats['std_weekend_days']:<6.1f}   │    {stats['std_total_hours']:<6.1f}   │        {stats['std_weekly_hours']:<10.1f}   │")
        
        print("└────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────────────┘")
        
        # Export person statistics to separate CSV
        self.export_person_statistics_to_csv(person_statistics)
        
        return person_statistics

    def calculate_std(self, values):
        """Calculate standard deviation of a list of values"""
        if len(values) <= 1:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def export_person_statistics_to_csv(self, person_statistics):
        """Export person statistics to a separate CSV file"""
        stats_file = 'person_statistics.csv'
        
        with open(stats_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            
            # Header
            header = [
                'Person_ID', 'Tests_Count', 
                'Avg_Morning_Shifts', 'Avg_Afternoon_Shifts', 'Avg_Night_Shifts', 
                'Avg_Weekend_Days', 'Avg_Total_Hours', 'Avg_Weekly_Hours',
                'Std_Morning_Shifts', 'Std_Afternoon_Shifts', 'Std_Night_Shifts',
                'Std_Weekend_Days', 'Std_Total_Hours', 'Std_Weekly_Hours'
            ]
            writer.writerow(header)
            
            # Data rows
            for person_id in sorted(person_statistics.keys()):
                stats = person_statistics[person_id]
                row = [
                    person_id,
                    stats['tests_count'],
                    f"{stats['avg_morning_shifts']:.1f}",
                    f"{stats['avg_afternoon_shifts']:.1f}",
                    f"{stats['avg_night_shifts']:.1f}",
                    f"{stats['avg_weekend_days']:.1f}",
                    f"{stats['avg_total_hours']:.1f}",
                    f"{stats['avg_weekly_hours']:.1f}",
                    f"{stats['std_morning_shifts']:.1f}",
                    f"{stats['std_afternoon_shifts']:.1f}",
                    f"{stats['std_night_shifts']:.1f}",
                    f"{stats['std_weekend_days']:.1f}",
                    f"{stats['std_total_hours']:.1f}",
                    f"{stats['std_weekly_hours']:.1f}"
                ]
                writer.writerow(row)
        
        print(f"\nPerson statistics exported to: {stats_file}")


def main():
    """Main function to run the scheduler tests"""
    
    # SCHEDULER CONFIGURATION OPTIONS - Modify these to test different scenarios
    scheduler_options = {
        # Staffing requirements
        'min_morning_staff': 4,           # Minimum morning staff on weekdays
        'max_afternoon_staff': 1,         # Maximum afternoon staff (acts as target)
        'saturday_morning_staff': 0,      # Saturday morning staff requirement
        'saturday_afternoon_staff': 0,    # Saturday afternoon staff requirement
        'sunday_staff': 1,                # Sunday MP shift staff requirement
        
        # Working hours constraints
        'min_weekly_hours': 34,           # Minimum hours per week per person
        'max_weekly_hours': 48,           # Maximum hours per week per person
        'morning_shift_hours': 6,         # Hours per morning shift
        'afternoon_shift_hours': 6,       # Hours per afternoon shift
        'night_shift_hours': 12,          # Hours per night shift
        'sunday_mp_shift_hours': 12,      # Hours for Sunday MP shift
        
        # Monthly and daily limits
        'max_weekend_days_per_month': 2,  # Max weekend days per person per month
        'night_shifts_per_month': 1,      # Max night shifts per person per month  
        'max_consecutive_days': 6,        # Max consecutive working days
        
        # Shift policies
        'weekend_morning_plus_afternoon': True,   # Allow Saturday morning+afternoon
        'night_shifts_only_weekdays': False,      # Night shifts only Mon-Fri
        'fill_up_to_minimum_hours': True,        # Add extra shifts to reach 34h minimum
        
        # NEW: Bias mitigation settings
        'randomize_people_order': True,           # Option 1: Randomize people order at start of scheduling
        'randomize_priority_tiebreaking': True,  # Option 5: Add randomization to priority scoring
        
        # Workload balancing (experimental)
        'workload_balancing': {
            'enabled': False,              # Enable workload balancing algorithm
            'night_burden_coefficient': 20,
            'weekend_burden_coefficient': 15,
            'min_afternoon_shifts': 0,
            'max_afternoon_compensation': 3
        }
    }
    
    # TEST SCENARIO CONFIGURATION
    test_config = {
        'num_people': 6, # Number of people in each test
        'num_tests': 100, # Number of random tests to run
        'date_range': {
            'start': datetime(2025, 10, 1).date(),
            'end': datetime(2025, 10, 31).date()
        },
        
        # Random prohibited shifts generation
        'prohibited_shifts': {
            'min_per_person': 0,          # Min prohibited shifts per person
            'max_per_person': 6,          # Max prohibited shifts per person
            'shift_types': ['M', 'P', 'N', 'MP', 'PN']  # Available shift types to prohibit
        },
        
        # Random prohibited weekends generation
        'prohibited_weekends': {
            'min_per_person': 0,          # Min prohibited weekends per person
            'max_per_person': 2           # Max prohibited weekends per person
        },
        
        # Night availability simulation
        'night_availability': {
            'probability_unavailable': 0.0  # Probability that person can't do nights (0.0-1.0)
        },
        
        # Required night shifts generation
        'required_nights': {
            'min_nights': 5,              # Min required night shifts in period
            'max_nights': 5               # Max required night shifts in period
        },
        
        # Pass scheduler options to test config
        'scheduler_settings': scheduler_options
    }
    
    print("="*80)
    print("HOSPITAL SCHEDULER TESTING")
    print("="*80)
    print(f"Scheduler Configuration:")
    print(f"  Morning staff (weekdays): {scheduler_options['min_morning_staff']}")
    print(f"  Afternoon staff (weekdays): {scheduler_options['max_afternoon_staff']}")
    print(f"  Weekend staff - Sat: {scheduler_options['saturday_morning_staff']}M/{scheduler_options['saturday_afternoon_staff']}P, Sun: {scheduler_options['sunday_staff']}MP")
    print(f"  Weekly hours: {scheduler_options['min_weekly_hours']}-{scheduler_options['max_weekly_hours']}h")
    print(f"  Monthly limits: {scheduler_options['night_shifts_per_month']} nights, {scheduler_options['max_weekend_days_per_month']} weekend days")
    print(f"  Max consecutive days: {scheduler_options['max_consecutive_days']}")
    print(f"  Fill to minimum hours: {scheduler_options['fill_up_to_minimum_hours']}")
    print(f"  Workload balancing: {scheduler_options['workload_balancing']['enabled']}")
    # NEW: Display bias mitigation settings
    print(f"  Randomize people order: {scheduler_options['randomize_people_order']}")
    print(f"  Randomize priority tiebreaking: {scheduler_options['randomize_priority_tiebreaking']}")
    print()
    print(f"Test Configuration:")
    print(f"  Number of tests: {test_config['num_tests']}")
    print(f"  People per test: {test_config['num_people']}")
    print(f"  Date range: {test_config['date_range']['start']} to {test_config['date_range']['end']}")
    print(f"  Prohibited shifts: {test_config['prohibited_shifts']['min_per_person']}-{test_config['prohibited_shifts']['max_per_person']} per person")
    print(f"  Prohibited weekends: {test_config['prohibited_weekends']['min_per_person']}-{test_config['prohibited_weekends']['max_per_person']} per person")
    print(f"  Night unavailability probability: {test_config['night_availability']['probability_unavailable']*100}%")
    print(f"  Required nights: {test_config['required_nights']['min_nights']}-{test_config['required_nights']['max_nights']}")
    print("="*80)
    
    # Create and run tester
    tester = SchedulerTester(test_config)
    tester.run_tests()
    
    print(f"\nTesting completed! Check the generated CSV files for detailed analysis.")

if __name__ == "__main__":
    main()
