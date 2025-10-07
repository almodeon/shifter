from datetime import timedelta
from constraint_rules_engine import ConstraintRulesEngine

class ConstraintVerifier:
    """Verifies schedule constraints and provides detailed feedback"""
    
    def __init__(self, scheduler):
        """Initialize with reference to main scheduler for accessing settings, people, schedule, etc."""
        self.scheduler = scheduler
        self.logger = scheduler.logger
        
        # Initialize the constraint rules engine with settings
        self.rules_engine = ConstraintRulesEngine(scheduler, scheduler.logger, scheduler.settings)
        
        # Initialize last_report for storing the most recent report
        self.last_report = None
    
    def verify_constraints(self, start_date, end_date):
        """Comprehensive constraint verification using the rules engine"""
        self.logger.log('constraint_verification', 'info', "\n" + "="*80)
        self.logger.log('constraint_verification', 'info', "CONSTRAINT VERIFICATION (Rules Engine)")
        self.logger.log('constraint_verification', 'info', "="*80)
        
        # Evaluate all constraints using the rules engine
        results = self.rules_engine.evaluate_all(start_date, end_date)
        
        # Convert results to the expected format for backward compatibility
        constraint_status = {}
        for constraint_id, result in results.items():
            constraint_status[constraint_id] = 'PASS' if result.passed else 'FAIL'
        
        # Generate and log summary
        self._print_summary(results)
        
        # Generate detailed report
        report = self.rules_engine.generate_constraint_report(results)
        
        # Store the detailed report for potential export
        self.last_report = report
        
        return constraint_status
    
    def verify_constraint_group(self, group_name: str, start_date, end_date):
        """Verify a specific group of constraints"""
        self.logger.log('constraint_verification', 'info', f"\n=== VERIFYING CONSTRAINT GROUP: {group_name.upper()} ===")
        
        results = self.rules_engine.evaluate_group(group_name, start_date, end_date)
        
        constraint_status = {}
        for constraint_id, result in results.items():
            constraint_status[constraint_id] = 'PASS' if result.passed else 'FAIL'
        
        return constraint_status
    
    def add_custom_constraint(self, constraint_id: str, name: str, description: str, 
                            evaluation_func, severity: str = "MEDIUM"):
        """Add a custom constraint to the rules engine"""
        from constraint_rules_engine import ConstraintSeverity
        
        severity_map = {
            "CRITICAL": ConstraintSeverity.CRITICAL,
            "HIGH": ConstraintSeverity.HIGH,
            "MEDIUM": ConstraintSeverity.MEDIUM,
            "LOW": ConstraintSeverity.LOW
        }
        
        sev = severity_map.get(severity.upper(), ConstraintSeverity.MEDIUM)
        self.rules_engine.add_custom_constraint(constraint_id, name, description, evaluation_func, sev)
    
    def enable_constraint(self, constraint_id: str):
        """Enable a specific constraint"""
        self.rules_engine.enable_constraint(constraint_id)
    
    def disable_constraint(self, constraint_id: str):
        """Disable a specific constraint"""
        self.rules_engine.disable_constraint(constraint_id)
    
    def get_available_constraints(self):
        """Get information about all available constraints"""
        return self.rules_engine.get_constraint_info()
    
    def get_constraint_groups(self):
        """Get available constraint groups"""
        return self.rules_engine.get_constraint_groups()
    
    def _print_summary(self, results):
        """Print constraint verification summary using rules engine results"""
        self.logger.log('constraint_verification', 'info', "\n" + "="*80)
        self.logger.log('constraint_verification', 'info', "CONSTRAINT VERIFICATION SUMMARY")
        self.logger.log('constraint_verification', 'info', "="*80)
        
        passed = sum(1 for result in results.values() if result.passed)
        total = len(results)
        
        if self.scheduler._should_log('constraint_verification', 'info'):
            for i, (constraint_id, result) in enumerate(results.items(), 1):
                status_symbol = "✅" if result.passed else "❌"
                constraint_name = self.rules_engine.constraints[constraint_id].name
                print(f"{i:2}. {constraint_name:<30} {status_symbol} {'PASS' if result.passed else 'FAIL'}")
        
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
    