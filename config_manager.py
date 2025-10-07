import json
import os
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional  # Make sure List is imported

class ConfigManager:
    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration manager with optional config file"""
        self.config_file = config_file
        self.settings = self._get_default_settings()
        
        # If config file is provided, try to load it
        if config_file and os.path.exists(config_file):
            self.load_from_file(config_file)
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Return default settings configuration"""
        return {
            # Staff requirements
            'min_morning_staff': 3,
            'max_afternoon_staff': 1,
            'night_staff': 1,
            'saturday_morning_staff': 1,
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
            'fill_up_to_minimum_hours': False,  # Add extra shifts to reach minimum hours
            'append_statistics_to_schedule': True,  # Append staff statistics to schedule CSV output
            'prevent_consecutive_weekend_days': False,  # Prevent working both Saturday and Sunday in same weekend
            
            # Data file names
            'data_files': {
                'people_data_file': 'desiderata',     # Name for people/constraints data file (without extension)
                'night_dates_file': 'notti',          # Name for required night dates file (without extension)
                'festivity_dates_file': 'festivi'     # Name for festivity dates file (without extension)
            },
            
            # Bias mitigation settings
            'randomize_people_order': False,  # Randomize people order at start of scheduling
            'randomize_priority_tiebreaking': False,  # Add randomization to priority scoring
            
            # Priority assignment settings
            'priority_assignment': {
                'night_priority_enabled': True,    # Use night priority from CSV data
                'weekend_priority_enabled': True,  # Use weekend priority from CSV data
                'priority_weight': 1.0             # Weight factor for priority in scoring
            },
            
            # Workload balancing settings
            'workload_balancing': {
                'enabled': False,  # Enable/disable workload balancing
                'night_burden_coefficient': 1.5,  # Each night reduces afternoon target by this much
                'weekend_burden_coefficient': 0.8,  # Each weekend day reduces afternoon target by this much
                'min_afternoon_shifts': 0,  # Never go below this many afternoon shifts per person
                'max_afternoon_compensation': 4  # Maximum afternoon shift reduction per person
            },
            
            # Multi-run optimization settings
            'multi_run': {
                'enabled': False,           # Enable multi-run optimization
                'max_runs': 100,           # Maximum number of runs to attempt
                'target_fails': 0,         # Stop early if this many or fewer constraints fail (0 = perfect solution)
                'enable_randomization_for_multi_run': True,  # Enable randomization during multi-run
                'silence_output': True,    # Silence all output during multi-run execution (except final results)
                'show_progress_bar': True, # Show progress bar during multi-run execution
                'enforce_desiderata': True  # Only consider runs that comply with forbidden shifts and vacation constraints
            },
            
            # Afternoon shift balancing
            'afternoon_balancing': {
                'enabled': True,
                'deprioritize_weekly_repeats': True,
                'consider_weekly_hours': True,
                'max_consecutive_afternoons': 1,
                'enforce_strict_weekly_balance': True,
                'consider_weekends_afternoons': True,  # Default to True for backward compatibility
                'give_precedence_to_afternoon_over_morning': False  # Default to False for backward compatibility
            },
            
            # Logging/Output verbosity settings
            'logging': {
                'data_loading': 'info',              # silence, error, info, debug
                'settings_display': 'info',          # silence, error, info, debug  
                'multi_run_optimization': 'info',    # silence, error, info, debug
                'night_shift_assignment': 'info',    # silence, error, info, debug
                'workload_balancing': 'debug',       # silence, error, info, debug
                'weekend_shift_balancing': 'debug',  # silence, error, info, debug
                'fill_up_minimum_hours': 'info',     # silence, error, info, debug
                'shift_assignment_warnings': 'error', # silence, error, info, debug
                'constraint_verification': 'info',   # silence, error, info, debug
                'schedule_display': 'info',          # silence, error, info, debug
                'summary_statistics': 'info',       # silence, error, info, debug
                'export_notifications': 'info'      # silence, error, info, debug
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value with optional default"""
        keys = key.split('.')
        value = self.settings
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set a setting value using dot notation"""
        keys = key.split('.')
        current = self.settings
        
        # Navigate to the parent dictionary
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = value
    
    def update(self, new_settings: Dict[str, Any]) -> None:
        """Update settings with new values (deep merge)"""
        self._deep_update(self.settings, new_settings)
    
    def _deep_update(self, base_dict: Dict, update_dict: Dict) -> None:
        """Recursively update nested dictionaries"""
        for key, value in update_dict.items():
            if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
    
    def validate_settings(self) -> Tuple[bool, List[str]]:  # Use Tuple instead of tuple
        """Validate current settings and return (is_valid, error_list)"""
        errors = []
        
        # Validate numeric constraints
        numeric_validations = [
            ('min_morning_staff', 0, 20),
            ('max_afternoon_staff', 0, 10),
            ('night_staff', 0, 5),
            ('min_weekly_hours', 0, 60),
            ('max_weekly_hours', 0, 60),
            ('morning_shift_hours', 1, 24),
            ('afternoon_shift_hours', 1, 24),
            ('night_shift_hours', 1, 24),
            ('sunday_mp_shift_hours', 1, 24),
            ('max_weekend_days_per_month', 0, 31),
            ('night_shifts_per_month', 0, 31),
            ('max_consecutive_days', 1, 31),
        ]
        
        for setting, min_val, max_val in numeric_validations:
            value = self.get(setting)
            if not isinstance(value, (int, float)) or not (min_val <= value <= max_val):
                errors.append(f"Setting '{setting}' must be a number between {min_val} and {max_val}, got: {value}")
        
        # Validate logical constraints
        if self.get('min_weekly_hours') > self.get('max_weekly_hours'):
            errors.append("min_weekly_hours cannot be greater than max_weekly_hours")
        
        # Validate logging levels
        valid_log_levels = ['silence', 'error', 'info', 'debug']
        logging_settings = self.get('logging', {})
        for category, level in logging_settings.items():
            if level not in valid_log_levels:
                errors.append(f"Invalid logging level '{level}' for category '{category}'. Must be one of: {valid_log_levels}")
        
        # Validate workload balancing settings
        wb_settings = self.get('workload_balancing', {})
        if wb_settings.get('enabled', False):
            if not isinstance(wb_settings.get('night_burden_coefficient'), (int, float)):
                errors.append("workload_balancing.night_burden_coefficient must be a number")
            if not isinstance(wb_settings.get('weekend_burden_coefficient'), (int, float)):
                errors.append("workload_balancing.weekend_burden_coefficient must be a number")
        
        # Validate multi-run settings
        multi_run = self.get('multi_run', {})
        if multi_run.get('enabled', False):
            max_runs = multi_run.get('max_runs', 0)
            if not isinstance(max_runs, int) or max_runs < 1 or max_runs > 100000:
                errors.append("multi_run.max_runs must be an integer between 1 and 100000")
        
        # Validate priority assignment settings
        priority_settings = self.get('priority_assignment', {})
        priority_weight = priority_settings.get('priority_weight', 1.0)
        if not isinstance(priority_weight, (int, float)) or priority_weight < 0:
            errors.append("priority_assignment.priority_weight must be a non-negative number")
        
        # Validate data file settings
        data_files = self.get('data_files', {})
        required_files = ['people_data_file', 'night_dates_file', 'festivity_dates_file']
        for file_key in required_files:
            file_name = data_files.get(file_key, '')
            if not isinstance(file_name, str) or not file_name.strip():
                errors.append(f"data_files.{file_key} must be a non-empty string")
        
        return len(errors) == 0, errors
    
    def load_from_file(self, config_file: str) -> bool:
        """Load settings from JSON file"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                loaded_settings = json.load(f)
            
            # Validate loaded settings
            temp_config = ConfigManager()
            temp_config.update(loaded_settings)
            is_valid, errors = temp_config.validate_settings()
            
            if not is_valid:
                print(f"Configuration validation errors in {config_file}:")
                for error in errors:
                    print(f"  - {error}")
                return False
            
            # If valid, update our settings
            self.update(loaded_settings)
            self.config_file = config_file
            return True
            
        except FileNotFoundError:
            print(f"Configuration file not found: {config_file}")
            return False
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in configuration file {config_file}: {e}")
            return False
        except Exception as e:
            print(f"Error loading configuration from {config_file}: {e}")
            return False
    
    def save_to_file(self, config_file: Optional[str] = None) -> bool:
        """Save current settings to JSON file"""
        file_path = config_file or self.config_file or 'scheduler_config.json'
        
        try:
            # Validate before saving
            is_valid, errors = self.validate_settings()
            if not is_valid:
                print("Cannot save invalid configuration:")
                for error in errors:
                    print(f"  - {error}")
                return False
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            
            self.config_file = file_path
            return True
            
        except Exception as e:
            print(f"Error saving configuration to {file_path}: {e}")
            return False
    
    def create_template(self, template_file: str) -> bool:
        """Create a template configuration file with comments"""
        template_content = {
            "_comments": {
                "description": "Hospital Scheduler Configuration Template",
                "staff_requirements": "Set minimum/maximum staff for different shifts",
                "working_hours": "Configure shift durations and weekly hour limits", 
                "constraints": "Set monthly and daily scheduling limits",
                "optimization": "Configure multi-run optimization and balancing",
                "logging": "Control output verbosity for different categories"
            },
            **self._get_default_settings()
        }
        
        try:
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_content, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error creating template file {template_file}: {e}")
            return False
    
    def get_preset(self, preset_name: str) -> Optional[Dict[str, Any]]:
        """Get predefined configuration presets"""
        presets = {
            'strict': {
                'fill_up_to_minimum_hours': True,
                'workload_balancing': {'enabled': False},
                'randomize_people_order': False,
                'randomize_priority_tiebreaking': False,
                'multi_run': {'enabled': False},
                'logging': {k: 'error' for k in self.settings['logging'].keys()}
            },
            'balanced': {
                'fill_up_to_minimum_hours': True,
                'workload_balancing': {
                    'enabled': True,
                    'night_burden_coefficient': 1.5,
                    'weekend_burden_coefficient': 0.8
                },
                'afternoon_balancing': {'enabled': True},
                'randomize_people_order': True,
                'multi_run': {'enabled': False},
                'logging': {k: 'info' if k in ['summary_statistics', 'export_notifications'] else 'error' 
                          for k in self.settings['logging'].keys()}
            },
            'optimized': {
                'fill_up_to_minimum_hours': True,
                'workload_balancing': {'enabled': True},
                'afternoon_balancing': {'enabled': True},
                'randomize_people_order': True,
                'randomize_priority_tiebreaking': True,
                'multi_run': {
                    'enabled': True,
                    'max_runs': 50,
                    'target_fails': 0,
                    'enable_randomization_for_multi_run': True
                },
                'logging': {k: 'info' if k in ['multi_run_optimization', 'summary_statistics', 'export_notifications'] else 'error' 
                          for k in self.settings['logging'].keys()}
            },
            'debug': {
                'logging': {k: 'debug' for k in self.settings['logging'].keys()}
            }
        }
        
        return presets.get(preset_name)
    
    def apply_preset(self, preset_name: str) -> bool:
        """Apply a predefined configuration preset"""
        preset = self.get_preset(preset_name)
        if preset:
            self.update(preset)
            return True
        return False
    
    def list_presets(self) -> List[str]:  # Change list[str] to List[str]
        """Get list of available preset names"""
        return ['strict', 'balanced', 'optimized', 'debug']
    
    def print_summary(self) -> None:
        """Print a summary of current configuration"""
        print("=== CONFIGURATION SUMMARY ===")
        print(f"Staff Requirements:")
        print(f"  Morning (weekdays): {self.get('min_morning_staff')}")
        print(f"  Afternoon (max): {self.get('max_afternoon_staff')}")
        print(f"  Night: {self.get('night_staff')}")
        print(f"  Sunday MP: {self.get('sunday_staff')}")
        print(f"  Festivity MP: {self.get('festivity_staff')}")
        
        print(f"\nWorking Hours:")
        print(f"  Weekly range: {self.get('min_weekly_hours')}-{self.get('max_weekly_hours')}h")
        print(f"  Shift durations: M={self.get('morning_shift_hours')}h, P={self.get('afternoon_shift_hours')}h, N={self.get('night_shift_hours')}h")
        
        print(f"\nConstraints:")
        print(f"  Max consecutive days: {self.get('max_consecutive_days')}")
        print(f"  Max weekend days/month: {self.get('max_weekend_days_per_month')}")
        print(f"  Night shifts/month: {self.get('night_shifts_per_month')}")
        
        print(f"\nOptimization:")
        print(f"  Workload balancing: {'ENABLED' if self.get('workload_balancing.enabled') else 'DISABLED'}")
        print(f"  Multi-run optimization: {'ENABLED' if self.get('multi_run.enabled') else 'DISABLED'}")
        print(f"  Fill minimum hours: {'YES' if self.get('fill_up_to_minimum_hours') else 'NO'}")
        print(f"  Night priority: {'ENABLED' if self.get('priority_assignment.night_priority_enabled') else 'DISABLED'}")
        print(f"  Weekend priority: {'ENABLED' if self.get('priority_assignment.weekend_priority_enabled') else 'DISABLED'}")
        print(f"  Append statistics to CSV: {'YES' if self.get('append_statistics_to_schedule') else 'NO'}")
        
        print(f"\nData Files:")
        print(f"  People data: {self.get('data_files.people_data_file')}.csv/.xlsx/.xls")
        print(f"  Night dates: {self.get('data_files.night_dates_file')}.csv/.xlsx/.xls")
        print(f"  Festivity dates: {self.get('data_files.festivity_dates_file')}.csv/.xlsx/.xls")
        print(f"  Prevent consecutive weekends: {'YES' if self.get('prevent_consecutive_weekend_days') else 'NO'}")
        
        # Show validation status
        is_valid, errors = self.validate_settings()
        print(f"\nValidation: {'✅ VALID' if is_valid else '❌ INVALID'}")
        if errors:
            for error in errors[:3]:  # Show first 3 errors
                print(f"  - {error}")
            if len(errors) > 3:
                print(f"  ... and {len(errors) - 3} more errors")
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get a copy of all current settings"""
        import copy
        return copy.deepcopy(self.settings)
    
    def reset_to_defaults(self) -> None:
        """Reset all settings to default values"""
        self.settings = self._get_default_settings()
