from datetime import timedelta

class ConstraintVerifier:
    def __init__(self, scheduler):
        """Initialize with reference to main scheduler for accessing settings, people, schedule, etc."""
        self.scheduler = scheduler
        self.logger = scheduler.logger
    
    def verify_constraints(self, start_date, end_date):
        """Comprehensive constraint verification with pass/not-pass for each constraint"""
        self.logger.log('constraint_verification', 'info', "\n" + "="*80)
        self.logger.log('constraint_verification', 'info', "CONSTRAINT VERIFICATION")
        self.logger.log('constraint_verification', 'info', "="*80)
        
        all_dates = []
        current_date = start_date
        while current_date <= end_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)
        
        total_weeks = len(all_dates) / 7
        constraints_status = {}
        
        # Run all constraint checks
        constraints_status.update(self._check_morning_staff_weekdays(all_dates))
        constraints_status.update(self._check_saturday_morning_staff(all_dates))
        constraints_status.update(self._check_max_afternoon_staff(all_dates))
        constraints_status.update(self._check_sunday_mp_staff(all_dates))
        constraints_status.update(self._check_night_coverage(all_dates, start_date, end_date))
        constraints_status.update(self._check_monthly_night_limits(all_dates))
        constraints_status.update(self._check_weekly_hours(all_dates, total_weeks))
        constraints_status.update(self._check_max_consecutive_days(all_dates))
        constraints_status.update(self._check_night_rest_periods(all_dates))
        constraints_status.update(self._check_weekend_days_per_month(all_dates))
        constraints_status.update(self._check_forbidden_shifts(all_dates))
        constraints_status.update(self._check_vacation_compliance(all_dates))
        constraints_status.update(self._check_night_availability(all_dates))
        constraints_status.update(self._check_weekday_morning_coverage(all_dates))
        constraints_status.update(self._check_weekday_afternoon_coverage(all_dates))
        constraints_status.update(self._check_weekend_coverage(all_dates))
        
        # Summary
        self._print_summary(constraints_status)
        
        return constraints_status
    
    def _check_morning_staff_weekdays(self, all_dates):
        """Check minimum morning staff (weekdays)"""
        self.logger.log('constraint_verification', 'info', "\n1. MINIMUM MORNING STAFF (WEEKDAYS)")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        morning_violations = []
        for date in all_dates:
            if date.weekday() < 5:  # Weekday
                morning_staff = sum(1 for person_id in self.scheduler.people.keys() 
                                  if 'morning' in self.scheduler.schedule[person_id].get(date, []))
                required = self.scheduler.settings['min_morning_staff']
                if morning_staff < required:
                    morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if morning_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in morning_violations[:5]:  # Show first 5
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            if len(morning_violations) > 5:
                self.logger.log('constraint_verification', 'debug', f"   ... and {len(morning_violations) - 5} more violations")
            return {'morning_staff_weekdays': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'morning_staff_weekdays': 'PASS'}
    
    def _check_saturday_morning_staff(self, all_dates):
        """Check Saturday morning staff"""
        self.logger.log('constraint_verification', 'info', "\n2. SATURDAY MORNING STAFF")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        saturday_morning_violations = []
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                morning_staff = sum(1 for person_id in self.scheduler.people.keys() 
                                  if 'morning' in self.scheduler.schedule[person_id].get(date, []))
                required = self.scheduler.settings.get('saturday_morning_staff', 2)
                if morning_staff < required:
                    saturday_morning_violations.append(f"{date}: {morning_staff} staff (need {required})")
        
        if saturday_morning_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in saturday_morning_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'saturday_morning_staff': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'saturday_morning_staff': 'PASS'}
    
    def _check_max_afternoon_staff(self, all_dates):
        """Check afternoon staff (max 1)"""
        self.logger.log('constraint_verification', 'info', "\n3. MAXIMUM AFTERNOON STAFF")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        afternoon_violations = []
        for date in all_dates:
            if date.weekday() < 6:  # Not Sunday (Sunday has MP shift)
                afternoon_staff = sum(1 for person_id in self.scheduler.people.keys() 
                                    if 'afternoon' in self.scheduler.schedule[person_id].get(date, []))
                max_allowed = self.scheduler.settings['max_afternoon_staff']
                if afternoon_staff > max_allowed:
                    afternoon_violations.append(f"{date}: {afternoon_staff} staff (max {max_allowed})")
        
        if afternoon_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in afternoon_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'max_afternoon_staff': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'max_afternoon_staff': 'PASS'}
    
    def _check_sunday_mp_staff(self, all_dates):
        """Check Sunday MP staff"""
        self.logger.log('constraint_verification', 'info', "\n4. SUNDAY MP STAFF")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        sunday_violations = []
        for date in all_dates:
            if date.weekday() == 6:  # Sunday
                mp_staff = sum(1 for person_id in self.scheduler.people.keys() 
                             if 'mp' in self.scheduler.schedule[person_id].get(date, []))
                required = self.scheduler.settings.get('sunday_staff', 1)
                if mp_staff != required:
                    sunday_violations.append(f"{date}: {mp_staff} staff (need exactly {required})")
        
        if sunday_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in sunday_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'sunday_mp_staff': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'sunday_mp_staff': 'PASS'}
    
    def _check_night_coverage(self, all_dates, start_date, end_date):
        """Check required night shifts coverage"""
        self.logger.log('constraint_verification', 'info', "\n5. REQUIRED NIGHT SHIFTS COVERAGE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        night_coverage_violations = []
        required_nights_in_period = [d for d in self.scheduler.required_night_dates if start_date <= d <= end_date]
        
        for night_date in required_nights_in_period:
            night_staff = sum(1 for person_id in self.scheduler.people.keys() 
                            if 'night' in self.scheduler.schedule[person_id].get(night_date, []))
            if night_staff != 1:
                night_coverage_violations.append(f"{night_date}: {night_staff} staff (need exactly 1)")
        
        if night_coverage_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_coverage_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'night_coverage': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'night_coverage': 'PASS'}
    
    def _check_monthly_night_limits(self, all_dates):
        """Check monthly night shift limits"""
        self.logger.log('constraint_verification', 'info', "\n6. MONTHLY NIGHT SHIFT LIMITS")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        monthly_night_violations = []
        months_in_period = set((date.year, date.month) for date in all_dates)
        
        for person_id in self.scheduler.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                night_shifts_this_month = 0
                
                for date in month_dates:
                    if 'night' in self.scheduler.schedule[person_id].get(date, []):
                        night_shifts_this_month += 1
                
                if night_shifts_this_month > self.scheduler.settings['night_shifts_per_month']:
                    monthly_night_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {night_shifts_this_month} night shifts (max {self.scheduler.settings['night_shifts_per_month']})")
        
        if monthly_night_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in monthly_night_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'monthly_night_limits': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'monthly_night_limits': 'PASS'}
    
    def _check_weekly_hours(self, all_dates, total_weeks):
        """Check weekly hours (34-48h)"""
        self.logger.log('constraint_verification', 'info', "\n7. WEEKLY HOURS (34-48h)")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        weekly_hours_violations = []
        
        for person_id in self.scheduler.people.keys():
            total_hours = 0
            for date in all_dates:
                for shift in self.scheduler.schedule[person_id][date]:
                    if shift == 'morning':
                        total_hours += self.scheduler.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        total_hours += self.scheduler.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += self.scheduler.settings['night_shift_hours']
            
            avg_weekly = total_hours / total_weeks if total_weeks > 0 else 0
            
            if avg_weekly < self.scheduler.settings['min_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (below {self.scheduler.settings['min_weekly_hours']}h)")
            elif avg_weekly > self.scheduler.settings['max_weekly_hours']:
                weekly_hours_violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (above {self.scheduler.settings['max_weekly_hours']}h)")
        
        if weekly_hours_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekly_hours_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'weekly_hours': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'weekly_hours': 'PASS'}
    
    def _check_max_consecutive_days(self, all_dates):
        """Check maximum consecutive days"""
        self.logger.log('constraint_verification', 'info', "\n8. MAXIMUM CONSECUTIVE DAYS")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        consecutive_violations = []
        
        for person_id in self.scheduler.people.keys():
            consecutive_days = 0
            max_consecutive = 0
            
            for date in all_dates:
                if self.scheduler.schedule[person_id][date] and 'rest_after_night' not in self.scheduler.schedule[person_id][date]:
                    consecutive_days += 1
                    max_consecutive = max(max_consecutive, consecutive_days)
                else:
                    consecutive_days = 0
            
            if max_consecutive > self.scheduler.settings['max_consecutive_days']:
                consecutive_violations.append(f"Person {person_id}: {max_consecutive} consecutive days (max {self.scheduler.settings['max_consecutive_days']})")
        
        if consecutive_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in consecutive_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'max_consecutive_days': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'max_consecutive_days': 'PASS'}
    
    def _check_night_rest_periods(self, all_dates):
        """Check night shift rest periods"""
        self.logger.log('constraint_verification', 'info', "\n9. NIGHT SHIFT REST PERIODS")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        night_rest_violations = []
        
        for person_id in self.scheduler.people.keys():
            for date in all_dates:
                if 'night' in self.scheduler.schedule[person_id].get(date, []):
                    # Check same day: no other shifts allowed on the night shift day
                    same_day_shifts = [shift for shift in self.scheduler.schedule[person_id].get(date, []) 
                                     if shift != 'night' and shift != 'rest_after_night']
                    if same_day_shifts:
                        night_rest_violations.append(f"Person {person_id}: has {', '.join(same_day_shifts)} shift(s) on same day as night shift {date}")
                    
                    # Check day after: must be completely free (should be marked as rest)
                    next_date = date + timedelta(days=1)
                    if next_date in all_dates:
                        next_shifts = self.scheduler.schedule[person_id].get(next_date, [])
                        # The day after should either be empty or contain only 'rest_after_night'
                        working_shifts = [shift for shift in next_shifts if shift != 'rest_after_night']
                        if working_shifts:
                            night_rest_violations.append(f"Person {person_id}: worked {next_date} after night on {date} (shifts: {', '.join(working_shifts)})")
        
        if night_rest_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_rest_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'night_rest_periods': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'night_rest_periods': 'PASS'}
    
    def _check_weekend_days_per_month(self, all_dates):
        """Check weekend days per month"""
        self.logger.log('constraint_verification', 'info', "\n10. WEEKEND DAYS PER MONTH")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        weekend_violations = []
        months_in_period = set((date.year, date.month) for date in all_dates)
        
        for person_id in self.scheduler.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                weekend_days_worked = 0
                
                for date in month_dates:
                    if date.weekday() >= 5 and self.scheduler.schedule[person_id].get(date, []):
                        day_shifts = self.scheduler.schedule[person_id][date]
                        # Only count weekend days with non-night shifts (excluding rest days)
                        non_night_shifts = [s for s in day_shifts if s not in ['night', 'rest_after_night']]
                        if non_night_shifts:  # Has morning, afternoon, or mp shifts
                            weekend_days_worked += 1
                
                if weekend_days_worked > self.scheduler.settings['max_weekend_days_per_month']:
                    weekend_violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {weekend_days_worked} weekend days (max {self.scheduler.settings['max_weekend_days_per_month']})")
        
        if weekend_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekend_violations[:5]:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            if len(weekend_violations) > 5:
                self.logger.log('constraint_verification', 'debug', f"   ... and {len(weekend_violations) - 5} more violations")
            return {'weekend_days_per_month': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'weekend_days_per_month': 'PASS'}
    
    def _check_forbidden_shifts(self, all_dates):
        """Check forbidden shifts compliance"""
        self.logger.log('constraint_verification', 'info', "\n11. FORBIDDEN SHIFTS COMPLIANCE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        forbidden_violations = []
        
        for person_id in self.scheduler.people.keys():
            person_data = self.scheduler.people[person_id]
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.scheduler.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                forbidden_violations.append(f"Person {person_id}: assigned forbidden {forbidden_shift} on {date}")
        
        if forbidden_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in forbidden_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'forbidden_shifts': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'forbidden_shifts': 'PASS'}
    
    def _check_vacation_compliance(self, all_dates):
        """Check vacation (Ferie) compliance"""
        self.logger.log('constraint_verification', 'info', "\n12. VACATION (FERIE) COMPLIANCE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        vacation_violations = []
        
        for person_id in self.scheduler.people.keys():
            person_data = self.scheduler.people[person_id]
            # Check all forbidden shifts to identify vacation-related violations
            for forbidden in person_data['forbidden_shifts']:
                if forbidden:
                    date = forbidden['date']
                    if date in all_dates:
                        assigned_shifts = self.scheduler.schedule[person_id].get(date, [])
                        for forbidden_shift in forbidden['shifts']:
                            if forbidden_shift in assigned_shifts:
                                # Check if this is a vacation-related constraint
                                if len(forbidden['shifts']) == 3 and all(s in forbidden['shifts'] for s in ['morning', 'afternoon', 'night']):
                                    # This is a vacation day (MPN all forbidden)
                                    vacation_violations.append(f"Person {person_id}: assigned {forbidden_shift} on vacation day {date}")
                                elif forbidden['shifts'] == ['night'] and len([f for f in person_data['forbidden_shifts'] 
                                    if f and f['date'] == date + timedelta(days=1) and len(f['shifts']) == 3]) > 0:
                                    # This is a night shift before vacation day
                                    vacation_violations.append(f"Person {person_id}: assigned night shift on {date} (night before vacation)")
        
        if vacation_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in vacation_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'vacation_compliance': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'vacation_compliance': 'PASS'}
    
    def _check_night_availability(self, all_dates):
        """Check night shift availability compliance"""
        self.logger.log('constraint_verification', 'info', "\n13. NIGHT SHIFT AVAILABILITY COMPLIANCE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        night_availability_violations = []
        
        for person_id in self.scheduler.people.keys():
            person_data = self.scheduler.people[person_id]
            if not person_data['night_available']:
                # Check if this person was assigned any night shifts
                for date in all_dates:
                    if 'night' in self.scheduler.schedule[person_id].get(date, []):
                        night_availability_violations.append(f"Person {person_id}: assigned night shift on {date} but not available for nights")
        
        if night_availability_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in night_availability_violations:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            return {'night_availability': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'night_availability': 'PASS'}
    
    def _check_weekday_morning_coverage(self, all_dates):
        """Check weekday morning shift coverage"""
        self.logger.log('constraint_verification', 'info', "\n14. WEEKDAY MORNING SHIFT COVERAGE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        weekday_morning_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                morning_staff = sum(1 for person_id in self.scheduler.people.keys() 
                                  if 'morning' in self.scheduler.schedule[person_id].get(date, []))
                required = self.scheduler.settings['min_morning_staff']
                if morning_staff < required:
                    weekday_morning_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {morning_staff}/{required} morning staff")
        
        if weekday_morning_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekday_morning_violations[:5]:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            if len(weekday_morning_violations) > 5:
                self.logger.log('constraint_verification', 'debug', f"   ... and {len(weekday_morning_violations) - 5} more violations")
            return {'weekday_morning_coverage': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'weekday_morning_coverage': 'PASS'}
    
    def _check_weekday_afternoon_coverage(self, all_dates):
        """Check weekday afternoon shift coverage"""
        self.logger.log('constraint_verification', 'info', "\n15. WEEKDAY AFTERNOON SHIFT COVERAGE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        weekday_afternoon_violations = []
        
        for date in all_dates:
            if date.weekday() < 5:  # Monday-Friday
                afternoon_staff = sum(1 for person_id in self.scheduler.people.keys() 
                                    if 'afternoon' in self.scheduler.schedule[person_id].get(date, []))
                required = self.scheduler.settings['max_afternoon_staff']  # This acts as target coverage
                if afternoon_staff != required:
                    weekday_afternoon_violations.append(f"{date.strftime('%d/%m/%Y')} ({date.strftime('%A')}): {afternoon_staff}/{required} afternoon staff")
        
        if weekday_afternoon_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekday_afternoon_violations[:5]:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            if len(weekday_afternoon_violations) > 5:
                self.logger.log('constraint_verification', 'debug', f"   ... and {len(weekday_afternoon_violations) - 5} more violations")
            return {'weekday_afternoon_coverage': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'weekday_afternoon_coverage': 'PASS'}
    
    def _check_weekend_coverage(self, all_dates):
        """Check weekend shift coverage"""
        self.logger.log('constraint_verification', 'info', "\n16. WEEKEND SHIFT COVERAGE")
        self.logger.log('constraint_verification', 'info', "-" * 40)
        
        weekend_coverage_violations = []
        
        for date in all_dates:
            if date.weekday() == 5:  # Saturday
                saturday_morning = sum(1 for person_id in self.scheduler.people.keys() 
                                     if 'morning' in self.scheduler.schedule[person_id].get(date, []))
                saturday_afternoon = sum(1 for person_id in self.scheduler.people.keys() 
                                       if 'afternoon' in self.scheduler.schedule[person_id].get(date, []))
                
                required_morning = self.scheduler.settings.get('saturday_morning_staff', 0)
                required_afternoon = self.scheduler.settings.get('saturday_afternoon_staff', 0)
                
                if saturday_morning != required_morning:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_morning}/{required_morning} morning staff")
                if saturday_afternoon != required_afternoon:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Saturday): {saturday_afternoon}/{required_afternoon} afternoon staff")
                    
            elif date.weekday() == 6:  # Sunday
                sunday_mp = sum(1 for person_id in self.scheduler.people.keys() 
                              if 'mp' in self.scheduler.schedule[person_id].get(date, []))
                required_mp = self.scheduler.settings.get('sunday_staff', 1)
                
                if sunday_mp != required_mp:
                    weekend_coverage_violations.append(f"{date.strftime('%d/%m/%Y')} (Sunday): {sunday_mp}/{required_mp} MP staff")
        
        if weekend_coverage_violations:
            self.logger.log('constraint_verification', 'info', "❌ FAIL")
            for violation in weekend_coverage_violations[:5]:
                self.logger.log('constraint_verification', 'debug', f"   {violation}")
            if len(weekend_coverage_violations) > 5:
                self.logger.log('constraint_verification', 'debug', f"   ... and {len(weekend_coverage_violations) - 5} more violations")
            return {'weekend_coverage': 'FAIL'}
        else:
            self.logger.log('constraint_verification', 'info', "✅ PASS")
            return {'weekend_coverage': 'PASS'}
    
    def _print_summary(self, constraints_status):
        """Print constraint verification summary"""
        self.logger.log('constraint_verification', 'info', "\n" + "="*80)
        self.logger.log('constraint_verification', 'info', "CONSTRAINT VERIFICATION SUMMARY")
        self.logger.log('constraint_verification', 'info', "="*80)
        
        passed = sum(1 for status in constraints_status.values() if status == 'PASS')
        total = len(constraints_status)
        
        if self.scheduler._should_log('constraint_verification', 'info'):
            for i, (constraint, status) in enumerate(constraints_status.items(), 1):
                status_symbol = "✅" if status == 'PASS' else "❌"
                print(f"{i:2}. {constraint.replace('_', ' ').title():<30} {status_symbol} {status}")
        
        self.logger.log('constraint_verification', 'info', f"\nOVERALL: {passed}/{total} constraints passed")
        
        if self.scheduler.warnings:
            self.logger.log('constraint_verification', 'info', f"⚠️  {len(self.scheduler.warnings)} SCHEDULING WARNINGS")
        
        if passed == total and not self.scheduler.warnings:
            self.logger.log('constraint_verification', 'info', "🎉 ALL CONSTRAINTS SATISFIED WITH NO WARNINGS!")
        elif passed == total:
            self.logger.log('constraint_verification', 'info', "✅ ALL CONSTRAINTS SATISFIED (with warnings)")
        else:
            self.logger.log('constraint_verification', 'info', f"⚠️  {total - passed} CONSTRAINT(S) VIOLATED")
        
        self.logger.log('constraint_verification', 'info', "="*80)
