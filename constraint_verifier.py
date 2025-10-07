import csv
from datetime import timedelta
from constraint_rules_engine import ConstraintRulesEngine, ConstraintSeverity

class ConstraintVerifier:
    """Verifies schedule constraints using the new rules engine"""
    
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.logger = scheduler.logger
        self.rules_engine = ConstraintRulesEngine(scheduler)
    
    def verify_constraints(self, start_date, end_date):
        """Verify all constraints using the rules engine"""
        self.logger.log('constraint_verification', 'info', "=== CONSTRAINT VERIFICATION ===")
        
        # Evaluate all constraints
        results = self.rules_engine.evaluate_all(start_date, end_date)
        
        # Convert results to the old format for compatibility
        constraint_status = {}
        
        for constraint_id, result in results.items():
            status = 'PASS' if result.passed else 'FAIL'
            constraint_status[constraint_id] = status
            
            # Log result
            level = 'info' if result.passed else 'error'
            self.logger.log('constraint_verification', level, f"{result.name}: {status}")
            
            if not result.passed and result.violations:
                for violation in result.violations:
                    self.logger.log('constraint_verification', 'error', f"  - {violation}")
        
        # Print summary
        self._print_summary(results)
        
        return constraint_status
    
    def verify_constraint_group(self, group_name: str, start_date, end_date):
        """Verify constraints in a specific group"""
        self.logger.log('constraint_verification', 'info', f"=== VERIFYING {group_name.upper()} CONSTRAINTS ===")
        
        results = self.rules_engine.evaluate_group(group_name, start_date, end_date)
        
        constraint_status = {}
        for constraint_id, result in results.items():
            status = 'PASS' if result.passed else 'FAIL'
            constraint_status[constraint_id] = status
            
            level = 'info' if result.passed else 'error'
            self.logger.log('constraint_verification', level, f"{result.name}: {status}")
            
            if not result.passed and result.violations:
                for violation in result.violations:
                    self.logger.log('constraint_verification', 'error', f"  - {violation}")
        
        return constraint_status
    
    def add_custom_constraint(self, constraint_id: str, name: str, description: str, 
                            evaluation_func, severity: str = "MEDIUM"):
        """Add a custom constraint to the rules engine"""
        self.rules_engine.add_custom_constraint(constraint_id, name, description, evaluation_func, severity)
    
    def enable_constraint(self, constraint_id: str):
        """Enable a specific constraint"""
        self.rules_engine.enable_constraint(constraint_id)
    
    def disable_constraint(self, constraint_id: str):
        """Disable a specific constraint"""
        self.rules_engine.disable_constraint(constraint_id)
    
    def get_available_constraints(self):
        """Get information about all available constraints"""
        return self.rules_engine.get_all_constraints_info()
    
    def get_constraint_groups(self):
        """Get constraint groups"""
        return self.rules_engine.get_constraint_groups()
    
    def _print_summary(self, results):
        """Print constraint verification summary"""
        if not self.logger.should_log('constraint_verification', 'info'):
            return
        
        print("\n=== CONSTRAINT VERIFICATION SUMMARY ===")
        
        # Group results by severity and status
        critical_fail = []
        high_fail = []
        medium_fail = []
        low_fail = []
        passed = []
        
        for constraint_id, result in results.items():
            if result.passed:
                passed.append(result)
            else:
                if result.severity == ConstraintSeverity.CRITICAL:
                    critical_fail.append(result)
                elif result.severity == ConstraintSeverity.HIGH:
                    high_fail.append(result)
                elif result.severity == ConstraintSeverity.MEDIUM:
                    medium_fail.append(result)
                else:
                    low_fail.append(result)
        
        # Print summary
        total = len(results)
        passed_count = len(passed)
        failed_count = total - passed_count
        
        print(f"Total constraints: {total}")
        print(f"✅ Passed: {passed_count}")
        print(f"❌ Failed: {failed_count}")
        
        if critical_fail:
            print(f"\n🚨 CRITICAL FAILURES ({len(critical_fail)}):")
            for result in critical_fail:
                print(f"  - {result.name}: {result.message}")
        
        if high_fail:
            print(f"\n⚠️  HIGH PRIORITY FAILURES ({len(high_fail)}):")
            for result in high_fail:
                print(f"  - {result.name}: {result.message}")
        
        if medium_fail:
            print(f"\n⚡ MEDIUM PRIORITY FAILURES ({len(medium_fail)}):")
            for result in medium_fail:
                print(f"  - {result.name}: {result.message}")
        
        if low_fail:
            print(f"\n💡 LOW PRIORITY FAILURES ({len(low_fail)}):")
            for result in low_fail:
                print(f"  - {result.name}: {result.message}")
        
        print()
        
        # Overall status
        if not failed_count:
            print("🎉 All constraints satisfied!")
        elif critical_fail:
            print("🚨 Critical constraint violations found - schedule may not be viable")
        elif high_fail:
            print("⚠️  Important constraint violations found - schedule needs attention")
        else:
            print("⚡ Minor constraint violations found - schedule is acceptable")
