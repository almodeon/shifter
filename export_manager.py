import csv
import os
from datetime import timedelta, datetime

class ExportManager:
    def __init__(self, scheduler):
        """Initialize with reference to main scheduler for accessing settings, people, schedule, etc."""
        self.scheduler = scheduler
        self.logger = scheduler.logger
    
    def export_schedule_to_csv(self, output_file):
        """Export schedule to CSV file (transposed format) with warnings column"""
        # Ensure the output file is in the output directory
        output_file = os.path.join(self.scheduler.output_dir, os.path.basename(output_file))
        
        # Prepare data for CSV
        all_dates = set()
        
        for person_schedule in self.scheduler.schedule.values():
            all_dates.update(person_schedule.keys())
        
        all_dates = sorted(list(all_dates))
        
        # Create header: Date, Day, Festivity, Night_Coverage, Morning Count, Afternoon Count, Night Count, Warnings, then person columns
        people_ids = sorted(self.scheduler.people.keys())
        header = ['Date', 'Day', 'Festivity', 'Night_Coverage', 'Morning_Staff', 'Afternoon_Staff', 'Night_Staff', 'Warnings'] + people_ids
        
        rows = [header]
        
        # Add data for each date
        for date in all_dates:
            day_name = date.strftime('%A')
            
            # Check if this is a festivity day
            is_festivity = date in self.scheduler.festivity_dates
            festivity_marker = '*' if is_festivity else ''
            
            # Check if night coverage is required on this date
            is_night_required = date in self.scheduler.required_night_dates
            night_coverage_marker = '*' if is_night_required else ''
            
            # Count staff for each shift type on this date
            morning_count = 0
            afternoon_count = 0
            night_count = 0
            
            # Prepare person data for this date
            person_data = []
            
            for person_id in people_ids:
                shifts = self.scheduler.schedule[person_id].get(date, [])
                
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
            date_warnings = [w for w in self.scheduler.warnings if date.strftime('%d/%m/%Y') in w]
            warnings_str = "; ".join(date_warnings) if date_warnings else ""
            
            # Create row: Date, Day, Festivity, Night_Coverage, Staff counts, Warnings, then person shifts
            row = [
                date.strftime('%d/%m/%Y'),
                day_name,
                festivity_marker,
                night_coverage_marker,
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
        
        self.logger.log('export_notifications', 'info', f"Schedule exported to {output_file}")
    
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
            # Count shifts from schedule
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
                
                # Count each shift type and calculate hours from shifts
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
            
            # Calculate vacation hours (weekday vacation days count as morning shift hours)
            vacation_hours = 0
            person_data = self.scheduler.people[person_id]
            for forbidden in person_data['forbidden_shifts']:
                if forbidden and len(forbidden['shifts']) == 3:
                    # This is a vacation day (all MPN shifts forbidden)
                    vacation_date = forbidden['date']
                    if vacation_date in all_dates and vacation_date.weekday() < 5:  # Monday-Friday only
                        vacation_hours += self.scheduler.settings['morning_shift_hours']
            
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
        
        self.logger.log('export_notifications', 'info', f"Staff statistics exported to {output_file}")
        return staff_data
    
    def export_multi_run_ranking(self, sorted_runs):
        """Export multi-run ranking to CSV"""
        ranking_file = os.path.join(self.scheduler.output_dir, 'multi_run_ranking.csv')
        
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
        
        self.logger.log('export_notifications', 'info', f"Detailed ranking exported to: {ranking_file}")
    
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
                # Convert date to string for JSON serialization
                date_str = date_obj.strftime('%Y-%m-%d')
                json_schedule[person_id][date_str] = shifts
        
        # Prepare complete export data
        export_data = {
            'schedule': json_schedule,
            'shift_counts': self.scheduler.shift_counts,
            'settings': self.scheduler.settings,
            'warnings': self.scheduler.warnings,
            'required_night_dates': [d.strftime('%Y-%m-%d') for d in self.scheduler.required_night_dates],
            'export_timestamp': str(datetime.now()),
            'people_count': len(self.scheduler.people),
            'total_warnings': len(self.scheduler.warnings)
        }
        
        # Write to JSON file
        with open(output_file, 'w', encoding='utf-8') as file:
            json.dump(export_data, file, indent=2, ensure_ascii=False)
        
        self.logger.log('export_notifications', 'info', f"Schedule exported to JSON: {output_file}")
    
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
        
        self.logger.log('export_notifications', 'info', "All exports completed successfully!")
