import random
from datetime import datetime, timedelta
from collections import defaultdict

class ShiftAssigner:
    def __init__(self, scheduler):
        """Initialize with reference to main scheduler for accessing settings, people, etc."""
        self.scheduler = scheduler
        self.logger = scheduler.logger  # Reference to the scheduler's logger
        self.afternoon_targets = {}
    
    def assign_shifts_balanced(self, dates):
        """Balanced shift assignment algorithm - never relax constraints"""
        people_list = list(self.scheduler.people.keys())
        
        # NEW: Option 1 - Randomize people order at start of scheduling
        if self.scheduler.settings.get('randomize_people_order', False):
            random.shuffle(people_list)
            self.logger.log('night_shift_assignment', 'debug', f"Randomized people order: {people_list}")
        
        # First pass: assign night shifts to ensure everyone gets exactly the required amount
        self.assign_night_shifts_first(dates, people_list)
        
        # Pre-calculate afternoon targets after night shifts are assigned (for workload balancing)
        if self.scheduler.settings['workload_balancing']['enabled']:
            self.afternoon_targets = {}
            for person_id in people_list:
                self.afternoon_targets[person_id] = self.calculate_adjusted_afternoon_target(person_id)
                self.logger.log('workload_balancing', 'debug', f"Person {person_id} afternoon target: {self.afternoon_targets[person_id]:.1f}")
        
        # Log weekend priority settings
        if self.scheduler.settings['priority_assignment']['weekend_priority_enabled']:
            self.logger.log('weekend_shift_balancing', 'info', "Weekend priority assignment: ENABLED (strict priority)")
            weekend_priorities = {}
            for person_id in people_list:
                priority = self.scheduler.people[person_id].get('weekend_priority', 0)
                if priority not in weekend_priorities:
                    weekend_priorities[priority] = []
                weekend_priorities[priority].append(person_id)
            
            for priority in sorted(weekend_priorities.keys(), reverse=True):
                self.logger.log('weekend_shift_balancing', 'info', f"  Weekend priority {priority}: {weekend_priorities[priority]}")
        else:
            self.logger.log('weekend_shift_balancing', 'info', "Weekend priority assignment: DISABLED")
        
        # Second pass: assign morning and afternoon shifts
        for date in dates:
            is_weekend = date.weekday() >= 5  # Saturday = 5, Sunday = 6
            is_festivity = date in self.scheduler.festivity_dates
            
            if is_festivity:
                # Festivity days have only MP shift - skip all other shift types
                shifts_needed = ['mp']
                self.logger.log('shift_assignment_warnings', 'info', f"Festivity day {date}: scheduling MP shift only")
            elif is_weekend:
                if date.weekday() == 6:  # Sunday
                    # Sunday has only MP (morning+afternoon combined) shift
                    shifts_needed = ['mp']  # Special MP shift for Sunday
                else:  # Saturday
                    # Saturday has morning, optional afternoon, and optional MP shifts
                    shifts_needed = ['morning', 'afternoon', 'mp']
            else:
                # Weekday shifts: morning, afternoon (night already assigned)
                shifts_needed = ['morning', 'afternoon']
            
            for shift in shifts_needed:
                if shift == 'morning':
                    # Skip morning assignment if this is a festivity day
                    if is_festivity:
                        continue
                    if date.weekday() == 5:  # Saturday
                        required_people = self.scheduler.settings.get('saturday_morning_staff', 1)
                    elif date.weekday() == 6:  # Sunday - no separate morning
                        continue
                    else:  # Weekday
                        required_people = self.scheduler.settings['min_morning_staff']
                elif shift == 'afternoon':
                    # Skip afternoon assignment if this is a festivity day
                    if is_festivity:
                        continue
                    if date.weekday() == 5:  # Saturday
                        required_people = self.scheduler.settings.get('saturday_afternoon_staff', 0)
                    elif date.weekday() == 6:  # Sunday - no separate afternoon
                        continue
                    else:  # Weekday
                        required_people = self.scheduler.settings['max_afternoon_staff']
                elif shift == 'mp':  # Saturday MP, Sunday MP shift or festivity MP shift
                    if date.weekday() == 5:  # Saturday MP
                        required_people = self.scheduler.settings.get('saturday_mp_staff', 1)
                    elif is_festivity:
                        required_people = self.scheduler.settings.get('festivity_staff', 1)
                    else:  # Sunday
                        required_people = self.scheduler.settings.get('sunday_staff', 1)
                
                assigned_count = 0
                
                # Keep assigning until we meet requirements or run out of eligible people
                while assigned_count < required_people:
                    best_person = self.find_best_person_for_shift(people_list, date, shift)
                    if best_person:
                        self.scheduler.schedule[best_person][date].append(shift)
                        
                        # Log weekend priority assignment
                        if date.weekday() >= 5 and shift in ['morning', 'afternoon', 'mp']:
                            weekend_priority = self.scheduler.people[best_person].get('weekend_priority', 0)
                            self.logger.log('weekend_shift_balancing', 'debug', f"Assigned weekend {shift} to person {best_person} (priority {weekend_priority}) on {date}")
                        
                        # Update shift counts
                        if shift == 'mp':
                            # MP counts as both morning and afternoon
                            self.scheduler.shift_counts[best_person]['morning'] += 1
                            self.scheduler.shift_counts[best_person]['afternoon'] += 1
                        else:
                            self.scheduler.shift_counts[best_person][shift] += 1
                        
                        assigned_count += 1
                        
                        # Track weekend days - only for non-night shifts
                        if is_weekend and shift != 'night':
                            # Check if this person already worked this weekend day with non-night shifts
                            person_worked_this_weekend_day = False
                            for existing_shift in self.scheduler.schedule[best_person][date]:
                                if existing_shift not in ['night', 'rest_after_night'] and existing_shift != shift:
                                    person_worked_this_weekend_day = True
                                    break
                            
                            # Only increment weekend_days counter if this is their first non-night shift on this weekend day
                            if not person_worked_this_weekend_day:
                                self.scheduler.shift_counts[best_person]['weekend_days'] += 1
                    else:
                        # Add warning when shift cannot be assigned
                        warning = f"Could not assign {shift} shift on {date.strftime('%d/%m/%Y')} - no eligible staff (assigned {assigned_count}/{required_people})"
                        self.scheduler.warnings.append(warning)
                        self.logger.log('shift_assignment_warnings', 'error', f"Warning: {warning}")
                        break
        
        # Third pass: Add extra morning shifts to ensure everyone meets 34h minimum (if enabled)
        if self.scheduler.settings['fill_up_to_minimum_hours']:
            self.ensure_minimum_hours(dates, people_list)
        else:
            self.logger.log('fill_up_minimum_hours', 'info', "\nFill-up to minimum hours is disabled - skipping third pass")

    def ensure_minimum_hours(self, dates, people_list):
        """Add extra morning shifts on weekdays to ensure everyone meets minimum hours"""
        self.logger.log('fill_up_minimum_hours', 'info', "\nThird pass: Ensuring minimum 34h per week for all people...")
        
        # Get all weekday dates (Monday-Friday) for potential extra morning shifts
        weekday_dates = [d for d in dates if d.weekday() < 5]
        
        for person_id in people_list:
            # Calculate total hours for this person across all weeks
            total_hours = 0
            for date in dates:
                for shift in self.scheduler.schedule[person_id][date]:
                    if shift == 'morning':
                        total_hours += self.scheduler.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        total_hours += self.scheduler.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += self.scheduler.settings['night_shift_hours']
            
            # Calculate average weekly hours
            total_weeks = len(dates) / 7
            avg_weekly_hours = total_hours / total_weeks if total_weeks > 0 else 0
            
            # If below minimum, add morning shifts
            if avg_weekly_hours < self.scheduler.settings['min_weekly_hours']:
                hours_needed = (self.scheduler.settings['min_weekly_hours'] * total_weeks) - total_hours
                shifts_needed = int(hours_needed / self.scheduler.settings['morning_shift_hours']) + 1
                
                self.logger.log('fill_up_minimum_hours', 'info', f"Person {person_id} has {avg_weekly_hours:.1f}h/week ({total_hours}h total), needs {shifts_needed} extra morning shifts")
                
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
                            self.scheduler.schedule[person_id][date].append('morning')
                            self.scheduler.shift_counts[person_id]['morning'] += 1
                            shifts_added += 1
                            self.logger.log('fill_up_minimum_hours', 'debug', f"  Added morning shift for person {person_id} on {date}")
                            
                            # Recalculate hours after each addition
                            new_total_hours = 0
                            for check_date in dates:
                                for shift in self.scheduler.schedule[person_id][check_date]:
                                    if shift == 'morning':
                                        new_total_hours += self.scheduler.settings['morning_shift_hours']
                                    elif shift == 'afternoon':
                                        new_total_hours += self.scheduler.settings['afternoon_shift_hours']
                                    elif shift == 'mp':
                                        new_total_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                                    elif shift == 'night':
                                        new_total_hours += self.scheduler.settings['night_shift_hours']
                            
                            new_avg_weekly = new_total_hours / total_weeks
                            if new_avg_weekly >= self.scheduler.settings['min_weekly_hours']:
                                self.logger.log('fill_up_minimum_hours', 'info', f"  Person {person_id} now has {new_avg_weekly:.1f}h/week - minimum reached!")
                                break
                        else:
                            # Only print detailed reasons for first few attempts to avoid spam
                            if attempts <= 10:
                                self.logger.log('fill_up_minimum_hours', 'debug', f"  Person {person_id} cannot take morning shift on {date}: {reason}")
                
                if shifts_added < shifts_needed:
                    # Final check of actual hours
                    final_total_hours = 0
                    for check_date in dates:
                        for shift in self.scheduler.schedule[person_id][check_date]:
                            if shift == 'morning':
                                final_total_hours += self.scheduler.settings['morning_shift_hours']
                            elif shift == 'afternoon':
                                final_total_hours += self.scheduler.settings['afternoon_shift_hours']
                            elif shift == 'mp':
                                final_total_hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                            elif shift == 'night':
                                final_total_hours += self.scheduler.settings['night_shift_hours']
                    
                    final_avg_weekly = final_total_hours / total_weeks
                    self.logger.log('fill_up_minimum_hours', 'error', f"  Warning: Person {person_id} added {shifts_added} of {shifts_needed} shifts, now has {final_avg_weekly:.1f}h/week")

    def can_add_extra_morning_shift(self, person_id, date):
        """Check if we can add an extra morning shift for this person on this date - returns (can_add, reason)"""
        # NEW: Don't add extra shifts on tirocinio days (only afternoon allowed)
        person = self.scheduler.people[person_id]
        if 'tirocinio_dates' in person and date in person['tirocinio_dates']:
            return False, "tirocinio day (only afternoon shifts allowed)"
        
        # Don't add extra shifts on festivity days
        if date in self.scheduler.festivity_dates:
            return False, "festivity day (only MP shifts allowed)"
        
        # Check if this date is blocked for rest after night shift
        current_shifts = self.scheduler.schedule[person_id].get(date, [])
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
        for forbidden in person['forbidden_shifts']:
            if forbidden and forbidden['date'] == date and 'morning' in forbidden['shifts']:
                return False, "morning shift is forbidden on this date"
        
        # Enhanced night shift constraints
        prev_date = date - timedelta(days=1)
        next_date = date + timedelta(days=1)
        
        # Can't work the day after a night shift
        if prev_date in self.scheduler.schedule[person_id]:
            prev_shifts = self.scheduler.schedule[person_id].get(prev_date, [])
            if 'night' in prev_shifts:
                return False, "day after night shift"
        
        # Check weekly hour limits
        week_start = date - timedelta(days=date.weekday())
        weekly_hours = self.calculate_weekly_hours(person_id, week_start)
        projected_hours = weekly_hours + self.scheduler.settings['morning_shift_hours']
        
        # Don't exceed 54h per week even for minimum requirement
        if projected_hours > 54:
            return False, f"would exceed 54h/week ({projected_hours:.1f}h)"
        
        # Check consecutive days constraint
        week_dates = []
        for i in range(7):
            week_dates.append(week_start + timedelta(days=i))
        
        days_worked_this_week = 0
        for week_date in week_dates:
            if week_date in self.scheduler.schedule[person_id]:
                check_shifts = self.scheduler.schedule[person_id][week_date]
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
        self.logger.log('night_shift_assignment', 'info', f"Assigning night shifts only on required dates: {self.scheduler.required_night_dates}")
        
        # Only assign night shifts on the specified dates
        available_night_dates = [d for d in self.scheduler.required_night_dates if d in dates]
        
        if not available_night_dates:
            self.logger.log('night_shift_assignment', 'error', "Warning: No required night dates found in the scheduling period")
            return
        
        self.logger.log('night_shift_assignment', 'info', f"Available night dates in period: {available_night_dates}")
        
        # Filter people who are available for night shifts
        night_available_people = [p for p in people_list if self.scheduler.people[p]['night_available']]
        
        if not night_available_people:
            self.logger.log('night_shift_assignment', 'error', "ERROR: No people are available for night shifts!")
            for date in available_night_dates:
                warning = f"Could not assign night shift on {date.strftime('%d/%m/%Y')} - no staff available for night shifts"
                self.scheduler.warnings.append(warning)
            return
        
        self.logger.log('night_shift_assignment', 'info', f"People available for night shifts: {night_available_people}")
        
        # Group people by night priority if enabled (STRICT PRIORITY)
        if self.scheduler.settings['priority_assignment']['night_priority_enabled']:
            priority_groups = {}
            for person_id in night_available_people:
                priority = self.scheduler.people[person_id].get('night_priority', 0)
                if priority not in priority_groups:
                    priority_groups[priority] = []
                priority_groups[priority].append(person_id)
            
            # Sort priority levels (highest first)
            sorted_priorities = sorted(priority_groups.keys(), reverse=True)
            self.logger.log('night_shift_assignment', 'info', f"Night priority groups: {[(p, priority_groups[p]) for p in sorted_priorities]}")
        else:
            # No priority - treat everyone as same priority
            priority_groups = {0: night_available_people}
            sorted_priorities = [0]
        
        # Group night dates by month to enforce monthly limits
        night_dates_by_month = defaultdict(list)
        for night_date in available_night_dates:
            month_key = (night_date.year, night_date.month)
            night_dates_by_month[month_key].append(night_date)
        
        # Initialize monthly night shift counters for each person
        monthly_night_counts = defaultdict(lambda: defaultdict(int))
        
        # Assign one person per required night date using STRICT PRIORITY
        for date in available_night_dates:
            assigned = False
            month_key = (date.year, date.month)
            
            # Try each priority level from highest to lowest
            for priority_level in sorted_priorities:
                if assigned:
                    break
                
                eligible_people = priority_groups[priority_level].copy()
                random.shuffle(eligible_people)  # Randomize within same priority level
                
                self.logger.log('night_shift_assignment', 'debug', f"Trying priority level {priority_level} for {date}: {eligible_people}")
                
                for person_id in eligible_people:
                    # Check if person has exceeded monthly night shift limit
                    if monthly_night_counts[person_id][month_key] >= self.scheduler.settings['night_shifts_per_month']:
                        continue
                    
                    if self.can_assign_shift(person_id, date, 'night'):
                        self.scheduler.schedule[person_id][date].append('night')
                        self.scheduler.shift_counts[person_id]['night'] += 1
                        monthly_night_counts[person_id][month_key] += 1
                        self.logger.log('night_shift_assignment', 'debug', f"Assigned night shift to person {person_id} (priority {priority_level}) on {date} (month {month_key[1]}/{month_key[0]}: {monthly_night_counts[person_id][month_key]}/{self.scheduler.settings['night_shifts_per_month']})")
                        
                        # CRITICAL: Block the next day completely for this person
                        next_date = date + timedelta(days=1)
                        if next_date <= dates[-1]:  # Only if next day is within scheduling period
                            # Clear any existing shifts on the next day
                            self.scheduler.schedule[person_id][next_date] = ['rest_after_night']
                            self.logger.log('night_shift_assignment', 'debug', f"  Blocked {next_date} for person {person_id} (rest after night shift)")
                        
                        assigned = True
                        break
                
                if assigned:
                    break
                else:
                    self.logger.log('night_shift_assignment', 'debug', f"No eligible people found at priority level {priority_level} for {date}")
            
            if not assigned:
                warning = f"Could not assign night shift on {date.strftime('%d/%m/%Y')} - no eligible night-available staff at any priority level (monthly limits reached)"
                self.scheduler.warnings.append(warning)
                self.logger.log('shift_assignment_warnings', 'error', f"Warning: {warning}")

    def calculate_adjusted_afternoon_target(self, person_id):
        """Calculate adjusted afternoon shift target based on workload balancing"""
        if not self.scheduler.settings['workload_balancing']['enabled']:
            return float('inf')  # No limit if balancing disabled
        
        # Calculate everyone's burden to find the average
        all_burdens = []
        for pid in self.scheduler.people.keys():
            night_count = self.scheduler.shift_counts[pid]['night']
            weekend_count = self.scheduler.shift_counts[pid]['weekend_days']
            burden = (night_count * self.scheduler.settings['workload_balancing']['night_burden_coefficient'] + 
                     weekend_count * self.scheduler.settings['workload_balancing']['weekend_burden_coefficient'])
            all_burdens.append(burden)
        
        avg_burden = sum(all_burdens) / len(all_burdens) if all_burdens else 0
        
        # Calculate this person's burden
        night_count = self.scheduler.shift_counts[person_id]['night']
        weekend_count = self.scheduler.shift_counts[person_id]['weekend_days']
        person_burden = (night_count * self.scheduler.settings['workload_balancing']['night_burden_coefficient'] + 
                        weekend_count * self.scheduler.settings['workload_balancing']['weekend_burden_coefficient'])
        
        # Base afternoon target
        base_afternoons = 6  # Reasonable monthly target
        
        # Calculate compensation: people with LOWER burden get MORE afternoons
        burden_difference = avg_burden - person_burden  # Positive if person has lower burden than average
        
        compensation = min(
            abs(burden_difference),
            self.scheduler.settings['workload_balancing']['max_afternoon_compensation']
        )
        
        if burden_difference > 0:
            # Person has lower burden than average → give MORE afternoon shifts
            adjusted_target = base_afternoons + compensation
        else:
            # Person has higher burden than average → give FEWER afternoon shifts
            adjusted_target = max(
                base_afternoons - compensation,
                self.scheduler.settings['workload_balancing']['min_afternoon_shifts']
            )
        
        # Debug output
        self.logger.log('workload_balancing', 'debug', f"DEBUG adjust_target: Person {person_id}: burden={person_burden:.1f}, avg={avg_burden:.1f}, diff={burden_difference:.1f}, comp={compensation:.1f}, target={adjusted_target:.1f}")
        
        return adjusted_target

    def find_best_person_for_shift(self, people_list, date, shift):
        """Find the best person for a shift based on current workload and constraints - no constraint relaxation"""
        eligible_people = []
        eligibility_debug = {}  # Track reasons for ineligibility
        
        # NEW: Weekend shift balancing - exclude person(s) with maximum weekend shifts
        is_weekend_shift = date.weekday() >= 5 and shift in ['morning', 'afternoon', 'mp']
        excluded_people = set()
        
        if is_weekend_shift:
            # Exclude only those who have reached the configured maximum
            max_allowed = self.scheduler.settings.get('max_weekend_days_per_month', 2)
            for person_id in people_list:
                if self.scheduler.shift_counts[person_id]['weekend_days'] >= max_allowed:
                    excluded_people.add(person_id)
            self.logger.log(
                'weekend_shift_balancing', 'debug',
                f"Weekend shift balancing on {date} ({shift}): max_allowed={max_allowed}, excluded={excluded_people}"
            )
        
        for person_id in people_list:
            reasons = []  # Track reasons why this person is not eligible
            
            # Skip if person already has this shift type on this date
            if shift in self.scheduler.schedule[person_id].get(date, []):
                reasons.append(f"already has {shift} shift on this date")
                eligibility_debug[person_id] = reasons
                continue
            
            # NEW: Skip if person is excluded due to maximum weekend shifts
            if person_id in excluded_people:
                reasons.append(f"excluded due to maximum weekend shifts ({max_allowed})")
                eligibility_debug[person_id] = reasons
                continue
            
            # NEW: Special handling for tirocinio days - prioritize afternoon shifts
            person = self.scheduler.people[person_id]
            is_tirocinio_day = 'tirocinio_dates' in person and date in person['tirocinio_dates']
            
            if is_tirocinio_day and shift != 'afternoon':
                reasons.append(f"tirocinio day (only afternoon shifts allowed on {date})")
                eligibility_debug[person_id] = reasons
                continue
                
            # Check basic shift assignment constraints
            can_assign, constraint_reason = self._check_can_assign_shift_detailed(person_id, date, shift)
            if not can_assign:
                reasons.append(f"constraint violation: {constraint_reason}")
                eligibility_debug[person_id] = reasons
                continue
                
            # Check weekly hour constraints
            week_start = date - timedelta(days=date.weekday())
            weekly_hours = self.calculate_weekly_hours(person_id, week_start)
            
            # Estimate hours for this shift
            if shift == 'morning':
                shift_hours = self.scheduler.settings['morning_shift_hours']
            elif shift == 'afternoon':
                shift_hours = self.scheduler.settings['afternoon_shift_hours']
            elif shift == 'mp':  # Sunday MP shift
                shift_hours = self.scheduler.settings.get('sunday_mp_shift_hours', 12)
            else:  # night
                shift_hours = self.scheduler.settings['night_shift_hours']
            
            projected_hours = weekly_hours + shift_hours
            
            # Check if within limits - no relaxation
            if projected_hours > self.scheduler.settings['max_weekly_hours']:
                reasons.append(f"would exceed max weekly hours ({projected_hours:.1f}h > {self.scheduler.settings['max_weekly_hours']}h)")
                eligibility_debug[person_id] = reasons
                continue
            
            # NEW: For afternoon shifts, check workload balancing
            if shift == 'afternoon' and self.scheduler.settings['workload_balancing']['enabled']:
                current_afternoons = self.scheduler.shift_counts[person_id]['afternoon']
                adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                
                # Skip if person has reached their adjusted afternoon target
                if current_afternoons >= adjusted_target:
                    reasons.append(f"reached afternoon target ({current_afternoons} >= {adjusted_target:.1f})")
                    eligibility_debug[person_id] = reasons
                    continue
            
            # If we get here, person is eligible
            eligible_people.append(person_id)
            eligibility_debug[person_id] = ["eligible"]
        
        # Log detailed eligibility debug information if no one is eligible
        if not eligible_people:
            self.logger.log('shift_assignment_warnings', 'error', f"No eligible people for {shift} shift on {date.strftime('%d/%m/%Y')}")
            self.logger.log('shift_assignment_warnings', 'error', "Eligibility breakdown:")
            for person_id in people_list:
                reasons = eligibility_debug.get(person_id, ["unknown"])
                self.logger.log('shift_assignment_warnings', 'error', f"  Person {person_id}: {'; '.join(reasons)}")
            return None
        
        # Log eligibility summary when there are eligible people
        if self.logger.should_log('shift_assignment_warnings', 'debug'):
            eligible_count = len(eligible_people)
            total_count = len(people_list)
            self.logger.log('shift_assignment_warnings', 'debug', f"{shift} shift on {date}: {eligible_count}/{total_count} people eligible")
            if eligible_count < total_count:
                ineligible_summary = {}
                for person_id, reasons in eligibility_debug.items():
                    if person_id not in eligible_people:
                        for reason in reasons:
                            if reason not in ineligible_summary:
                                ineligible_summary[reason] = 0
                            ineligible_summary[reason] += 1
                
                self.logger.log('shift_assignment_warnings', 'debug', f"  Ineligibility reasons: {dict(ineligible_summary)}")
        
        # NEW: For weekend shifts, use STRICT PRIORITY assignment
        if is_weekend_shift and self.scheduler.settings['priority_assignment']['weekend_priority_enabled']:
            return self._find_best_person_weekend_strict_priority(eligible_people, date, shift)
        
        # Prioritize people who need more hours to reach minimum
        def priority_score(person_id):
            week_start = date - timedelta(days=date.weekday())
            weekly_hours = self.calculate_weekly_hours(person_id, week_start)
            
            # NEW: High priority for people on tirocinio days for afternoon shifts
            person = self.scheduler.people[person_id]
            is_tirocinio_day = 'tirocinio_dates' in person and date in person['tirocinio_dates']
            
            if is_tirocinio_day and shift == 'afternoon':
                # Give highest priority to people on tirocinio days for afternoon shifts
                return (-1, weekly_hours)  # -1 ensures highest priority
            
            # Higher priority for people below minimum hours (only if weekly hours consideration is enabled)
            if shift == 'afternoon' and self.scheduler.settings['afternoon_balancing']['enabled']:
                if not self.scheduler.settings['afternoon_balancing']['consider_weekly_hours']:
                    # Skip weekly hours consideration for afternoon shifts
                    if self.scheduler.settings['workload_balancing']['enabled']:
                        current_afternoons = self.scheduler.shift_counts[person_id]['afternoon']
                        adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                        # Prioritize those furthest below their adjusted target
                        base_priority = (0, current_afternoons - adjusted_target)
                    else:
                        # Use shift count only
                        base_priority = (0, self.scheduler.shift_counts[person_id]['afternoon'])
                else:
                    # Use standard weekly hours logic
                    if weekly_hours < self.scheduler.settings['min_weekly_hours']:
                        base_priority = (0, weekly_hours)
                    else:
                        if self.scheduler.settings['workload_balancing']['enabled']:
                            current_afternoons = self.scheduler.shift_counts[person_id]['afternoon']
                            adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                            base_priority = (1, current_afternoons - adjusted_target)
                        else:
                            base_priority = (1, self.scheduler.shift_counts[person_id]['afternoon'])
            else:
                # Standard logic for non-afternoon shifts
                if weekly_hours < self.scheduler.settings['min_weekly_hours']:
                    base_priority = (0, weekly_hours)
                else:
                    # NEW: For afternoon shifts, prioritize by adjusted target
                    if shift == 'afternoon' and self.scheduler.settings['workload_balancing']['enabled']:
                        current_afternoons = self.scheduler.shift_counts[person_id]['afternoon']
                        adjusted_target = self.afternoon_targets.get(person_id, float('inf'))
                        # Prioritize those furthest below their adjusted target
                        base_priority = (1, current_afternoons - adjusted_target)
                    else:
                        shift_key = shift if shift != 'mp' else 'morning'  # Use morning count for MP shifts
                        base_priority = (1, self.scheduler.shift_counts[person_id][shift_key])
            
            # NEW: For afternoon shifts, add weekly balancing penalty
            if shift == 'afternoon' and self.scheduler.settings['afternoon_balancing']['enabled']:
                if self.scheduler.settings['afternoon_balancing']['deprioritize_weekly_repeats']:
                    # Count afternoon shifts this week for this person
                    week_start = date - timedelta(days=date.weekday())
                    week_end = week_start + timedelta(days=6)
                    
                    afternoon_shifts_this_week = 0
                    current_date = week_start
                    while current_date <= week_end and current_date <= date:  # Only count up to today
                        if current_date in self.scheduler.schedule[person_id]:
                            if 'afternoon' in self.scheduler.schedule[person_id][current_date]:
                                afternoon_shifts_this_week += 1
                            # MP shifts also count as afternoon
                            if 'mp' in self.scheduler.schedule[person_id][current_date]:
                                afternoon_shifts_this_week += 1
                        current_date += timedelta(days=1)
                    
                    # Add penalty tier for people with afternoon shifts this week
                    if afternoon_shifts_this_week > 0:
                        base_priority = (base_priority[0] + 1, afternoon_shifts_this_week, base_priority[1])
            
            # NEW: Add priority from CSV data (but NOT for night shifts - they're handled strictly elsewhere)
            priority_bonus = 0
            if is_weekend_shift and self.scheduler.settings['priority_assignment']['weekend_priority_enabled']:
                weekend_priority = self.scheduler.people[person_id].get('weekend_priority', 0)
                priority_bonus = -weekend_priority * self.scheduler.settings['priority_assignment']['priority_weight']
            
            # Apply priority bonus (negative because we use min() - lower is better)
            if priority_bonus != 0:
                base_priority = (base_priority[0], base_priority[1] + priority_bonus)
            
            # NEW: Option 5 - Add randomization to tie-breaking
            if self.scheduler.settings.get('randomize_priority_tiebreaking', False):
                return base_priority + (random.random(),)
            else:
                return base_priority
        
        return min(eligible_people, key=priority_score)
    
    def _find_best_person_weekend_strict_priority(self, eligible_people, date, shift):
        """Find best person for weekend shift using STRICT priority (similar to night shifts)"""
        # Group people by weekend priority
        priority_groups = {}
        for person_id in eligible_people:
            priority = self.scheduler.people[person_id].get('weekend_priority', 0)
            if priority not in priority_groups:
                priority_groups[priority] = []
            priority_groups[priority].append(person_id)
        
        # Sort priority levels (highest first)
        sorted_priorities = sorted(priority_groups.keys(), reverse=True)
        self.logger.log('weekend_shift_balancing', 'debug', f"Weekend priority groups for {date} ({shift}): {[(p, priority_groups[p]) for p in sorted_priorities]}")
        
        # Try each priority level from highest to lowest
        for priority_level in sorted_priorities:
            candidates = priority_groups[priority_level].copy()
            if not candidates:
                continue
                
            # Randomize within same priority level to avoid bias
            random.shuffle(candidates)
            
            self.logger.log('weekend_shift_balancing', 'debug', f"Trying priority level {priority_level} for weekend {shift} on {date}: {candidates}")
            
            # For weekend shifts, we can return the first available candidate at this priority level
            # (unlike night shifts which have additional monthly limit checks)
            for person_id in candidates:
                # Additional checks can be added here if needed (e.g., monthly weekend limits)
                self.logger.log('weekend_shift_balancing', 'debug', f"Selected person {person_id} (priority {priority_level}) for weekend {shift} on {date}")
                return person_id
            
            self.logger.log('weekend_shift_balancing', 'debug', f"No suitable candidates found at priority level {priority_level} for weekend {shift} on {date}")
        
        # If no one found at any priority level, return None
        self.logger.log('weekend_shift_balancing', 'debug', f"No suitable candidates found at any priority level for weekend {shift} on {date}")
        return None

    def can_assign_shift(self, person_id, date, shift):
        """Check if person can be assigned to this shift"""
        can_assign, reason = self._check_can_assign_shift_detailed(person_id, date, shift)
        return can_assign

    def _check_can_assign_shift_detailed(self, person_id, date, shift):
        """Check if person can be assigned to this shift with detailed reason - returns (can_assign, reason)"""
        person = self.scheduler.people[person_id]
        
        # NEW: Check tirocinio (training) restrictions
        if 'tirocinio_dates' in person and date in person['tirocinio_dates']:
            if shift != 'afternoon':
                return False, f"tirocinio day (only afternoon shifts allowed on {date})"
        
        # NEW: Check night shift availability
        if shift == 'night' and not person['night_available']:
            return False, "not available for night shifts"
        
        # NEW: Check consecutive afternoon shift limit
        if shift == 'afternoon' and self.scheduler.settings['afternoon_balancing']['enabled']:
            max_consecutive = self.scheduler.settings['afternoon_balancing']['max_consecutive_afternoons']
            if max_consecutive > 0:
                # Count consecutive afternoon shifts ending at the previous day
                consecutive_afternoons = 0
                check_date = date - timedelta(days=1)
                
                while check_date in self.scheduler.schedule[person_id]:
                    day_shifts = self.scheduler.schedule[person_id][check_date]
                    has_afternoon = 'afternoon' in day_shifts or 'mp' in day_shifts
                    
                    if has_afternoon:
                        consecutive_afternoons += 1
                        check_date -= timedelta(days=1)
                    else:
                        break
                
                # If adding this afternoon shift would exceed the limit, refuse
                if consecutive_afternoons >= max_consecutive:
                    return False, f"would exceed max consecutive afternoons ({consecutive_afternoons} >= {max_consecutive})"
            
            # NEW: Check weekly afternoon shift limit
            max_weekly = self.scheduler.settings['afternoon_balancing'].get('max_afternoons_per_week', 0)
            if max_weekly > 0:
                # Count afternoon shifts in the current week
                week_start = date - timedelta(days=date.weekday())
                week_end = week_start + timedelta(days=6)
                
                afternoons_this_week = 0
                current_date = week_start
                while current_date <= week_end:
                    if current_date in self.scheduler.schedule[person_id]:
                        day_shifts = self.scheduler.schedule[person_id][current_date]
                        if 'afternoon' in day_shifts or 'mp' in day_shifts:
                            afternoons_this_week += 1
                    current_date += timedelta(days=1)
                
                # If adding this afternoon shift would exceed the weekly limit, refuse
                if afternoons_this_week >= max_weekly:
                    return False, f"would exceed max weekly afternoons ({afternoons_this_week} >= {max_weekly})"
        
        # Check forbidden shifts - for MP shift, check both M and P
        # This now includes vacation-generated forbidden shifts
        for forbidden in person['forbidden_shifts']:
            if forbidden and forbidden['date'] == date:
                if shift == 'mp':
                    # MP shift is forbidden if either M or P is forbidden
                    if 'morning' in forbidden['shifts'] or 'afternoon' in forbidden['shifts']:
                        return False, f"MP shift forbidden (morning or afternoon forbidden on {date})"
                elif shift in forbidden['shifts']:
                    return False, f"{shift} shift forbidden on {date}"
        
        # Check forbidden weekends
        if date.weekday() >= 5:  # Weekend
            for forbidden_weekend in person['forbidden_weekends']:
                if forbidden_weekend:
                    # Check if this weekend (Saturday or Sunday) is forbidden
                    weekend_start = date - timedelta(days=date.weekday() - 5)  # Get Saturday
                    if abs((weekend_start - forbidden_weekend).days) <= 1:
                        return False, f"weekend work forbidden (forbidden weekend: {forbidden_weekend})"
        
        # NEW: Check consecutive weekend days prevention
        if (date.weekday() >= 5 and shift != 'night' and 
            self.scheduler.settings.get('prevent_consecutive_weekend_days', False)):
            
            if date.weekday() == 5:  # Saturday - check if already working Sunday
                sunday = date + timedelta(days=1)
                if sunday in self.scheduler.schedule[person_id]:
                    sunday_shifts = self.scheduler.schedule[person_id][sunday]
                    # Check if has non-night shifts on Sunday
                    non_night_shifts = [s for s in sunday_shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:
                        return False, f"would work consecutive weekend days (Sunday {sunday} already assigned: {non_night_shifts})"
                        
            elif date.weekday() == 6:  # Sunday - check if already worked Saturday
                saturday = date - timedelta(days=1)
                if saturday in self.scheduler.schedule[person_id]:
                    saturday_shifts = self.scheduler.schedule[person_id][saturday]
                    # Check if has non-night shifts on Saturday
                    non_night_shifts = [s for s in saturday_shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:
                        return False, f"would work consecutive weekend days (Saturday {saturday} already assigned: {non_night_shifts})"
        
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
                if current_month_date.weekday() >= 5 and current_month_date in self.scheduler.schedule[person_id]:
                    day_shifts = self.scheduler.schedule[person_id][current_month_date]
                    # Only count as weekend day if has non-night shifts and not just rest
                    non_night_shifts = [s for s in day_shifts if s not in ['night', 'rest_after_night']]
                    if non_night_shifts:  # Has morning, afternoon, or mp shifts
                        weekend_days_this_month += 1
                current_month_date += timedelta(days=1)
            
            # If assigning this shift would exceed the monthly limit, refuse
            if weekend_days_this_month >= self.scheduler.settings['max_weekend_days_per_month']:
                return False, f"would exceed monthly weekend limit ({weekend_days_this_month} >= {self.scheduler.settings['max_weekend_days_per_month']})"
        
        # Check if already has shifts or is blocked for rest
        current_shifts = self.scheduler.schedule[person_id].get(date, [])
        if current_shifts:
            # If this date is blocked for rest after night shift, cannot assign anything
            if 'rest_after_night' in current_shifts:
                return False, "blocked for rest after night shift"
            
            # If trying to assign night shift but already has other shifts
            if shift == 'night':
                return False, f"already has other shifts on this date: {current_shifts}"
            
            # If already has night shift, cannot assign anything else
            if 'night' in current_shifts:
                return False, "already has night shift on this date"
            
            # If trying to assign MP shift but already has other shifts
            if shift == 'mp':
                return False, f"MP shift conflicts with existing shifts: {current_shifts}"
            if 'mp' in current_shifts:
                return False, "already has MP shift on this date"
            
            # On weekdays, only one shift allowed (except night which is handled above)
            if date.weekday() < 5:
                return False, f"weekday allows only one shift, already has: {current_shifts}"
            
            # On Saturday, allow morning + afternoon based on settings
            if date.weekday() == 5 and not self.scheduler.settings.get('weekend_morning_plus_afternoon', True):
                return False, f"Saturday morning+afternoon not allowed, already has: {current_shifts}"
        else:
            # If no current shifts, check if this date is blocked for rest after night shift
            if 'rest_after_night' in current_shifts:
                return False
        
        # Enhanced night shift constraints
        if shift == 'night':
            # Check day before: no shifts allowed
            prev_date = date - timedelta(days=1)
            if prev_date in self.scheduler.schedule[person_id]:
                prev_shifts = self.scheduler.schedule[person_id][prev_date]
                # If person worked the day before (and it's not just a rest day), cannot assign night
                if prev_shifts and 'rest_after_night' not in prev_shifts:
                    return False, f"worked day before night shift ({prev_date}): {prev_shifts}"
            
            # Check day after: must be completely free
            next_date = date + timedelta(days=1)
            if next_date in self.scheduler.schedule[person_id]:
                next_shifts = self.scheduler.schedule[person_id][next_date]
                # If next day already has any shifts (other than being marked for rest), cannot assign night
                if next_shifts and 'rest_after_night' not in next_shifts:
                    return False, f"day after night shift already occupied ({next_date}): {next_shifts}"
        else:
            # For non-night shifts, check if previous day had a night shift
            prev_date = date - timedelta(days=1)
            if prev_date in self.scheduler.schedule[person_id]:
                prev_shifts = self.scheduler.schedule[person_id][prev_date]
                if 'night' in prev_shifts:
                    return False, f"day after night shift ({prev_date})"
        
        # Check continuous rest requirement
        week_start = date - timedelta(days=date.weekday())
        days_worked_this_week = 0
        for i in range(7):
            check_date = week_start + timedelta(days=i)
            if check_date in self.scheduler.schedule[person_id]:
                check_shifts = self.scheduler.schedule[person_id][check_date]
                # Count as worked day only if has actual shifts (not rest days)
                if check_shifts and 'rest_after_night' not in check_shifts:
                    days_worked_this_week += 1
        
        if days_worked_this_week >= self.scheduler.settings['max_consecutive_days']:
            return False, f"would exceed max consecutive days ({days_worked_this_week} >= {self.scheduler.settings['max_consecutive_days']})"
        
        return True, "OK"
    
    def calculate_weekly_hours(self, person_id, week_start):
        """Calculate hours worked in a week starting from week_start"""
        hours = 0
        for i in range(7):
            date = week_start + timedelta(days=i)
            if date in self.scheduler.schedule[person_id]:
                for shift in self.scheduler.schedule[person_id][date]:
                    if shift == 'morning':
                        hours += self.scheduler.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        hours += self.scheduler.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        hours += self.scheduler.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        hours += self.scheduler.settings['night_shift_hours']
                    # Don't count 'rest_after_night' as hours
        return hours
        return hours
