class Logger:
    def __init__(self, settings=None):
        """Initialize logger with settings"""
        self.LOG_LEVELS = {'silence': 0, 'error': 1, 'info': 2, 'debug': 3}
        self.log_entries = []  # Store log messages
        
        # Default logging settings
        self.logging_settings = {
            'data_loading': 'info',
            'settings_display': 'info',
            'multi_run_optimization': 'info',
            'night_shift_assignment': 'info',
            'workload_balancing': 'debug',
            'weekend_shift_balancing': 'debug',
            'fill_up_minimum_hours': 'info',
            'shift_assignment_warnings': 'error',
            'constraint_verification': 'info',
            'schedule_display': 'info',
            'summary_statistics': 'info',
            'export_notifications': 'info'
        }
        
        # Override with provided settings
        if settings and 'logging' in settings:
            self.logging_settings.update(settings['logging'])
    
    def log(self, category, level, message):
        """Log message if it meets the level criteria for the category"""
        category_level = self.logging_settings.get(category, 'info')
        if self.LOG_LEVELS[level] <= self.LOG_LEVELS[category_level]:
            log_entry = {'level': level, 'category': category, 'message': message}
            self.log_entries.append(log_entry)  # Store the log message as a dictionary
            print(message)
    
    def get_all_logs(self):
        """Retrieve all log entries"""
        return self.log_entries
    
    def should_log(self, category, level):
        """Check if we should log at this level for this category"""
        category_level = self.logging_settings.get(category, 'info')
        return self.LOG_LEVELS[level] <= self.LOG_LEVELS[category_level]
    
    def update_settings(self, logging_settings):
        """Update logging settings"""
        self.logging_settings.update(logging_settings)
