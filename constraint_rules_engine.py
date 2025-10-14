from abc import ABC, abstractmethod
from typing import Dict, List, Any, Callable, Optional, Tuple
from datetime import datetime, timedelta, date
from enum import Enum
import inspect

class ConstraintSeverity(Enum):
    """Severity levels for constraint violations"""
    CRITICAL = "CRITICAL"  # Must pass - hard constraint
    HIGH = "HIGH"         # Should pass - important constraint
    MEDIUM = "MEDIUM"     # Nice to pass - soft constraint
    LOW = "LOW"           # Optional - preference

class ConstraintResult:
    """Result of a constraint evaluation"""
    def __init__(self, constraint_id: str, passed: bool, severity: ConstraintSeverity, 
                 message: str = "", violations: List[str] = None, metadata: Dict = None, name: str = None):
        self.constraint_id = constraint_id
        self.passed = passed
        self.severity = severity
        self.message = message
        self.violations = violations or []
        self.metadata = metadata or {}
        self.name = name or constraint_id  # Use constraint_id as fallback for name
        
    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"{self.name} ({self.constraint_id}): {status} - {self.message}"


class BaseConstraint(ABC):
    """Abstract base class for all constraints"""
    
    def __init__(self, constraint_id: str, name: str, description: str, 
                 severity: ConstraintSeverity, enabled: bool = True):
        self.constraint_id = constraint_id
        self.name = name
        self.description = description
        self.severity = severity
        self.enabled = enabled
        
    @abstractmethod
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        """Evaluate the constraint and return a result"""
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """Get constraint information"""
        return {
            'constraint_id': self.constraint_id,
            'name': self.name,
            'description': self.description,
            'severity': self.severity.value,
            'enabled': self.enabled
        }


class StaffingConstraint(BaseConstraint):
    """Constraint for minimum/maximum staffing requirements"""
    
    def __init__(self, constraint_id: str, shift_type: str, min_staff: int, max_staff: int = None,
                 days_filter: Callable[[date], bool] = None, severity: ConstraintSeverity = ConstraintSeverity.CRITICAL):
        super().__init__(constraint_id, f"Staffing ({shift_type.title()})", 
                        f"Staffing requirements for {shift_type} shifts", severity)
        self.shift_type = shift_type
        self.min_staff = min_staff
        self.max_staff = max_staff
        self.days_filter = days_filter or (lambda d: True)  # Default: all days
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        for date in all_dates:
            # print(f"Evaluating {self.constraint_id} for date {date}")
            if self.days_filter(date):
                staff_count = self._count_staff(scheduler, date)
                if staff_count < self.min_staff:
                    violations.append(f"{date}: {staff_count}/{self.min_staff} {self.shift_type} staff (under minimum)")
                
                if self.max_staff and staff_count > self.max_staff:
                    violations.append(f"{date}: {staff_count}/{self.max_staff} {self.shift_type} staff (over maximum)")
        
        passed = len(violations) == 0
        message = f"Staffing check: {len(violations)} violations found" if violations else "All staffing requirements met"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)
    
    def _count_staff(self, scheduler, check_date: date) -> int:
        """Count staff assigned to this shift type on the given date"""
        count = 0
        for person_id in scheduler.people.keys():
            assigned_shifts = scheduler.schedule[person_id].get(check_date, [])
            if self.shift_type in assigned_shifts:
                count += 1
        return count

