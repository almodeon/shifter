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
                 message: str = "", violations: List[str] = None, metadata: Dict = None):
        self.constraint_id = constraint_id
        self.passed = passed
        self.severity = severity
        self.message = message
        self.violations = violations or []
        self.metadata = metadata or {}
        
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{self.constraint_id}: {status} ({self.severity.value})"

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
        """Evaluate the constraint and return result"""
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """Get constraint information"""
        return {
            'id': self.constraint_id,
            'name': self.name,
            'description': self.description,
            'severity': self.severity.value,
            'enabled': self.enabled
        }

class StaffingConstraint(BaseConstraint):
    """Constraint for minimum/maximum staffing requirements"""
    
    def __init__(self, constraint_id: str, shift_type: str, min_staff: int, max_staff: int = None,
                 days_filter: Callable[[date], bool] = None, severity: ConstraintSeverity = ConstraintSeverity.CRITICAL):
        name = f"Staffing: {shift_type}"
        description = f"Require {min_staff}-{max_staff or '∞'} staff for {shift_type} shifts"
        super().__init__(constraint_id, name, description, severity)
        
        self.shift_type = shift_type
        self.min_staff = min_staff
        self.max_staff = max_staff
        self.days_filter = days_filter or (lambda d: True)
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = []
        current_date = start_date
        while current_date <= end_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)
        
        for check_date in all_dates:
            if not self.days_filter(check_date):
                continue
                
            staff_count = self._count_staff(scheduler, check_date)
            
            if staff_count < self.min_staff:
                violations.append(f"{check_date}: {staff_count} staff (need ≥{self.min_staff})")
            elif self.max_staff and staff_count > self.max_staff:
                violations.append(f"{check_date}: {staff_count} staff (need ≤{self.max_staff})")
        
        passed = len(violations) == 0
        message = f"Checked {len([d for d in all_dates if self.days_filter(d)])} days"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations)
    
    def _count_staff(self, scheduler, check_date: date) -> int:
        """Count staff working the specified shift type on the given date"""
        count = 0
        for person_id in scheduler.people.keys():
            shifts = scheduler.schedule[person_id].get(check_date, [])
            if self.shift_type in shifts:
                count += 1
            elif self.shift_type == 'morning' and 'mp' in shifts:
                count += 1  # MP counts as morning
            elif self.shift_type == 'afternoon' and 'mp' in shifts:
                count += 1  # MP counts as afternoon
        return count

class PersonalConstraint(BaseConstraint):
    """Constraint for individual person limits and requirements"""
    
    def __init__(self, constraint_id: str, constraint_type: str, limit: int, 
                 period: str = "month", severity: ConstraintSeverity = ConstraintSeverity.HIGH):
        name = f"Personal: {constraint_type} per {period}"
        description = f"Limit {constraint_type} to {limit} per {period} per person"
        super().__init__(constraint_id, name, description, severity)
        
        self.constraint_type = constraint_type
        self.limit = limit
        self.period = period
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        
        if self.period == "month":
            violations = self._check_monthly_limits(scheduler, start_date, end_date)
        elif self.period == "week":
            violations = self._check_weekly_limits(scheduler, start_date, end_date)
        
        passed = len(violations) == 0
        message = f"Checked {len(scheduler.people)} people for {self.constraint_type} limits"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations)
    
    def _check_monthly_limits(self, scheduler, start_date: date, end_date: date) -> List[str]:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        months_in_period = set((d.year, d.month) for d in all_dates)
        
        for person_id in scheduler.people.keys():
            for month_year in months_in_period:
                month_dates = [d for d in all_dates if (d.year, d.month) == month_year]
                count = self._count_constraint_violations(scheduler, person_id, month_dates)
                
                if count > self.limit:
                    violations.append(f"Person {person_id} in {month_year[1]}/{month_year[0]}: {count} {self.constraint_type} (max {self.limit})")
        
        return violations
    
    def _check_weekly_limits(self, scheduler, start_date: date, end_date: date) -> List[str]:
        violations = []
        # Implementation for weekly limits
        return violations
    
    def _count_constraint_violations(self, scheduler, person_id: str, dates: List[date]) -> int:
        count = 0
        for check_date in dates:
            shifts = scheduler.schedule[person_id].get(check_date, [])
            if self.constraint_type == "night_shifts" and 'night' in shifts:
                count += 1
            elif self.constraint_type == "weekend_days" and check_date.weekday() >= 5:
                non_night_shifts = [s for s in shifts if s not in ['night', 'rest_after_night']]
                if non_night_shifts:
                    count += 1
            elif self.constraint_type == "consecutive_days":
                # Special handling for consecutive days
                pass
        return count

