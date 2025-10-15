import csv
import os
import json
from datetime import timedelta, datetime
from typing import List
import shutil

class ExportManager:
    def __init__(self, scheduler):
        """Initialize with reference to main scheduler for accessing settings, people, schedule, etc."""
        self.scheduler = scheduler
        self.logger = scheduler.logger
        self.output_files = {}  # NEW: Track output files by type
    
    def export_schedule_to_csv(self, output_file, start_date=None, end_date=None):
        """Export schedule to CSV file (transposed format) with warnings column"""
        # Ensure the output file is in the output directory
        output_file = os.path.join(self.scheduler.output_dir, os.path.basename(output_file))
        
        # Prepare data for CSV
        all_dates = set()
        
        for person_schedule in self.scheduler.schedule.values():
            all_dates.update(person_schedule.keys())
        
        all_dates = sorted(list(all_dates))
        
        # Create header: Date, Day, Holiday, Night_Coverage, Morning Count, Afternoon Count, Night Count, then person columns, then Warnings
        people_ids = sorted(self.scheduler.people.keys())
        header = ['Date', 'Day', 'Holiday', 'Night_Coverage', 'Morning_Staff', 'Afternoon_Staff', 'Night_Staff'] + people_ids + ['Warnings']
        
        rows = [header]
        
        # Add data for each date
        for date in all_dates:
            day_name = date.strftime('%A')
            
            # Check if this is a holiday day
            is_holiday = date in self.scheduler.holiday_dates
            holiday_marker = '*' if is_holiday else ''
            
            # Check if night coverage is required on this date
            is_night_required = date in self.scheduler.required_night_dates
            night_coverage_marker = '*' if is_night_required else ''
            
            # Check if this is a weekend or holiday
            is_weekend_or_holiday = date.weekday() >= 5 or is_holiday
            
            # Count staff for each shift type on this date
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            
            # Prepare person data for this date
            person_data = []
            
            for person_id in people_ids:
                shifts = self.scheduler.schedule[person_id].get(date, [])
                
                # Check if this person is on vacation on this date
                is_on_vacation = self._is_person_on_vacation(person_id, date)
                
                # Check if this person has forbidden shifts on this date
                forbidden_shift_types = self._get_forbidden_shifts_for_date(person_id, date)
                
                # Check if this person is in tirocinio (training)
                is_in_tirocinio = self._is_person_in_tirocinio(person_id, date)
                
                # Check if this person has prohibited weekend on this date
                is_prohibited_weekend = self._is_prohibited_weekend(person_id, date)
                
                # Convert shifts to M, P, N, MP format first
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
                
                # Collect all markers that need to be appended
                markers = []
                
                if is_on_vacation:
                    # Person is on vacation - add F or (F) as marker
                    if is_weekend_or_holiday:
                        markers.append("(F)")
                    else:
                        markers.append("F")
                elif is_prohibited_weekend:
                    # Person has prohibited weekend - add (W) marker
                    markers.append("(D-W)")
                elif forbidden_shift_types:
                    # Person has forbidden shifts - add (D) with shift types marker
                    forbidden_display = "(D-" + "".join(forbidden_shift_types) + ")"
                    markers.append(forbidden_display)
                
                # Add tirocinio marker if person is in training
                if is_in_tirocinio:
                    markers.append("(T)")
                
                # Combine shift assignments with markers
                if shift_str and markers:
                    # Has both shifts and markers: "MP, (T)"
                    person_data.append(f"{', '.join(markers)} {shift_str}")
                elif shift_str:
                    # Only shifts: "MP"
                    person_data.append(shift_str)
                elif markers:
                    # Only markers: "(T)" or "F" or "(D) MP"
                    person_data.append(', '.join(markers))
                else:
                    # Nothing: empty cell
                    person_data.append("")
            
            # Find warnings for this date
            # Debug: Check if warnings exist
            date_warnings = [w for w in self.scheduler.warnings if date.strftime('%Y-%m-%d') in w]
            warnings_str = "; ".join(date_warnings) if date_warnings else ""

            # Create row: Date, Day, Holiday, Night_Coverage, Staff counts, then person shifts, then Warnings
            row = [
                date.strftime('%d/%m/%Y'),
                day_name,
                holiday_marker,
                night_coverage_marker,
                morning_count,
                afternoon_count, 
                night_count
            ] + person_data + [warnings_str]
            
            rows.append(row)
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerows(rows)
            
            # Optionally append staff statistics
            if (self.scheduler.settings.get('append_statistics_to_schedule', True) and 
                start_date is not None and end_date is not None):
                
                # Add blank row
                writer.writerow([])
                
                # Add statistics header aligned with person columns (skip base columns but include warnings column)
                stats_header_col = 6  # 6 base columns before person columns
                writer.writerow([''] * stats_header_col + ['STAFF STATISTICS'] + [''] * len(people_ids))
                writer.writerow([])
                
                # Get staff statistics data
                staff_data = self._get_staff_statistics_data(start_date, end_date)
                
                # Verify we have the correct number of data points (now 13 elements: 0-12)
                if staff_data and len(staff_data[0]) >= 13:
                    # Create statistics rows with titles aligned with person columns
                    stats_rows = [
                        [''] * stats_header_col + ['Total_Hours'] + [str(person_stats[1]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Vacation_Hours'] + [str(person_stats[2]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Morning_Shifts'] + [str(person_stats[3]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Afternoon_Shifts'] + [str(person_stats[4]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['MP_Shifts'] + [str(person_stats[5]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Night_Shifts'] + [str(person_stats[6]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Ferie_Days'] + [str(person_stats[7]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Tirocinio_Days'] + [str(person_stats[8]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Weekend_Days'] + [str(person_stats[9]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Avg_Hours_Per_Week'] + [str(person_stats[10]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Night_Priority'] + [str(person_stats[11]) for person_stats in staff_data] + [''],
                        [''] * stats_header_col + ['Weekend_Priority'] + [str(person_stats[12]) for person_stats in staff_data] + ['']
                    ]
                    
                    # Write statistics rows
                    for stats_row in stats_rows:
                        writer.writerow(stats_row)
                else:
                    # Fallback - just write basic statistics without new columns
                    if staff_data:
                        stats_rows = [
                            [''] * stats_header_col + ['Total_Hours'] + [str(person_stats[1]) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Vacation_Hours'] + [str(person_stats[2] if len(person_stats) > 2 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Morning_Shifts'] + [str(person_stats[3] if len(person_stats) > 3 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Afternoon_Shifts'] + [str(person_stats[4] if len(person_stats) > 4 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['MP_Shifts'] + [str(person_stats[5] if len(person_stats) > 5 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Night_Shifts'] + [str(person_stats[6] if len(person_stats) > 6 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Weekend_Days'] + [str(person_stats[9] if len(person_stats) > 9 else 0) for person_stats in staff_data] + [''],
                            [''] * stats_header_col + ['Avg_Hours_Per_Week'] + [str(person_stats[10] if len(person_stats) > 10 else "0.0") for person_stats in staff_data] + ['']
                        ]
                        
                        # Write statistics rows
                        for stats_row in stats_rows:
                            writer.writerow(stats_row)
        
        self.logger.log('export_notifications', 'info', f"Schedule exported to {output_file}")
        self.output_files['csv'] = output_file  # Save for later collection

        # Export JSON with the same base filename
        json_output_file = os.path.splitext(output_file)[0] + '.json'
        self.export_schedule_json(json_output_file)
        self.logger.log('export_notifications', 'info', f"Schedule exported to {json_output_file}")
        self.output_files['json'] = json_output_file  # Save for later collection
    
    def _get_staff_statistics_data(self, start_date, end_date):
        """Get staff statistics data for appending to schedule CSV, with detailed breakdowns."""
        total_days = (end_date - start_date).days + 1
        total_weeks = total_days / 7
        all_dates = [start_date + timedelta(days=i) for i in range(total_days)]
        holiday_dates = set(getattr(self.scheduler, 'holiday_dates', []))
        holidays = holiday_dates  # alias for clarity

        staff_data = []

        for person_id in sorted(self.scheduler.people.keys()):
            person = self.scheduler.people[person_id]

            # --- Standard counts ---
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            mp_count = 0
            weekend_days = 0
            shift_hours = 0

            # --- New: Detailed breakdowns ---
            saturday_m = saturday_p = saturday_mp = 0
            sunday_m = sunday_p = sunday_mp = 0
            holiday_m = holiday_p = holiday_mp = 0
            night_saturday = night_sunday = night_holiday = 0

            # Count shifts properly from the schedule
            dates = sorted(self.scheduler.schedule[person_id].keys())
            for date in dates:
                shifts = self.scheduler.schedule[person_id][date]
                is_saturday = date.weekday() == 5
                is_sunday = date.weekday() == 6
                is_holiday = date in holidays

                # Weekend day logic (unchanged)
                is_weekend = date.weekday() >= 5
                if shifts and is_weekend:
                    non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:
                        weekend_days += 1

                # Count each shift type and breakdowns
                for shift in shifts:
                    if shift == 'morning':
                        morning_count += 1
                        shift_hours += self.scheduler.settings['morning_shift_hours']
                        if is_saturday:
                            saturday_m += 1
                        elif is_sunday:
                            sunday_m += 1
                        elif is_holiday:
                            holiday_m += 1
                    elif shift == 'afternoon':
                        afternoon_count += 1
                        shift_hours += self.scheduler.settings['afternoon_shift_hours']
                        if is_saturday:
                            saturday_p += 1
                        elif is_sunday:
                            sunday_p += 1
                        elif is_holiday:
                            holiday_p += 1
                    elif shift == 'mp':
                        mp_count += 1
                        shift_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                        if is_saturday:
                            saturday_mp += 1
                        elif is_sunday:
                            sunday_mp += 1
                        elif is_holiday:
                            holiday_mp += 1
                    elif shift == 'night':
                        night_count += 1
                        shift_hours += self.scheduler.settings['night_shift_hours']
                        if is_saturday:
                            night_saturday += 1
                        elif is_sunday:
                            night_sunday += 1
                        elif is_holiday:
                            night_holiday += 1

            # Calculate tirocinio hours and count tirocinio days (UPDATED LOGIC)
            tirocinio_hours = 0
            tirocinio_count = 0
            for date in all_dates:
                if date.weekday() < 5:  # Monday-Friday only
                    is_tirocinio_day = ('tirocinio_dates' in person and 
                                      date in person['tirocinio_dates'])
                    if is_tirocinio_day:
                        assigned_shifts = self.scheduler.schedule[person_id].get(date, [])
                        prev_date = date - timedelta(days=1)
                        has_night_today = 'night' in assigned_shifts
                        has_night_prev = 'night' in self.scheduler.schedule[person_id].get(prev_date, [])
                        # Person gets tirocinio morning hours UNLESS they have afternoon/mp shift or a night shift on this or previous day
                        if (not has_night_today and not has_night_prev and
                            'afternoon' not in assigned_shifts and 'mp' not in assigned_shifts):
                            tirocinio_hours += self.scheduler.settings['morning_shift_hours']
                            tirocinio_count += 1

            # Calculate vacation hours and count vacation days (weekday vacation days count as morning shift hours)
            vacation_hours = 0
            ferie_count = 0
            for forbidden in person.get('forbidden_shifts', []):
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates and vacation_date.weekday() < 5:  # Monday-Friday only
                        vacation_hours += self.scheduler.settings['morning_shift_hours']
                        ferie_count += 1

            # Total hours including vacation and tirocinio
            total_hours = shift_hours + vacation_hours + tirocinio_hours

            # Average hours per week
            avg_hours_per_week = total_hours / total_weeks if total_weeks > 0 else 0

            # Get priorities
            night_priority = person.get('night_priority', 0)
            weekend_priority = person.get('weekend_priority', 0)

            # --- Compose extended stats row ---
            staff_data.append([
                person_id,                    # 0
                total_hours,                  # 1
                vacation_hours,               # 2
                morning_count,                # 3
                afternoon_count,              # 4
                mp_count,                     # 5
                night_count,                  # 6
                ferie_count,                  # 7
                tirocinio_count,              # 8
                weekend_days,                 # 9
                f"{avg_hours_per_week:.1f}",  # 10
                night_priority,               # 11
                weekend_priority,             # 12
                # --- Extended breakdowns ---
                saturday_m,                   # 13
                saturday_p,                   # 14
                saturday_mp,                  # 15
                night_saturday,               # 16
                sunday_m,                     # 17
                sunday_p,                     # 18
                sunday_mp,                    # 19
                night_sunday,                 # 20
                holiday_m,                    # 21
                holiday_p,                    # 22
                holiday_mp,                   # 23
                night_holiday                 # 24
            ])

        return staff_data
    
    def export_staff_statistics_to_csv(self, start_date, end_date, output_file='staff_statistics.csv'):
        """Export detailed staff statistics to CSV file"""
        # Ensure the output file is in the output directory
        output_file = os.path.join(self.scheduler.output_dir, os.path.basename(output_file))
        
        total_days = (end_date - start_date).days + 1
        total_weeks = total_days / 7
        all_dates = [start_date + timedelta(days=i) for i in range(total_days)]
        
        # Prepare data for all people
        staff_data = []
        
        for person_id in sorted(self.scheduler.people.keys()):
            person = self.scheduler.people[person_id]
            
            # Count shifts from schedule (separate counts, no double counting)
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            mp_count = 0
            weekend_days = 0
            shift_hours = 0
            
            # Count shifts properly from the schedule
            dates = sorted(self.scheduler.schedule[person_id].keys())
            for date in dates:
                shifts = self.scheduler.schedule[person_id][date]
                is_weekend = date.weekday() >= 5
                
                # Count weekend days if they have non-night shifts
                if shifts and is_weekend:
                    non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:
                        weekend_days += 1
                
                # Count each shift type separately and calculate hours from shifts
                for shift in shifts:
                    if shift == 'morning':
                        morning_count += 1
                        shift_hours += self.scheduler.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        afternoon_count += 1
                        shift_hours += self.scheduler.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        mp_count += 1
                        shift_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        night_count += 1
                        shift_hours += self.scheduler.settings['night_shift_hours']
            
            # Calculate tirocinio hours and count tirocinio days (NEW)
            tirocinio_hours = 0
            tirocinio_count = 0
            for date in all_dates:
                if date.weekday() < 5:  # Monday-Friday only
                    is_tirocinio_day = ('tirocinio_dates' in person and 
                                      date in person['tirocinio_dates'])
                    
                    if is_tirocinio_day:
                        assigned_shifts = self.scheduler.schedule[person_id].get(date, [])
                        # Person gets tirocinio morning hours UNLESS they have afternoon shift
                        if 'afternoon' not in assigned_shifts and 'mp' not in assigned_shifts:
                            tirocinio_hours += self.scheduler.settings['morning_shift_hours']
                            tirocinio_count += 1
            
            # Calculate vacation hours and count vacation days (weekday vacation days count as morning shift hours)
            vacation_hours = 0
            ferie_count = 0
            for forbidden in person.get('forbidden_shifts', []):
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates and vacation_date.weekday() < 5:  # Monday-Friday only
                        vacation_hours += self.scheduler.settings['morning_shift_hours']
                        ferie_count += 1
            
            # Total hours including vacation and tirocinio
            total_hours = shift_hours + vacation_hours + tirocinio_hours
            
            # Average hours per week
            avg_hours_per_week = total_hours / total_weeks if total_weeks > 0 else 0
            
            staff_data.append([
                person_id,
                total_hours,
                vacation_hours,
                morning_count,        # M only (no MP included)
                afternoon_count,      # P only (no MP included)
                mp_count,             # MP only
                night_count,          # N
                ferie_count,          # F (vacation days)
                tirocinio_count,      # T (tirocinio days)
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
            'MP_Shifts',
            'Night_Shifts',
            'Ferie_Days',
            'Tirocinio_Days',
            'Weekend_Days',
            'Avg_Hours_Per_Week'
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(header)
            writer.writerows(staff_data)
        
        self.logger.log('export_notifications', 'info', f"Staff statistics exported to {output_file}")
        self.output_files['staff_statistics'] = output_file  # Save for later collection
        return staff_data
    
    def export_multi_run_ranking(self, sorted_runs, filename='multi_run_ranking.csv'):
        """Export multi-run ranking to CSV"""
        ranking_file = os.path.join(self.scheduler.output_dir, os.path.basename(filename))
        print(f"Exporting multi-run ranking to {ranking_file}")
        # Get actual constraint names from the first run's results
        if sorted_runs and sorted_runs[0]['constraint_results']:
            actual_constraints = list(sorted_runs[0]['constraint_results'].keys())
        else:
            # Fallback to expected constraint names if no runs available
            actual_constraints = [
                'weekday_morning_staff', 'weekday_afternoon_staff', 'saturday_morning_staff', 
                'sunday_mp_staff', 'monthly_night_limits', 'monthly_weekend_limits',
                'weekly_hours', 'forbidden_shifts', 'holiday_coverage'
            ]
        
        # Get all person IDs for creating person-specific columns
        people_ids = sorted(self.scheduler.people.keys()) if self.scheduler.people else []
        
        # Constraint name mapping for CSV headers (shortened for better display)
        constraint_short_names = {
            'weekday_morning_staff': 'WD_Morn',
            'weekday_afternoon_staff': 'WD_Aftn',
            'saturday_morning_staff': 'Sat_Morn',
            'sunday_mp_staff': 'Sun_MP',
            'monthly_night_limits': 'Month_Night',
            'monthly_weekend_limits': 'Month_Wknd',
            'weekly_hours': 'Week_Hrs',
            'forbidden_shifts': 'Forbidden',
            'holiday_coverage': 'Holiday',
            # Legacy names (in case old constraint names are still used)
            'forbidden_shifts': 'ForbShifts',
            'target_afternoon_staff': 'MaxAftnPers',
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
            
            # CSV Header - Base columns + Constraint columns + Person statistics columns
            header = ['Rank', 'Run_ID', 'Passed_Constraints', 'Total_Constraints', 'Warnings', 'Unassigned', 'Hour_Difference', 'Discrimination_Score']
            
            # Add constraint columns
            for constraint in actual_constraints:
                short_name = constraint_short_names.get(constraint, constraint[:9])
                header.append(short_name)
            
            # Add person-specific statistics columns
            for person_id in people_ids:
                header.extend([
                    f'{person_id}_M',      # Morning shifts
                    f'{person_id}_P',      # Afternoon shifts  
                    f'{person_id}_N',      # Night shifts
                    f'{person_id}_WKND',   # Weekend days
                    f'{person_id}_totH',   # Total hours
                    f'{person_id}_avgH'    # Average hours per week
                ])
            
            writer.writerow(header)
            
            # CSV Data rows
            for rank, run in enumerate(sorted_runs, 1):
                row = [
                    rank,
                    run['run_id'] + 1,
                    run['passed_count'],
                    run['total_constraints'],
                    run['warning_count'],
                    run.get('unassigned_count', 0),
                    run['hour_difference'],
                    f"{run.get('discrimination_score', 0):.1f}"  # NEW: Add discrimination score right after Hour_Difference
                ]
                
                # Add constraint results using actual constraint names
                for constraint in actual_constraints:
                    status = run['constraint_results'].get(constraint, 'N/A')
                    # Use * for FAIL, empty for PASS, ? for N/A
                    if status == 'FAIL':
                        row.append('*')
                    elif status == 'PASS':
                        row.append('')
                    else:
                        row.append('?')
                
                # Add person-specific statistics
                for person_id in people_ids:
                    if 'shift_counts' in run and person_id in run['shift_counts']:
                        shift_counts = run['shift_counts'][person_id]
                        
                        # Calculate person statistics for this run
                        morning_shifts = shift_counts.get('morning', 0)
                        afternoon_shifts = shift_counts.get('afternoon', 0)
                        night_shifts = shift_counts.get('night', 0)
                        weekend_days = shift_counts.get('weekend_days', 0)
                        
                        # Calculate total hours for this person in this run
                        total_hours = self._calculate_person_hours_from_run(run, person_id)
                        
                        # Calculate average hours per week (assuming roughly 4.33 weeks per month)
                        # This is an approximation - for exact calculation we'd need the actual date range
                        avg_hours_per_week = total_hours / 4.33 if total_hours > 0 else 0
                        
                        row.extend([
                            morning_shifts,
                            afternoon_shifts,
                            night_shifts,
                            weekend_days,
                            f'{total_hours:.0f}',
                            f'{avg_hours_per_week:.1f}'
                        ])
                    else:
                        # No data available for this person in this run
                        row.extend(['', '', '', '', '', ''])
                
                writer.writerow(row)
        
        self.logger.log('export_notifications', 'info', f"Detailed ranking exported to: {ranking_file}")
        self.output_files['multi_run_ranking'] = ranking_file
    
    def _calculate_person_hours_from_run(self, run, person_id):
        """Calculate total hours for a person from a specific run's data"""
        if 'schedule' not in run or person_id not in run['schedule']:
            return 0
        
        total_hours = 0
        person_schedule = run['schedule'][person_id]
        
        for date, shifts in person_schedule.items():
            # Convert date string back to date object for tirocinio check
            if isinstance(date, str):
                try:
                    date_obj = datetime.strptime(date, '%Y-%m-%d').date()
                except:
                    continue
            else:
                date_obj = date
            
            # Count regular shift hours
            for shift in shifts:
                if shift == 'morning':
                    total_hours += self.scheduler.settings['morning_shift_hours']
                elif shift == 'afternoon':
                    total_hours += self.scheduler.settings['afternoon_shift_hours']
                elif shift == 'mp':
                    total_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                elif shift == 'night':
                    total_hours += self.scheduler.settings['night_shift_hours']
                # Don't count 'rest_after_night' as hours
        
            # Add tirocinio hours if applicable (NEW)
            if date_obj.weekday() < 5:  # Monday-Friday only
                person = self.scheduler.people.get(person_id, {})
                is_tirocinio_day = ('tirocinio_dates' in person and 
                                  date_obj in person['tirocinio_dates'])
                
                if is_tirocinio_day:
                    # Person gets tirocinio morning hours UNLESS they have afternoon shift
                    if 'afternoon' not in shifts and 'mp' not in shifts:
                        total_hours += self.scheduler.settings['morning_shift_hours']
        
        # Add vacation hours if applicable
        if person_id in self.scheduler.people:
            person_data = self.scheduler.people[person_id]
            for forbidden in person_data.get('forbidden_shifts', []):
                if forbidden and len(forbidden['shifts']) == 3:  # Vacation day
                    vacation_date = forbidden['date']
                    # Check if vacation date is in the schedule period
                    if vacation_date in person_schedule and vacation_date.weekday() < 5:  # Weekday only
                        total_hours += self.scheduler.settings['morning_shift_hours']
        
        return total_hours

    def export_constraint_summary(self, constraints_status, start_date, end_date, output_file='constraint_summary.csv'):
        """Export constraint verification results to CSV"""
        output_file = os.path.join(self.scheduler.output_dir, os.path.basename(output_file))
        
        # Prepare constraint summary data
        constraint_data = []
        
        for i, (constraint, status) in enumerate(constraints_status.items(), 1):
            constraint_data.append([
                i,
                constraint.replace('_', ' ').title(),
                status,
                "✅" if status == 'PASS' else "❌"
            ])
        
        # Calculate summary statistics
        passed = sum(1 for status in constraints_status.values() if status == 'PASS')
        total = len(constraints_status)
        pass_percentage = (passed / total * 100) if total > 0 else 0
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            
            # Header information
            writer.writerow(['Constraint Verification Summary'])
            writer.writerow(['Period:', f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"])
            writer.writerow(['Total Constraints:', total])
            writer.writerow(['Passed:', passed])
            writer.writerow(['Failed:', total - passed])
            writer.writerow(['Pass Rate:', f"{pass_percentage:.1f}%"])
            writer.writerow(['Warnings:', len(self.scheduler.warnings)])
            writer.writerow([])  # Empty row
            
            # Constraint details header
            writer.writerow(['#', 'Constraint', 'Status', 'Symbol'])
            
            # Constraint details
            for row in constraint_data:
                writer.writerow(row)
            
            # Warnings section if any exist
            if self.scheduler.warnings:
                writer.writerow([])  # Empty row
                writer.writerow(['Warnings:'])
                for warning in self.scheduler.warnings:
                    writer.writerow(['', warning])
        
        self.logger.log('export_notifications', 'info', f"Constraint summary exported to {output_file}")
        self.output_files['constraint_summary'] = output_file  # Save for later collection
    
    def export_schedule_json(self, output_file='schedule_output.json'):
        """Export schedule to JSON format"""
        import json
        from datetime import date

        output_file = os.path.join(self.scheduler.output_dir, os.path.basename(output_file))

        # Convert schedule to JSON-serializable format
        json_schedule = {}
        for person_id, person_schedule in self.scheduler.schedule.items():
            json_schedule[person_id] = {}
            for date_obj, shifts in person_schedule.items():
                date_str = date_obj.strftime('%Y-%m-%d')
                json_schedule[person_id][date_str] = shifts

        # --- NEW: Collect extra data ---
        # Tirocinio (internships)
        tirocinio_data = {}
        for person_id, person in self.scheduler.people.items():
            tirocinio_dates = []
            if 'tirocinio_dates' in person:
                tirocinio_dates = [d.strftime('%Y-%m-%d') for d in person['tirocinio_dates']]
            elif 'tirocinio' in person and isinstance(person['tirocinio'], list):
                tirocinio_dates = [
                    (d['date'].strftime('%Y-%m-%d') if isinstance(d, dict) and 'date' in d else str(d))
                    for d in person['tirocinio']
                ]
            tirocinio_data[person_id] = tirocinio_dates

        # Desiderata (forbidden shifts) - ONLY desiderata, NOT ferie, NOT tirocini, ONLY for scheduled dates
        desiderata_data = {}
        # Collect all scheduled dates for each person
        scheduled_dates_by_person = {
            person_id: set([d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
                            for d in person_schedule.keys()])
            for person_id, person_schedule in self.scheduler.schedule.items()
        }
        for person_id, person in self.scheduler.people.items():
            forbidden = []
            scheduled_dates = scheduled_dates_by_person.get(person_id, set())
            # --- Add forbidden shifts as before ---
            for entry in person.get('forbidden_shifts', []):
                if entry and 'date' in entry and 'shifts' in entry:
                    shifts_set = set(entry['shifts'])
                    # Exclude ferie (all 3 shifts forbidden)
                    if shifts_set == {"morning", "afternoon", "night"}:
                        continue
                    # Exclude single 'night' shift on a vacation day
                    vac_dates = [e['date'] for e in person.get('forbidden_shifts', []) if set(e['shifts']) == {"morning", "afternoon", "night"}]
                    if shifts_set == {"night"} and entry['date'] in vac_dates:
                        continue
                    # Only include if date is in the schedule for this person
                    entry_date_str = entry['date'].strftime('%Y-%m-%d') if hasattr(entry['date'], 'strftime') else str(entry['date'])
                    if entry_date_str not in scheduled_dates:
                        continue
                    forbidden.append({
                        'date': entry_date_str,
                        'shifts': entry['shifts']
                    })
            # --- Add forbidden weekends as "weekend" shift ---
            forbidden_weekends = person.get('forbidden_weekends', [])
            for weekend_date in forbidden_weekends:
                weekend_date_str = weekend_date.strftime('%Y-%m-%d') if hasattr(weekend_date, 'strftime') else str(weekend_date)
                if weekend_date_str in scheduled_dates:
                    forbidden.append({
                        'date': weekend_date_str,
                        'shifts': ['weekend']
                    })
            desiderata_data[person_id] = forbidden

        # Vacations (days with all shifts forbidden)
        vacations_data = {}
        for person_id, person in self.scheduler.people.items():
            vacs = []
            for entry in person.get('forbidden_shifts', []):
                if entry and 'date' in entry and 'shifts' in entry and set(entry['shifts']) == {"morning", "afternoon", "night"}:
                    vacs.append(entry['date'].strftime('%Y-%m-%d'))
            vacations_data[person_id] = vacs

        # Holidays (holiday dates)
        holidays_data = [d.strftime('%Y-%m-%d') for d in getattr(self.scheduler, 'holiday_dates', [])]

        # --- NEW: Add statistics (including detailed breakdowns) ---
        from datetime import timedelta
        start_date = min([min(person_schedule.keys()) for person_schedule in self.scheduler.schedule.values()])
        end_date = max([max(person_schedule.keys()) for person_schedule in self.scheduler.schedule.values()])
        staff_stats_list = self._get_staff_statistics_data(start_date, end_date)
        stats_keys = [
            "person_id", "total_hours", "vacation_hours", "morning_shifts", "afternoon_shifts", "mp_shifts", "night_shifts",
            "ferie_days", "tirocinio_days", "weekend_days", "avg_hours_per_week", "night_priority", "weekend_priority",
            "saturday_m", "saturday_p", "saturday_mp", "night_saturday",
            "sunday_m", "sunday_p", "sunday_mp", "night_sunday",
            "holiday_m", "holiday_p", "holiday_mp", "night_holiday"
        ]
        staff_statistics = {}
        for row in staff_stats_list:
            staff_statistics[row[0]] = {k: v for k, v in zip(stats_keys, row)}

        export_data = {
            'schedule': json_schedule,
            'shift_counts': self.scheduler.shift_counts,
            'settings': self.scheduler.settings,
            'warnings': self.scheduler.warnings,
            'required_night_dates': [d.strftime('%Y-%m-%d') for d in self.scheduler.required_night_dates],
            'export_timestamp': str(datetime.now()),
            'people_count': len(self.scheduler.people),
            'total_warnings': len(self.scheduler.warnings),
            'tirocinio': tirocinio_data,
            'desiderata': desiderata_data,
            'vacations': vacations_data,
            'holidays': holidays_data,
            'staff_statistics': staff_statistics
        }

        with open(output_file, 'w', encoding='utf-8') as file:
            json.dump(export_data, file, indent=2, ensure_ascii=False)

        self.logger.log('export_notifications', 'info', f"Schedule exported to JSON: {output_file}")
        self.output_files['json'] = output_file  # Save for later collection
    
    def export_all(self, start_date, end_date, base_filename='schedule'):
        """Export schedule in all available formats"""
        self.logger.log('export_notifications', 'info', "Exporting schedule in all formats...")
        
        # CSV exports
        self.export_schedule_to_csv(f'{base_filename}_output.csv')
        self.export_staff_statistics_to_csv(start_date, end_date, f'{base_filename}_statistics.csv')
        
        # JSON export
        self.export_schedule_json(f'{base_filename}_output.json')
        
        # Constraint summary (if constraints have been verified)
        if hasattr(self.scheduler, 'last_constraint_results'):
            self.export_constraint_summary(
                self.scheduler.last_constraint_results, 
                start_date, 
                end_date, 
                f'{base_filename}_constraints.csv'
            )
        
        # Export shift assignment debug info
        debug_file = f'{base_filename}_debug.csv'
        self.export_assignment_debug(debug_file)
        
        self.logger.log('export_notifications', 'info', "All exports completed successfully!")
        
        # # Collect all output files in a summary dict
        # self.output_files['all'] = {
        #     'csv': self.output_files.get('csv'),
        #     'json': self.output_files.get('json'),
        #     'staff_statistics': self.output_files.get('staff_statistics'),
        #     'multi_run_ranking': self.output_files.get('multi_run_ranking'),
        #     'constraint_summary': self.output_files.get('constraint_summary'),
        #     'debug': os.path.join(self.scheduler.output_dir, debug_file)
        # }

    def export_assignment_debug(self, output_file='assignment_debug.csv'):
        """Export detailed shift assignment failure information"""
        output_path = os.path.join(self.scheduler.output_dir, output_file)
        
        if not hasattr(self.scheduler, 'assignment_failures') or not self.scheduler.assignment_failures:
            self.scheduler.logger.log('export_notifications', 'info', 
                                    f"No assignment failures to export")
            return
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Header
                writer.writerow([
                    'Date', 'Day of Week', 'Shift Type', 'Person ID', 
                    'Failure Reasons', 'Reason Count'
                ])
                
                # Sort failures by date, then by shift type
                sorted_failures = sorted(self.scheduler.assignment_failures, 
                                       key=lambda x: (x['date'], x['shift_type'], x['person_id']))
                
                for failure in sorted_failures:
                    day_of_week = failure['date'].strftime('%A')
                    reason_text = '; '.join(failure['reasons'])
                    reason_count = len(failure['reasons'])
                    
                    writer.writerow([
                        failure['date'].strftime('%d/%m/%Y'),
                        day_of_week,
                        failure['shift_type'],
                        failure['person_id'],
                        reason_text,
                        reason_count
                    ])
                
                # Add summary section
                writer.writerow([])  # Empty row
                writer.writerow(['=== SUMMARY ==='])
                writer.writerow(['Total Failures', len(self.scheduler.assignment_failures)])
                
                # Reason frequency analysis
                reason_counts = {}
                for failure in self.scheduler.assignment_failures:
                    for reason in failure['reasons']:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                
                writer.writerow([])
                writer.writerow(['Failure Reason', 'Frequency'])
                for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
                    writer.writerow([reason, count])
            
            self.scheduler.logger.log('export_notifications', 'info', 
                                    f"📊 Assignment debug exported to {output_file} ({len(self.scheduler.assignment_failures)} failures)")
            self.output_files['debug'] = output_path  # Save for later collection
        except Exception as e:
            self.scheduler.logger.log('export_notifications', 'error', 
                                    f"❌ Failed to export assignment debug: {e}")
            self.output_files['debug'] = None

    def export_schedule_docx(self, docx_file=None, json_file=None):
        """
        Export the schedule to a DOCX file using ScheduleDocxCreator.
        Saves the DOCX filename in self.output_files['docx'].
        """
        from doc_creator import ScheduleDocxCreator

        # Determine file paths
        output_dir = self.scheduler.output_dir
        docx_file = docx_file or os.path.join(output_dir, "schedule_output.docx")
        json_file = json_file or os.path.join(output_dir, "schedule_output.json")

        # Ensure JSON exists (export if not)
        if not os.path.exists(json_file):
            self.export_schedule_json(json_file)

        # Create DOCX
        try:
            creator = ScheduleDocxCreator(
                json_path=json_file,
                doc_path=docx_file
                # Optionally add more settings here if needed
            )
            creator.create_doc()
            self.logger.log('export_notifications', 'info', f"DOCX exported to {docx_file}")
            self.output_files['docx'] = docx_file  # Save for later collection
        except Exception as e:
            self.logger.log('export_notifications', 'error', f"❌ DOCX export failed: {e}")
            self.output_files['docx'] = None

    def _is_person_on_vacation(self, person_id: str, date) -> bool:
        """Check if a person is on vacation on a specific date"""
        person_data = self.scheduler.people[person_id]
        
        for forbidden in person_data.get('forbidden_shifts', []):
            if forbidden and forbidden['date'] == date:
                # Check if this is a vacation day (all MPN shifts forbidden)
                if len(forbidden['shifts']) == 3 and all(s in forbidden['shifts'] for s in ['morning', 'afternoon', 'night']):
                    return True
        
        return False
    
    def _get_forbidden_shifts_for_date(self, person_id: str, date) -> List[str]:
        """Get forbidden shift types for a person on a specific date (excluding vacation days)"""
        person_data = self.scheduler.people[person_id]
        forbidden_types = []
        
        for forbidden in person_data.get('forbidden_shifts', []):
            if forbidden and forbidden['date'] == date:
                # Skip vacation days (all MPN shifts forbidden)
                if len(forbidden['shifts']) == 3 and all(s in forbidden['shifts'] for s in ['morning', 'afternoon', 'night']):
                    continue  # This is handled by vacation logic
                
                # Convert shift names to display codes
                shift_codes = []
                for shift_type in forbidden['shifts']:
                    if shift_type == 'morning':
                        shift_codes.append('M')
                    elif shift_type == 'afternoon':
                        shift_codes.append('P')
                    elif shift_type == 'night':
                        shift_codes.append('N')
                
                if shift_codes:
                    forbidden_types.extend(shift_codes)
        
        # Remove duplicates and sort for consistent display
        return sorted(list(set(forbidden_types)))
        
    def _is_person_in_tirocinio(self, person_id: str, date) -> bool:
        """Check if a person is in tirocinio (training) on a specific date"""
        person_data = self.scheduler.people[person_id]
        
        # Check if person has tirocinio_dates field (used by shift assignment logic)
        if 'tirocinio_dates' in person_data:
            tirocinio_dates = person_data['tirocinio_dates']
            if isinstance(tirocinio_dates, list):
                return date in tirocinio_dates
            elif isinstance(tirocinio_dates, set):
                return date in tirocinio_dates
        
        # Legacy check - look for tirocinio field in the person data
        tirocinio_data = person_data.get('tirocinio', person_data.get('Tirocinio', ''))
        
        if not tirocinio_data:
            return False
        
        # If tirocinio_data is a string of dates (similar to vacation format)
        if isinstance(tirocinio_data, str):
            # Parse tirocinio dates similar to vacation dates
            tirocinio_shifts = self._parse_tirocinio_dates(tirocinio_data)
            for tirocinio in tirocinio_shifts:
                if tirocinio and tirocinio['date'] == date:
                    return True
        
        # If tirocinio_data is already a list of date objects or dictionaries
        elif isinstance(tirocinio_data, list):
            for tirocinio in tirocinio_data:
                if tirocinio:
                    # Handle different formats: date objects, dictionaries with date field
                    tirocinio_date = None
                    if hasattr(tirocinio, 'date') or isinstance(tirocinio, dict):
                        tirocinio_date = tirocinio.get('date') if isinstance(tirocinio, dict) else tirocinio.date
                    elif hasattr(tirocinio, 'year'):  # Direct date object
                        tirocinio_date = tirocinio
                    
                    if tirocinio_date == date:
                        return True
        
        return False
    
    def _parse_tirocinio_dates(self, tirocinio_str):
        """Parse tirocinio dates string and convert to date objects"""
        from datetime import datetime, timedelta
        
        tirocinio_dates = []
        
        # Split by comma and parse each date
        date_strings = [d.strip() for d in tirocinio_str.split(',') if d.strip()]
        
        for date_str in date_strings:
            # Try to parse the date
            tirocinio_date = None
            try:
                # Try DD/MM/YYYY format first
                tirocinio_date = datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
            except ValueError:
                try:
                    # Try YYYY-MM-DD format
                    tirocinio_date = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
                except ValueError:
                    # Skip invalid date formats
                    continue
            
            if tirocinio_date:
                tirocinio_dates.append({'date': tirocinio_date})
        
        return tirocinio_dates
    
    def _is_prohibited_weekend(self, person_id: str, date) -> bool:
        """Check if a person has prohibited weekend on a specific date"""
        # Only check for weekends (Saturday = 5, Sunday = 6)
        if date.weekday() < 5:
            return False
            
        person_data = self.scheduler.people[person_id]
        
        # Check if person has forbidden_weekends field (not prohibited_weekends)
        forbidden_weekends = person_data.get('forbidden_weekends', [])
        
        if not forbidden_weekends:
            return False
        
        # Check if this date is in the forbidden weekends list
        # The data loader stores forbidden weekends as a list of date objects
        for forbidden_date in forbidden_weekends:
            if forbidden_date == date:
                return True
            
            # Also check if this date falls within a weekend that contains the forbidden date
            # If forbidden_date is Saturday, also check Sunday of same weekend
            # If forbidden_date is Sunday, also check Saturday of same weekend
            if date.weekday() == 5:  # Current date is Saturday
                # Check if Sunday of this weekend is forbidden
                sunday = date + timedelta(days=1)
                if forbidden_date == sunday:
                    return True
            elif date.weekday() == 6:  # Current date is Sunday
                # Check if Saturday of this weekend is forbidden
                saturday = date - timedelta(days=1)
                if forbidden_date == saturday:
                    return True
        
        return False

    def save_all_data(self, output_folder):
        """Save all input files, settings, output files, and logs to a specified folder."""
        # Get the current date in YYYY-MM-DD format
        current_date = datetime.now().strftime('%Y-%m-%d-%H%M%S')
        date_folder = os.path.join(output_folder, current_date)  # Create a subfolder with the date

        os.makedirs(date_folder, exist_ok=True)

        # Save input files
        input_files = [
            self.scheduler.settings['data_files']['people_data_file'],
            self.scheduler.settings['data_files']['night_dates_file'],
            self.scheduler.settings['data_files']['holiday_dates_file']
        ]
        for file in input_files:
            if os.path.exists(file):
                shutil.copy(file, date_folder)  # Save to the date subfolder

        # Save settings
        settings_file = os.path.join(date_folder, 'settings.json')
        with open(settings_file, 'w') as f:
            json.dump(self.scheduler.settings, f, indent=2)

        # Save output files using self.output_files
        for key, file_path in self.output_files.items():
            if not file_path:
                continue
            # If it's a dict (e.g. self.output_files['all']), iterate its values
            if isinstance(file_path, dict):
                for subkey, subfile in file_path.items():
                    if subfile and os.path.exists(subfile):
                        shutil.copy(subfile, date_folder)
            else:
                if os.path.exists(file_path):
                    shutil.copy(file_path, date_folder)

        # Save multi_run_ranking.csv from self.output_files if present
        multi_run_ranking_path = self.output_files.get('multi_run_ranking')
        if multi_run_ranking_path and os.path.exists(multi_run_ranking_path):
            shutil.copy(multi_run_ranking_path, date_folder)

        # Save logs
        log_file = os.path.join(date_folder, 'scheduler_log.txt')
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as f:  # Specify utf-8 encoding
            for entry in self.logger.get_all_logs():
                f.write(f"[{entry['level'].upper()}] [{entry['category']}] {entry['message']}\n")

        self.logger.log('export_notifications', 'info', f"All data saved to {date_folder}")