class PersonalConstraint(BaseConstraint):
    """Constraint for individual person limits and requirements"""
    
    def __init__(self, constraint_id: str, constraint_type: str, limit: int, 
                 period: str = "month", severity: ConstraintSeverity = ConstraintSeverity.HIGH):
        super().__init__(constraint_id, f"Personal {constraint_type.title()} Limit", 
                        f"Maximum {limit} {constraint_type} shifts per {period}", severity)
        self.constraint_type = constraint_type  # 'night', 'weekend', etc.
        self.limit = limit
        self.period = period
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        if self.period == 'month':
            # Group dates by month
            months = {}
            for date in all_dates:
                month_key = (date.year, date.month)
                if month_key not in months:
                    months[month_key] = []
                months[month_key].append(date)
            
            # Check each person for each month
            for person_id in scheduler.people.keys():
                for month_key, month_dates in months.items():
                    count = 0
                    
                    for date in month_dates:
                        assigned_shifts = scheduler.schedule[person_id].get(date, [])
                        
                        if self.constraint_type == 'night':
                            if 'night' in assigned_shifts:
                                count += 1
                        elif self.constraint_type == 'weekend':
                            if date.weekday() >= 5:  # Weekend
                                non_night_shifts = [s for s in assigned_shifts if s not in ['night', 'rest_after_night']]
                                if non_night_shifts:
                                    count += 1
                    
                    if count > self.limit:
                        violations.append(f"Person {person_id} in {month_key[1]}/{month_key[0]}: {count} {self.constraint_type} shifts > {self.limit} limit")
        
        passed = len(violations) == 0
        message = f"{self.constraint_type.title()} limits check: {len(violations)} violations found" if violations else f"All {self.constraint_type} limits satisfied"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)

class WorkHoursConstraint(BaseConstraint):
    """Constraint for working hours limits and requirements"""
    
    def __init__(self, constraint_id: str, constraint_type: str, min_hours: float = None, 
                 max_hours: float = None, period: str = "week", severity: ConstraintSeverity = ConstraintSeverity.HIGH):
        super().__init__(constraint_id, f"Work Hours ({constraint_type})", 
                        f"Hours constraint: {constraint_type} per {period}", severity)
        self.constraint_type = constraint_type  # 'weekly', 'daily', 'shift'
        self.min_hours = min_hours
        self.max_hours = max_hours
        self.period = period
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        if self.constraint_type == 'weekly':
            # Check weekly hours for each person
            weeks = self._get_weeks_in_period(start_date, end_date)
            for person_id in scheduler.people.keys():
                for week_start in weeks:
                    week_hours = scheduler.shift_assigner.calculate_weekly_hours(person_id, week_start)
                    
                    if self.min_hours and week_hours < self.min_hours:
                        violations.append(f"Person {person_id} week {week_start}: {week_hours:.1f}h < {self.min_hours}h minimum")
                    if self.max_hours and week_hours > self.max_hours:
                        violations.append(f"Person {person_id} week {week_start}: {week_hours:.1f}h > {self.max_hours}h maximum")
        elif self.constraint_type == 'monthly':
            # Group dates by month
            months = {}
            for date in all_dates:
                month_key = (date.year, date.month)
                if month_key not in months:
                    months[month_key] = []
                months[month_key].append(date)
            for person_id in scheduler.people.keys():
                for month_key, month_dates in months.items():
                    # Find all weeks (Monday start) in this month
                    first_day = min(month_dates)
                    last_day = max(month_dates)
                    week_starts = []
                    current = first_day - timedelta(days=first_day.weekday())
                    while current <= last_day:
                        week_starts.append(current)
                        current += timedelta(weeks=1)
                    week_hours_list = []
                    for week_start in week_starts:
                        week_hours = scheduler.shift_assigner.calculate_weekly_hours(person_id, week_start, force_debug=False)
                        week_hours_list.append(week_hours)
                    if week_hours_list:
                        num_days_in_month = (last_day - first_day).days + 1
                        avg_weekly_hours = sum(week_hours_list) / (num_days_in_month / 7)
                        if self.min_hours and avg_weekly_hours < self.min_hours:
                            violations.append(f"Person {person_id} {month_key[1]}/{month_key[0]}: avg {avg_weekly_hours:.1f}h/week < {self.min_hours}h minimum")
                        if self.max_hours and avg_weekly_hours > self.max_hours:
                            violations.append(f"Person {person_id} {month_key[1]}/{month_key[0]}: avg {avg_weekly_hours:.1f}h/week > {self.max_hours}h maximum")
        
        passed = len(violations) == 0
        if self.constraint_type == 'monthly':
            message = f"Monthly average weekly hours check: {len(violations)} violations found" if violations else "All monthly average weekly hours within limits"
        else:
            message = f"Weekly hours check: {len(violations)} violations found" if violations else "All weekly hours within limits"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)
    
    def _get_weeks_in_period(self, start_date: date, end_date: date) -> List[date]:
        """Get all Monday dates (week starts) in the period"""
        weeks = []
        current = start_date - timedelta(days=start_date.weekday())  # Get Monday of start week
        while current <= end_date:
            weeks.append(current)
            current += timedelta(weeks=1)
        return weeks