class WorkHoursConstraint(BaseConstraint):
    """Constraint for working hours limits"""
    
    def __init__(self, constraint_id: str, min_hours: float, max_hours: float,
                 period: str = "week", severity: ConstraintSeverity = ConstraintSeverity.CRITICAL):
        name = f"Work Hours: {min_hours}-{max_hours}h per {period}"
        description = f"Ensure {min_hours}-{max_hours} hours per {period} per person"
        super().__init__(constraint_id, name, description, severity)
        
        self.min_hours = min_hours
        self.max_hours = max_hours
        self.period = period
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        total_weeks = len(all_dates) / 7
        
        for person_id in scheduler.people.keys():
            total_hours = 0
            for check_date in all_dates:
                for shift in scheduler.schedule[person_id].get(check_date, []):
                    if shift == 'morning':
                        total_hours += scheduler.settings['morning_shift_hours']
                    elif shift == 'afternoon':
                        total_hours += scheduler.settings['afternoon_shift_hours']
                    elif shift == 'mp':
                        total_hours += scheduler.settings.get('sunday_mp_shift_hours', 12)
                    elif shift == 'night':
                        total_hours += scheduler.settings['night_shift_hours']
            
            if self.period == "week":
                avg_weekly = total_hours / total_weeks if total_weeks > 0 else 0
                if avg_weekly < self.min_hours:
                    violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (below {self.min_hours}h)")
                elif avg_weekly > self.max_hours:
                    violations.append(f"Person {person_id}: {avg_weekly:.1f}h/week (above {self.max_hours}h)")
        
        passed = len(violations) == 0
        message = f"Checked {len(scheduler.people)} people for work hours"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations)

class ForbiddenShiftsConstraint(BaseConstraint):
    """Constraint for forbidden shifts and vacation compliance"""
    
    def __init__(self, constraint_id: str, severity: ConstraintSeverity = ConstraintSeverity.CRITICAL):
        name = "Forbidden Shifts"
        description = "Ensure no person is assigned forbidden shifts or works during vacation"
        super().__init__(constraint_id, name, description, severity)
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        violations = []
        all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        
        for person_id in scheduler.people.keys():
            person_data = scheduler.people[person_id]
            for forbidden in person_data.get('forbidden_shifts', []):
                if forbidden and forbidden['date'] in all_dates:
                    assigned_shifts = scheduler.schedule[person_id].get(forbidden['date'], [])
                    for forbidden_shift in forbidden['shifts']:
                        if forbidden_shift in assigned_shifts:
                            violations.append(f"Person {person_id}: assigned forbidden {forbidden_shift} on {forbidden['date']}")
        
        passed = len(violations) == 0
        message = f"Checked forbidden shifts for {len(scheduler.people)} people"
        
        return ConstraintResult(self.constraint_id, passed, self.severity, message, violations)

class CustomConstraint(BaseConstraint):
    """Custom constraint defined by a user function"""
    
    def __init__(self, constraint_id: str, name: str, description: str, 
                 evaluation_func: Callable, severity: ConstraintSeverity = ConstraintSeverity.MEDIUM):
        super().__init__(constraint_id, name, description, severity)
        self.evaluation_func = evaluation_func
    
    def evaluate(self, scheduler, start_date: date, end_date: date) -> ConstraintResult:
        try:
            # Call user-defined evaluation function
            result = self.evaluation_func(scheduler, start_date, end_date)
            
            # Ensure result is a ConstraintResult
            if isinstance(result, ConstraintResult):
                return result
            elif isinstance(result, tuple) and len(result) >= 2:
                # Allow returning (passed, violations) tuple
                passed, violations = result[0], result[1]
                message = result[2] if len(result) > 2 else "Custom constraint check"
                return ConstraintResult(self.constraint_id, passed, self.severity, message, violations)
            else:
                # Simple boolean return
                return ConstraintResult(self.constraint_id, bool(result), self.severity, "Custom constraint check")
                
        except Exception as e:
            return ConstraintResult(self.constraint_id, False, self.severity, f"Error: {e}", [str(e)])