class ForbiddenShiftsConstraint(BaseConstraint):
    """Constraint for forbidden shifts (vacation, personal unavailability)"""
    
    def __init__(self, constraint_id: str, severity: ConstraintSeverity = ConstraintSeverity.CRITICAL):
        super().__init__(constraint_id, "Forbidden Shifts", 
                        "No person should be assigned forbidden shifts", severity)
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        for person_id in scheduler.people.keys():
            person_data = scheduler.people[person_id]
            
            # Check forbidden shifts
            for forbidden in person_data.get('forbidden_shifts', []):
                if forbidden and forbidden['date'] in all_dates:
                    assigned_shifts = scheduler.schedule[person_id].get(forbidden['date'], [])
                    for forbidden_shift in forbidden['shifts']:
                        if forbidden_shift in assigned_shifts:
                            violations.append(f"Person {person_id} assigned forbidden {forbidden_shift} on {forbidden['date']}")
        
        passed = len(violations) == 0
        message = f"Forbidden shifts check: {len(violations)} violations found" if violations else "No forbidden shift violations"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)


class CustomConstraint(BaseConstraint):
    """Constraint defined by a custom evaluation function"""
    
    def __init__(self, constraint_id: str, name: str, description: str, 
                 evaluation_func: Callable, severity: ConstraintSeverity = ConstraintSeverity.MEDIUM):
        super().__init__(constraint_id, name, description, severity)
        self.evaluation_func = evaluation_func
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        try:
            return self.evaluation_func(scheduler, start_date, end_date, self.constraint_id, self.severity)
        except Exception as e:
            return ConstraintResult(
                self.constraint_id, False, self.severity, 
                f"Custom constraint evaluation failed: {str(e)}", [str(e)], name=self.name
            )


class FestivityConstraint(BaseConstraint):
    """Constraint for festivity day coverage"""
    
    def __init__(self, constraint_id: str, required_staff: int = 1, 
                 severity: ConstraintSeverity = ConstraintSeverity.HIGH):
        super().__init__(constraint_id, "Festivity Coverage", 
                        f"Festivity days must have {required_staff} staff member(s)", severity)
        self.required_staff = required_staff
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        for date in all_dates:
            if date in scheduler.festivity_dates:
                staff_count = 0
                for person_id in scheduler.people.keys():
                    assigned_shifts = scheduler.schedule[person_id].get(date, [])
                    if 'mp' in assigned_shifts:  # Festivity uses MP shift
                        staff_count += 1
                
                if staff_count < self.required_staff:
                    violations.append(f"Festivity {date}: {staff_count}/{self.required_staff} staff assigned")
        
        passed = len(violations) == 0
        message = f"Festivity coverage: {len(violations)} violations found" if violations else "All festivities properly covered"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)


class AlwaysOnShiftWeekdaysConstraint(BaseConstraint):
    """
    Each person must be assigned at least one shift on every weekday (Mon-Fri) that is not a festivity,
    unless they are in tirocinio, on vacation, or resting after a night shift.
    """
    def __init__(self, constraint_id: str = "always_on_shift_weekdays",
                 severity: ConstraintSeverity = ConstraintSeverity.HIGH):
        super().__init__(
            constraint_id,
            "Always On Shift (Weekdays)",
            "Each person must be assigned at least one shift on every weekday (not festivity), unless in tirocinio, on vacation, or resting after night shift.",
            severity
        )

    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        festivity_dates = set(scheduler.festivity_dates)
        for person_id, person in scheduler.people.items():
            for d in all_dates:
                if d.weekday() >= 5 or d in festivity_dates:
                    continue  # Skip weekends and festivities

                assigned_shifts = scheduler.schedule[person_id].get(d, [])
                # Vacation: all shifts forbidden
                is_vacation = any(
                    forbidden and forbidden['date'] == d and len(forbidden['shifts']) == 3
                    for forbidden in person.get('forbidden_shifts', [])
                )
                # Tirocinio
                is_tirocinio = 'tirocinio_dates' in person and d in person['tirocinio_dates']
                # Rest after night shift (the day after a night shift)
                prev_day = d - timedelta(days=1)
                had_night_before = 'night' in scheduler.schedule[person_id].get(prev_day, [])

                if not assigned_shifts and not is_vacation and not is_tirocinio and not had_night_before:
                    violations.append(
                        f"Person {person_id} has no shift on {d} (weekday, not festivity, not vacation/tirocinio/night-rest)"
                    )

        passed = len(violations) == 0
        message = f"Weekday presence check: {len(violations)} violations found" if violations else "All people assigned on all required weekdays"
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations, name=self.name)