class ConstraintRulesEngine:
    """Main constraint rules engine that manages and evaluates all constraints"""
    
    def __init__(self, scheduler=None, logger=None):
        self.scheduler = scheduler
        self.logger = logger
        self.constraints: Dict[str, BaseConstraint] = {}
        self.constraint_groups: Dict[str, List[str]] = {}
        
        # Initialize default constraints
        self._initialize_default_constraints()
    
    def _log(self, level: str, message: str):
        """Internal logging helper"""
        if self.logger:
            self.logger.log('constraint_verification', level, message)
    
    def _initialize_default_constraints(self):
        """Initialize standard hospital scheduling constraints"""
        # Staffing constraints
        self.add_constraint(StaffingConstraint(
            "weekday_morning_staff", "morning", 3, None,
            lambda d: d.weekday() < 5, ConstraintSeverity.CRITICAL
        ))
        
        self.add_constraint(StaffingConstraint(
            "weekday_afternoon_staff", "afternoon", 1, 1,
            lambda d: d.weekday() < 5, ConstraintSeverity.CRITICAL
        ))
        
        self.add_constraint(StaffingConstraint(
            "saturday_morning_staff", "morning", 0, None,
            lambda d: d.weekday() == 5, ConstraintSeverity.CRITICAL
        ))
        
        self.add_constraint(StaffingConstraint(
            "sunday_mp_staff", "mp", 1, 1,
            lambda d: d.weekday() == 6, ConstraintSeverity.CRITICAL
        ))
        
        # Personal constraints
        self.add_constraint(PersonalConstraint(
            "monthly_night_limits", "night_shifts", 1, "month", ConstraintSeverity.HIGH
        ))
        
        self.add_constraint(PersonalConstraint(
            "monthly_weekend_limits", "weekend_days", 2, "month", ConstraintSeverity.HIGH
        ))
        
        # Work hours constraint
        self.add_constraint(WorkHoursConstraint(
            "weekly_hours", 34, 48, "week", ConstraintSeverity.CRITICAL
        ))
        
        # Forbidden shifts constraint
        self.add_constraint(ForbiddenShiftsConstraint(
            "forbidden_shifts", ConstraintSeverity.CRITICAL
        ))
        
        # Define constraint groups
        self.constraint_groups = {
            "staffing": ["weekday_morning_staff", "weekday_afternoon_staff", "saturday_morning_staff", "sunday_mp_staff"],
            "personal_limits": ["monthly_night_limits", "monthly_weekend_limits"],
            "work_hours": ["weekly_hours"],
            "forbidden": ["forbidden_shifts"],
            "critical": [c_id for c_id, c in self.constraints.items() if c.severity == ConstraintSeverity.CRITICAL],
            "all": list(self.constraints.keys())
        }
    
    def add_constraint(self, constraint: BaseConstraint):
        """Add a constraint to the engine"""
        self.constraints[constraint.constraint_id] = constraint
        self._log('info', f"Added constraint: {constraint.name}")
    
    def remove_constraint(self, constraint_id: str) -> bool:
        """Remove a constraint from the engine"""
        if constraint_id in self.constraints:
            removed = self.constraints.pop(constraint_id)
            self._log('info', f"Removed constraint: {removed.name}")
            return True
        return False
    
    def enable_constraint(self, constraint_id: str):
        """Enable a constraint"""
        if constraint_id in self.constraints:
            self.constraints[constraint_id].enabled = True
    
    def disable_constraint(self, constraint_id: str):
        """Disable a constraint"""
        if constraint_id in self.constraints:
            self.constraints[constraint_id].enabled = False
    
    def add_custom_constraint(self, constraint_id: str, name: str, description: str,
                            evaluation_func: Callable, severity: ConstraintSeverity = ConstraintSeverity.MEDIUM):
        """Add a custom constraint with user-defined evaluation function"""
        constraint = CustomConstraint(constraint_id, name, description, evaluation_func, severity)
        self.add_constraint(constraint)
    
    def create_constraint_group(self, group_name: str, constraint_ids: List[str]):
        """Create a named group of constraints"""
        self.constraint_groups[group_name] = constraint_ids
    
    def evaluate_all(self, start_date: date, end_date: date) -> Dict[str, ConstraintResult]:
        """Evaluate all enabled constraints"""
        return self.evaluate_constraints(list(self.constraints.keys()), start_date, end_date)
    
    def evaluate_group(self, group_name: str, start_date: date, end_date: date) -> Dict[str, ConstraintResult]:
        """Evaluate a specific group of constraints"""
        if group_name not in self.constraint_groups:
            self._log('error', f"Unknown constraint group: {group_name}")
            return {}
        
        constraint_ids = self.constraint_groups[group_name]
        return self.evaluate_constraints(constraint_ids, start_date, end_date)
    
    def evaluate_constraints(self, constraint_ids: List[str], start_date: date, end_date: date) -> Dict[str, ConstraintResult]:
        """Evaluate specific constraints"""
        results = {}
        
        for constraint_id in constraint_ids:
            if constraint_id not in self.constraints:
                self._log('error', f"Unknown constraint: {constraint_id}")
                continue
                
            constraint = self.constraints[constraint_id]
            if not constraint.enabled:
                self._log('debug', f"Skipping disabled constraint: {constraint_id}")
                continue
            
            self._log('debug', f"Evaluating constraint: {constraint.name}")
            result = constraint.evaluate(self.scheduler, start_date, end_date)
            results[constraint_id] = result
            
            # Log result
            status = "✅ PASS" if result.passed else "❌ FAIL"
            self._log('info' if result.passed else 'error', f"{constraint.name}: {status}")
            
            if not result.passed and result.violations:
                for violation in result.violations[:3]:  # Show first 3 violations
                    self._log('debug', f"  - {violation}")
                if len(result.violations) > 3:
                    self._log('debug', f"  ... and {len(result.violations) - 3} more violations")
        
        return results
    
    def get_constraint_info(self) -> Dict[str, Dict]:
        """Get information about all constraints"""
        return {c_id: constraint.get_info() for c_id, constraint in self.constraints.items()}
    
    def get_constraint_groups(self) -> Dict[str, List[str]]:
        """Get all constraint groups"""
        return self.constraint_groups.copy()
    
    def update_constraint_settings(self, settings: Dict[str, Any]):
        """Update constraint parameters from scheduler settings"""
        # Update staffing constraints based on settings
        if "weekday_morning_staff" in self.constraints:
            self.constraints["weekday_morning_staff"].min_staff = settings.get('min_morning_staff', 3)
        
        if "weekday_afternoon_staff" in self.constraints:
            max_afternoon = settings.get('max_afternoon_staff', 1)
            self.constraints["weekday_afternoon_staff"].min_staff = max_afternoon
            self.constraints["weekday_afternoon_staff"].max_staff = max_afternoon
        
        # Update personal limits
        if "monthly_night_limits" in self.constraints:
            self.constraints["monthly_night_limits"].limit = settings.get('night_shifts_per_month', 1)
        
        if "monthly_weekend_limits" in self.constraints:
            self.constraints["monthly_weekend_limits"].limit = settings.get('max_weekend_days_per_month', 2)
        
        # Update work hours
        if "weekly_hours" in self.constraints:
            self.constraints["weekly_hours"].min_hours = settings.get('min_weekly_hours', 34)
            self.constraints["weekly_hours"].max_hours = settings.get('max_weekly_hours', 48)
    
    def generate_constraint_report(self, results: Dict[str, ConstraintResult]) -> Dict[str, Any]:
        """Generate a comprehensive constraint evaluation report"""
        total_constraints = len(results)
        passed_constraints = sum(1 for r in results.values() if r.passed)
        failed_constraints = total_constraints - passed_constraints
        
        # Group by severity
        severity_summary = {}
        for severity in ConstraintSeverity:
            severity_results = [r for r in results.values() if r.severity == severity]
            severity_summary[severity.value] = {
                'total': len(severity_results),
                'passed': sum(1 for r in severity_results if r.passed),
                'failed': sum(1 for r in severity_results if not r.passed)
            }
        
        # Collect all violations
        all_violations = []
        for result in results.values():
            if not result.passed:
                all_violations.extend(result.violations)
        
        return {
            'summary': {
                'total_constraints': total_constraints,
                'passed': passed_constraints,
                'failed': failed_constraints,
                'pass_rate': (passed_constraints / total_constraints * 100) if total_constraints > 0 else 0
            },
            'by_severity': severity_summary,
            'violations': all_violations,
            'constraint_details': {c_id: {'passed': r.passed, 'message': r.message} for c_id, r in results.items()}
        }