class ConstraintRulesEngine:
    """Main engine for managing and evaluating constraints"""
    
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.constraints: Dict[str, BaseConstraint] = {}
        self.constraint_groups: Dict[str, List[str]] = {
            'staffing': [],
            'personal': [],
            'work_hours': [],
            'forbidden': [],
            'festivity': [],
            'custom': []
        }
        
        # Initialize default constraints
        self._initialize_default_constraints()
    
    def _initialize_default_constraints(self):
        """Initialize default constraints based on scheduler settings"""
        settings = self.scheduler.settings
        
        # Staffing constraints
        self.add_constraint(StaffingConstraint(
            'weekday_morning_staff', 'morning', settings['min_morning_staff'],
            days_filter=lambda d: d.weekday() < 5,  # Monday-Friday
            severity=ConstraintSeverity.CRITICAL
        ))
        
        self.add_constraint(StaffingConstraint(
            'weekday_afternoon_staff', 'afternoon', settings['target_afternoon_staff'],
            days_filter=lambda d: d.weekday() < 5,  # Monday-Friday
            severity=ConstraintSeverity.HIGH
        ))
        
        self.add_constraint(StaffingConstraint(
            'saturday_morning_staff', 'morning', settings.get('saturday_morning_staff', 1),
            days_filter=lambda d: d.weekday() == 5,  # Saturday
            severity=ConstraintSeverity.CRITICAL
        ))
        
        self.add_constraint(StaffingConstraint(
            'sunday_mp_staff', 'mp', settings.get('sunday_staff', 1),
            days_filter=lambda d: d.weekday() == 6,  # Sunday
            severity=ConstraintSeverity.CRITICAL
        ))
        
        # Work hours constraints
        self.add_constraint(WorkHoursConstraint(
            'weekly_hours', 'monthly', 
            settings['min_weekly_hours'], settings['max_weekly_hours'],
            severity=ConstraintSeverity.HIGH
        ))
        
        # Personal constraints
        self.add_constraint(PersonalConstraint(
            'monthly_night_limits', 'night', settings['night_shifts_per_month'],
            period='month', severity=ConstraintSeverity.HIGH
        ))
        
        self.add_constraint(PersonalConstraint(
            'monthly_weekend_limits', 'weekend', settings['max_weekend_days_per_month'],
            period='month', severity=ConstraintSeverity.MEDIUM
        ))
        
        # Forbidden shifts constraint
        self.add_constraint(ForbiddenShiftsConstraint(
            'forbidden_shifts', severity=ConstraintSeverity.CRITICAL
        ))
        
        # Festivity constraint
        self.add_constraint(FestivityConstraint(
            'festivity_coverage', settings.get('festivity_staff', 1),
            severity=ConstraintSeverity.HIGH
        ))
        
        # Always On Shift Weekdays constraint
        self.add_constraint(AlwaysOnShiftWeekdaysConstraint())

    def add_constraint(self, constraint: BaseConstraint):
        """Add a constraint to the engine"""
        self.constraints[constraint.constraint_id] = constraint
        
        # Add to appropriate group
        if isinstance(constraint, StaffingConstraint):
            self.constraint_groups['staffing'].append(constraint.constraint_id)
        elif isinstance(constraint, PersonalConstraint):
            self.constraint_groups['personal'].append(constraint.constraint_id)
        elif isinstance(constraint, WorkHoursConstraint):
            self.constraint_groups['work_hours'].append(constraint.constraint_id)
        elif isinstance(constraint, ForbiddenShiftsConstraint):
            self.constraint_groups['forbidden'].append(constraint.constraint_id)
        elif isinstance(constraint, FestivityConstraint):
            self.constraint_groups['festivity'].append(constraint.constraint_id)
        elif isinstance(constraint, CustomConstraint):
            self.constraint_groups['custom'].append(constraint.constraint_id)
    
    def remove_constraint(self, constraint_id: str):
        """Remove a constraint from the engine"""
        if constraint_id in self.constraints:
            del self.constraints[constraint_id]
            # Remove from groups
            for group_constraints in self.constraint_groups.values():
                if constraint_id in group_constraints:
                    group_constraints.remove(constraint_id)
    
    def enable_constraint(self, constraint_id: str):
        """Enable a constraint"""
        if constraint_id in self.constraints:
            self.constraints[constraint_id].enabled = True
    
    def disable_constraint(self, constraint_id: str):
        """Disable a constraint"""
        if constraint_id in self.constraints:
            self.constraints[constraint_id].enabled = False
    
    def evaluate_all(self, start_date: date, end_date: date) -> Dict[str, ConstraintResult]:
        """Evaluate all enabled constraints"""
        results = {}
        
        for constraint_id, constraint in self.constraints.items():
            if constraint.enabled:
                try:
                    result = constraint.evaluate(self.scheduler, start_date, end_date)
                    results[constraint_id] = result
                except Exception as e:
                    results[constraint_id] = ConstraintResult(
                        constraint_id, False, constraint.severity,
                        f"Evaluation error: {str(e)}", [str(e)]
                    )
        
        return results
    
    def evaluate_group(self, group_name: str, start_date: date, end_date: date) -> Dict[str, ConstraintResult]:
        """Evaluate constraints in a specific group"""
        results = {}
        
        if group_name in self.constraint_groups:
            for constraint_id in self.constraint_groups[group_name]:
                if constraint_id in self.constraints and self.constraints[constraint_id].enabled:
                    try:
                        result = self.constraints[constraint_id].evaluate(self.scheduler, start_date, end_date)
                        results[constraint_id] = result
                    except Exception as e:
                        results[constraint_id] = ConstraintResult(
                            constraint_id, False, self.constraints[constraint_id].severity,
                            f"Evaluation error: {str(e)}", [str(e)], name=self.constraints[constraint_id].name
                        )
        
        return results
    
    def get_constraint_info(self, constraint_id: str) -> Dict[str, Any]:
        """Get information about a specific constraint"""
        if constraint_id in self.constraints:
            return self.constraints[constraint_id].get_info()
        return {}
    
    def get_all_constraints_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all constraints"""
        return {cid: constraint.get_info() for cid, constraint in self.constraints.items()}
    
    def get_constraint_groups(self) -> Dict[str, List[str]]:
        """Get constraint groups"""
        return self.constraint_groups.copy()
    
    def add_custom_constraint(self, constraint_id: str, name: str, description: str, 
                            evaluation_func: Callable, severity: str = "MEDIUM"):
        """Add a custom constraint with evaluation function"""
        severity_enum = ConstraintSeverity(severity)
        custom_constraint = CustomConstraint(constraint_id, name, description, evaluation_func, severity_enum)
        self.add_constraint(custom_constraint)
